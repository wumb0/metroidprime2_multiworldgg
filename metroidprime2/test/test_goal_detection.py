"""Tests for ``client/client.py``'s goal detection and pickup-counter
handling (PLAN.md section P), which replaced section O's
single-shared-counter ``_handle_magic_item_amount`` (exact-match sentinel
arithmetic against ``GOAL_SENTINEL_AMOUNT``) and its
``location_reconciliation`` subset-sum fallback entirely.

Goal detection is a memory read (``_handle_check_goal``): the client reads
the current MLVL and the current area's TAreaId
(``EchoesInterface.current_mlvl`` / ``current_area_id``) and declares the
goal when the area is one of the ending areas
(``constants.GAME_END_AREA_INDICES``). This mirrors
``worlds/metroidprime``'s "current level == End_of_Game" check. Both older
approaches rode on a persistent counter instead, and neither worked: the
in-ISO Credits-area trigger that set the counter to a sentinel never fired
in practice, and while it was live, unrelated pickup arithmetic on that
same shared counter could sum past the sentinel and declare victory early.
No counter amount can declare the goal at all now.

The pickup counters are tested separately, against the new protocol. The
old design's fundamental problem (section O fixed only its *false victory*
symptom, not the underlying loss of identity): every pickup ADDs
``pickup_index + 1`` to one shared counter, so two pickups collected in the
same disconnect window merge into an ambiguous sum with no way to recover
which pickups produced it. Section P's fix is a new encoding (one bit per
pickup, spread across several persistent counters, ``pickup_encoding.py``)
rather than a smarter decoder, so these tests exercise the four pickup
bitmask counters directly (decoded via ``pickup_encoding.decode``),
including the multi-pickup-disconnect case that motivated the redesign --
several bits set across several counters at once, all reported, none
invented.
"""

from __future__ import annotations

import os
import unittest
from typing import Any

# See test_deathlink.py's identical comment: importing client.client pulls
# in CommonClient, which without this env var (set before CommonClient's
# first import anywhere in the process) and the network_data_package stub
# below would shell out to pip / import every world package.
os.environ.setdefault("SKIP_REQUIREMENTS_UPDATE", "1")

import worlds

if "network_data_package" not in worlds.__dict__:
    worlds.network_data_package = {"games": {}}
    worlds.network_data_package_single_game = {}

from .. import constants
from ..client.client import _handle_check_goal, _handle_pickup_counters
from ..pickup_encoding import counter_and_amount

_END_AREA = min(constants.GAME_END_AREA_INDICES)


class _FakeGameInterface:
    def __init__(
        self,
        mlvl: int | None = None,
        area: int | None = None,
    ) -> None:
        self.consumed_calls: list[list[tuple[int, int]]] = []
        self.mlvl = mlvl
        self.area = area

    def consume_counters(self, deltas: list[tuple[int, int]]) -> list[tuple[int, int]]:
        self.consumed_calls.append(list(deltas))
        return []

    def current_mlvl(self) -> int | None:
        return self.mlvl

    def current_area_id(self) -> int | None:
        return self.area


class _FakeContext:
    def __init__(
        self,
        missing_locations: set[int] | None = None,
        mlvl: int | None = None,
        area: int | None = None,
        slot: int | None = 1,
    ) -> None:
        self.sent_msgs: list[list[dict[str, Any]]] = []
        self.finished_game = False
        self.game_interface = _FakeGameInterface(mlvl=mlvl, area=area)
        self.missing_locations: set[int] = missing_locations if missing_locations is not None else set()
        self.slot = slot

    async def send_msgs(self, msgs: list[dict[str, Any]]) -> None:
        self.sent_msgs.append(msgs)


def _inventory(**counter_amounts: int) -> dict[int, tuple[int, int]]:
    """Builds a full ``{item_id: (amount, capacity)}`` inventory snapshot
    (the shape ``EchoesInterface.read_inventory`` returns) with every
    counter in ``constants.PICKUP_COUNTER_ITEMS`` defaulting to 0,
    overridden by keyword args named ``item_<id>``."""
    inventory: dict[int, tuple[int, int]] = dict.fromkeys(constants.PICKUP_COUNTER_ITEMS, (0, 0))
    for key, amount in counter_amounts.items():
        item_id = int(key.removeprefix("item_"))
        inventory[item_id] = (amount, 0)
    return inventory


def _run(ctx: _FakeContext, inventory: dict[int, tuple[int, int]]) -> None:
    import asyncio

    asyncio.run(_handle_pickup_counters(ctx, inventory))  # type: ignore[arg-type]


def _run_goal(ctx: _FakeContext) -> None:
    import asyncio

    asyncio.run(_handle_check_goal(ctx))  # type: ignore[arg-type]


def _goal_ctx(area: int | None = _END_AREA, mlvl: int | None = constants.TEMPLE_GROUNDS_MLVL) -> _FakeContext:
    return _FakeContext(mlvl=mlvl, area=area)


