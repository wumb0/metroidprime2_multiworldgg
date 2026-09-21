"""Regression tests for ``client/client.py``'s pickup-counter handling
(PLAN.md section P), which replaced section O's single-shared-counter
``_handle_magic_item_amount`` (exact-match sentinel arithmetic against
``constants.GOAL_SENTINEL_AMOUNT``) and its ``location_reconciliation``
subset-sum fallback entirely.

The old design's fundamental problem (section O fixed only its *false
victory* symptom, not the underlying loss of identity): every pickup ADDs
``pickup_index + 1`` to one shared counter, so two pickups collected in the
same disconnect window merge into an ambiguous sum with no way to recover
which pickups produced it. Section P's fix is a new encoding (one bit per
pickup, spread across several persistent counters, ``pickup_encoding.py``)
rather than a smarter decoder, so these tests exercise the new counter
protocol directly: the goal counter (checked first, independently, "amount
nonzero" only) and the four pickup bitmask counters (decoded via
``pickup_encoding.decode``), including the multi-pickup-disconnect case
that motivated the redesign -- several bits set across several counters at
once, all reported, none invented.
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
from ..client.client import _handle_pickup_counters
from ..pickup_encoding import counter_and_amount


class _FakeGameInterface:
    def __init__(self) -> None:
        self.consumed_calls: list[list[tuple[int, int]]] = []

    def consume_counters(self, deltas: list[tuple[int, int]]) -> list[tuple[int, int]]:
        self.consumed_calls.append(list(deltas))
        return []


class _FakeContext:
    def __init__(self, missing_locations: set[int] | None = None) -> None:
        self.sent_msgs: list[list[dict[str, Any]]] = []
        self.finished_game = False
        self.game_interface = _FakeGameInterface()
        self.missing_locations: set[int] = missing_locations if missing_locations is not None else set()

    async def send_msgs(self, msgs: list[dict[str, Any]]) -> None:
        self.sent_msgs.append(msgs)


def _inventory(**counter_amounts: int) -> dict[int, tuple[int, int]]:
    """Builds a full ``{item_id: (amount, capacity)}`` inventory snapshot
    (the shape ``EchoesInterface.read_inventory`` returns) with every
    counter in ``constants.ALL_COUNTER_ITEMS`` defaulting to 0, overridden
    by keyword args named ``item_<id>``."""
    inventory: dict[int, tuple[int, int]] = dict.fromkeys(constants.ALL_COUNTER_ITEMS, (0, 0))
    for key, amount in counter_amounts.items():
        item_id = int(key.removeprefix("item_"))
        inventory[item_id] = (amount, 0)
    return inventory


def _run(ctx: _FakeContext, inventory: dict[int, tuple[int, int]]) -> None:
    import asyncio

    asyncio.run(_handle_pickup_counters(ctx, inventory))  # type: ignore[arg-type]


class TestGoalCounter(unittest.TestCase):
    def test_goal_counter_nonzero_declares_goal(self) -> None:
        ctx = _FakeContext()
        inventory = _inventory(**{f"item_{constants.GOAL_COUNTER_ITEM}": constants.GOAL_SIGNAL_AMOUNT})
        _run(ctx, inventory)
        self.assertTrue(ctx.finished_game)
        self.assertEqual(1, len(ctx.sent_msgs))
        self.assertEqual("StatusUpdate", ctx.sent_msgs[0][0]["cmd"])

    def test_goal_correct_under_add_semantics_too(self) -> None:
        """Section P constraint 5: the goal check is "amount nonzero", not
        an exact match against a specific value, so it's correct whether
        the in-ISO SetInventoryAmount sets or adds -- an amount of, say, 3
        (accumulated adds) must still declare the goal."""
        ctx = _FakeContext()
        inventory = _inventory(**{f"item_{constants.GOAL_COUNTER_ITEM}": 3})
        _run(ctx, inventory)
        self.assertTrue(ctx.finished_game)

    def test_goal_declared_once(self) -> None:
        ctx = _FakeContext()
        inventory = _inventory(**{f"item_{constants.GOAL_COUNTER_ITEM}": constants.GOAL_SIGNAL_AMOUNT})
        _run(ctx, inventory)
        _run(ctx, inventory)
        self.assertEqual(1, len(ctx.sent_msgs))

    def test_goal_counter_consumed_on_every_call(self) -> None:
        """Every nonzero counter is consumed regardless of branch -- the
        goal branch consumes even after finished_game is already True, so
        a leftover amount can never survive to be misread later."""
        ctx = _FakeContext()
        inventory = _inventory(**{f"item_{constants.GOAL_COUNTER_ITEM}": constants.GOAL_SIGNAL_AMOUNT})
        _run(ctx, inventory)
        _run(ctx, inventory)
        self.assertEqual(
            [[(constants.GOAL_COUNTER_ITEM, -constants.GOAL_SIGNAL_AMOUNT)]] * 2,
            ctx.game_interface.consumed_calls,
        )

    def test_goal_counter_takes_priority_over_pickup_bits(self) -> None:
        """The goal counter is checked first and independently: even if a
        pickup counter also happens to be nonzero in the same read, the
        goal fires and returns without touching pickup bits this tick (the
        pickup bits are picked up cleanly on the next tick instead)."""
        ctx = _FakeContext()
        pickup_item, pickup_bit = counter_and_amount(0)
        inventory = _inventory(
            **{
                f"item_{constants.GOAL_COUNTER_ITEM}": constants.GOAL_SIGNAL_AMOUNT,
                f"item_{pickup_item}": pickup_bit,
            }
        )
        _run(ctx, inventory)
        self.assertTrue(ctx.finished_game)
        self.assertEqual(1, len(ctx.sent_msgs))
        self.assertEqual("StatusUpdate", ctx.sent_msgs[0][0]["cmd"])
        expected_consumed = [[(constants.GOAL_COUNTER_ITEM, -constants.GOAL_SIGNAL_AMOUNT)]]
        self.assertEqual(expected_consumed, ctx.game_interface.consumed_calls)


class TestPickupBitmaskCounters(unittest.TestCase):
    def test_goal_zero_single_pickup_bit_sends_check_only(self) -> None:
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

    def test_multiple_bits_on_one_counter_report_all_indices(self) -> None:
        # Indices 0, 2, 5 all land on the same counter (all < BITS_PER_COUNTER).
        item_id_0, bit_0 = counter_and_amount(0)
        _, bit_2 = counter_and_amount(2)
        _, bit_5 = counter_and_amount(5)
        combined = bit_0 | bit_2 | bit_5
        ctx = _FakeContext()
        inventory = _inventory(**{f"item_{item_id_0}": combined})
        _run(ctx, inventory)
        self.assertEqual(1, len(ctx.sent_msgs))
        sent = ctx.sent_msgs[0][0]
        self.assertEqual("LocationChecks", sent["cmd"])
        self.assertEqual(
            sorted(constants.LOCATION_ID_BASE + idx for idx in (0, 2, 5)),
            sorted(sent["locations"]),
        )
        self.assertEqual([[(item_id_0, -combined)]], ctx.game_interface.consumed_calls)

    def test_multi_pickup_disconnect_across_several_counters_reports_all_none_invented(self) -> None:
        """The case that motivated section P: several pickups collected
        while disconnected, landing bits across several different
        counters. Every one of them must be reported, and nothing else --
        this is exactly what the old shared-additive-counter design (and
        its location_reconciliation subset-sum fallback, removed by this
        section) could not reliably do."""
        indices = [0, 14, 20, 44, 60, 118]  # spread across all 8 counters
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
