"""Regression tests for ``client/client.py``'s magic-item goal detection.

The bug: ``_handle_magic_item_amount`` used to treat any amount *at or
above* the Credits-area sentinel (``constants.GOAL_SENTINEL_AMOUNT``, 120)
as "the player reached the credits". Real pickups ADD their index+1 to
whatever the magic-item counter already holds rather than setting it
outright, so if the client isn't attached and consuming for a while (most
realistically, a disconnect) and the player collects more than one pickup
in that window, the counter ends up holding their sum -- e.g. two Sky
Temple Keys collected while disconnected. Under the old `>=` check, that
summed value was misread as the goal instead of the "implausible value"
case the surrounding code already had a warning branch for. Fixed by
requiring an exact match against the sentinel; see PLAN.md section O.

Most of these tests use an empty ``missing_locations`` on the fake
context, so the location-reconciliation attempt (``location_reconciliation``,
whose own DP is tested exhaustively in ``test_location_reconciliation.py``)
always finds no candidates and falls straight through to the plain warning
path. ``TestClientReconciliation`` below covers the case where it
succeeds.
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
from ..client import client as client_module
from ..client.client import _handle_magic_item_amount


class _FakeGameInterface:
    def __init__(self) -> None:
        self.consumed_amounts: list[int] = []

    def consume_magic_item(self, amount: int) -> None:
        self.consumed_amounts.append(amount)


class _FakeContext:
    def __init__(self, missing_locations: set[int] | None = None) -> None:
        self.sent_msgs: list[list[dict[str, Any]]] = []
        self.finished_game = False
        self.game_interface = _FakeGameInterface()
        self.missing_locations: set[int] = missing_locations if missing_locations is not None else set()

    async def send_msgs(self, msgs: list[dict[str, Any]]) -> None:
        self.sent_msgs.append(msgs)


def _run(ctx: _FakeContext, amount: int) -> None:
    import asyncio

    asyncio.run(_handle_magic_item_amount(ctx, amount))  # type: ignore[arg-type]


class TestGoalSentinelIsAnExactMatch(unittest.TestCase):
    def test_real_pickup_index_sends_location_check_not_goal(self) -> None:
        ctx = _FakeContext()
        _run(ctx, 50)
        self.assertEqual([[{"cmd": "LocationChecks", "locations": [constants.LOCATION_ID_BASE + 49]}]], ctx.sent_msgs)
        self.assertFalse(ctx.finished_game)

    def test_last_real_pickup_index_still_sends_location_check(self) -> None:
        ctx = _FakeContext()
        last_index = client_module._GOAL_INDEX_THRESHOLD - 1
        _run(ctx, client_module._GOAL_INDEX_THRESHOLD)  # amount 119: index 118, the last real pickup
        self.assertEqual(
            [[{"cmd": "LocationChecks", "locations": [constants.LOCATION_ID_BASE + last_index]}]],
            ctx.sent_msgs,
        )
        self.assertFalse(ctx.finished_game)

    def test_exact_sentinel_declares_goal(self) -> None:
        ctx = _FakeContext()
        _run(ctx, constants.GOAL_SENTINEL_AMOUNT)
        self.assertTrue(ctx.finished_game)
        self.assertEqual(1, len(ctx.sent_msgs))
        self.assertEqual("StatusUpdate", ctx.sent_msgs[0][0]["cmd"])

    def test_goal_only_declared_once(self) -> None:
        ctx = _FakeContext()
        _run(ctx, constants.GOAL_SENTINEL_AMOUNT)
        _run(ctx, constants.GOAL_SENTINEL_AMOUNT)
        self.assertEqual(1, len(ctx.sent_msgs))

    def test_amount_past_sentinel_is_implausible_not_goal(self) -> None:
        """Regression: this is exactly the race PLAN.md section J's risk 3
        describes -- two pickups summing into a garbage amount above the
        sentinel must NOT be read as having finished the game."""
        ctx = _FakeContext()
        _run(ctx, constants.GOAL_SENTINEL_AMOUNT + 1)
        self.assertFalse(ctx.finished_game)
        self.assertEqual([], ctx.sent_msgs)
        self.assertEqual([constants.GOAL_SENTINEL_AMOUNT + 1], ctx.game_interface.consumed_amounts)

    def test_large_garbage_amount_is_implausible_not_goal(self) -> None:
        ctx = _FakeContext()
        _run(ctx, 5000)
        self.assertFalse(ctx.finished_game)
        self.assertEqual([], ctx.sent_msgs)

    def test_every_amount_is_consumed_regardless_of_branch(self) -> None:
        for amount in (50, constants.GOAL_SENTINEL_AMOUNT, constants.GOAL_SENTINEL_AMOUNT + 1):
            ctx = _FakeContext()
            _run(ctx, amount)
            self.assertEqual([amount], ctx.game_interface.consumed_amounts)


class TestClientReconciliation(unittest.TestCase):
    """Integration coverage for _handle_magic_item_amount's use of
    location_reconciliation. Note that a plain amount in 1..119 always
    matches "a single real pickup index" (the first branch) regardless of
    whether that index happens to be in missing_locations, so exercising
    reconciliation at all requires an amount past the goal sentinel (120)
    -- it only ever runs in the "implausible" bucket.

    It must build candidate indices from ctx.missing_locations
    (translating AP location ids back to 0-based pickup indices), report
    every recovered index as a LocationCheck in one message when the sum
    is uniquely explained, and fall back to the plain warning (no checks
    sent) when it isn't."""

    def test_unique_sum_of_two_missing_locations_reports_both(self) -> None:
        # Indices 60 and 90 -> values 61 and 91 -> sum 152. idx 5 (value 6)
        # is a distractor that doesn't create a second way to reach 152.
        missing = {constants.LOCATION_ID_BASE + idx for idx in (5, 60, 90)}
        ctx = _FakeContext(missing_locations=missing)
        _run(ctx, 152)
        self.assertFalse(ctx.finished_game)
        self.assertEqual(1, len(ctx.sent_msgs))
        sent = ctx.sent_msgs[0][0]
        self.assertEqual("LocationChecks", sent["cmd"])
        self.assertEqual(
            sorted([constants.LOCATION_ID_BASE + 60, constants.LOCATION_ID_BASE + 90]),
            sorted(sent["locations"]),
        )
        self.assertEqual([152], ctx.game_interface.consumed_amounts)

    def test_ambiguous_sum_reports_nothing(self) -> None:
        # idx 58,59,60,61 -> values 59,60,61,62. Target 121 is reachable
        # two different ways: {59,62} (idx 58+61) and {60,61} (idx 59+60)
        # -- deliberately ambiguous, must not guess between them.
        missing = {constants.LOCATION_ID_BASE + idx for idx in (58, 59, 60, 61)}
        ctx = _FakeContext(missing_locations=missing)
        _run(ctx, 121)
        self.assertFalse(ctx.finished_game)
        self.assertEqual([], ctx.sent_msgs)
        self.assertEqual([121], ctx.game_interface.consumed_amounts)

    def test_missing_locations_outside_this_worlds_id_range_are_ignored(self) -> None:
        # A location id far outside LOCATION_ID_BASE..+119 (e.g. another
        # game's location in a combined view) must never be translated
        # into a bogus negative/huge pickup index.
        missing = {constants.LOCATION_ID_BASE + 10, 999_999_999}
        ctx = _FakeContext(missing_locations=missing)
        _run(ctx, 999)  # nowhere near reachable from index 10 alone (value 11)
        self.assertEqual([], ctx.sent_msgs)


if __name__ == "__main__":
    unittest.main()