class TestMemoryGoalDetection(unittest.TestCase):
    def test_every_ending_area_declares_goal(self) -> None:
        for area in constants.GAME_END_AREA_INDICES:
            ctx = _goal_ctx(area=area)
            _run_goal(ctx)
            self.assertTrue(ctx.finished_game, f"area {area} did not declare goal")

    def test_goal_only_declared_once(self) -> None:
        ctx = _goal_ctx()
        _run_goal(ctx)
        _run_goal(ctx)
        self.assertEqual(1, len(ctx.sent_msgs))

    def test_non_ending_area_does_not_declare_goal(self) -> None:
        # Area index 0 (Temple Grounds, but not an ending area).
        ctx = _goal_ctx(area=0)
        _run_goal(ctx)
        self.assertFalse(ctx.finished_game)
        self.assertEqual([], ctx.sent_msgs)

    def test_other_mlvl_does_not_declare_goal(self) -> None:
        # Same numeric area index, but a different MLVL -- the index is only
        # meaningful within Temple Grounds.
        ctx = _goal_ctx(area=_END_AREA, mlvl=0x42B935E4)  # Agon Wastes
        _run_goal(ctx)
        self.assertFalse(ctx.finished_game)
        self.assertEqual([], ctx.sent_msgs)

    def test_none_reads_do_not_declare_goal(self) -> None:
        ctx = _goal_ctx(area=None, mlvl=None)
        _run_goal(ctx)
        self.assertFalse(ctx.finished_game)

    def test_no_slot_does_not_declare_goal(self) -> None:
        ctx = _goal_ctx()
        ctx.slot = None
        _run_goal(ctx)
        self.assertFalse(ctx.finished_game)
        self.assertEqual([], ctx.sent_msgs)


class TestPickupBitmaskCounters(unittest.TestCase):
    def test_no_pickup_counter_amount_ever_declares_the_goal(self) -> None:
        """The premature-goal bug (section O) and the sentinel it was built
        on are both gone: no amount on any pickup counter -- including the
        old 120 sentinel and sums past it -- can finish the game."""
        for amount in (1, 120, 121, 2**constants.BITS_PER_COUNTER - 1):
            for item_id in constants.PICKUP_COUNTER_ITEMS:
                ctx = _FakeContext()
                _run(ctx, _inventory(**{f"item_{item_id}": amount}))
                self.assertFalse(ctx.finished_game, f"item {item_id} amount {amount} declared the goal")
                self.assertTrue(
                    all(msg[0]["cmd"] == "LocationChecks" for msg in ctx.sent_msgs),
                    f"item {item_id} amount {amount} sent something other than location checks",
                )

    def test_single_pickup_bit_sends_check_only(self) -> None:
        ctx = _FakeContext()
        item_id, bit = counter_and_amount(3)
        inventory = _inventory(**{f"item_{item_id}": bit})
        _run(ctx, inventory)
        self.assertFalse(ctx.finished_game)
        self.assertEqual(
            [[{"cmd": "LocationChecks", "locations": [constants.LOCATION_ID_BASE + 3]}]],
            ctx.sent_msgs,
        )
        self.assertEqual([[(item_id, -bit)]], ctx.game_interface.consumed_calls)

    def test_multi_pickup_disconnect_across_several_counters_reports_all_none_invented(self) -> None:
        """The case that motivated section P: several pickups collected
        while disconnected, landing bits across several different
        counters. Every one of them must be reported, and nothing else --
        this is exactly what the old shared-additive-counter design (and
        its location_reconciliation subset-sum fallback, removed by this
        section) could not reliably do."""
        indices = [0, 14, 20, 44, 60, 118]  # spread across all four counters
        by_item: dict[int, int] = {}
        for index in indices:
            item_id, bit = counter_and_amount(index)
            by_item[item_id] = by_item.get(item_id, 0) | bit

        ctx = _FakeContext()
        inventory = _inventory(**{f"item_{item_id}": amount for item_id, amount in by_item.items()})
        _run(ctx, inventory)

        self.assertFalse(ctx.finished_game)
        self.assertEqual(1, len(ctx.sent_msgs))
        sent = ctx.sent_msgs[0][0]
        self.assertEqual("LocationChecks", sent["cmd"])
        self.assertEqual(
            sorted(constants.LOCATION_ID_BASE + idx for idx in indices),
            sorted(sent["locations"]),
        )
        # Every nonzero counter consumed regardless of branch, by its exact
        # read amount (PLAN.md section P point 2).
        [consumed] = ctx.game_interface.consumed_calls
        self.assertEqual(sorted(by_item.items()), sorted((item_id, -amount) for item_id, amount in consumed))

    def test_no_counters_nonzero_sends_nothing(self) -> None:
        ctx = _FakeContext()
        _run(ctx, _inventory())
        self.assertEqual([], ctx.sent_msgs)
        self.assertEqual([], ctx.game_interface.consumed_calls)


if __name__ == "__main__":
    unittest.main()
