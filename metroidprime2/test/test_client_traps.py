"""Trap items (``client/traps.py`` and ``client/client.py``'s
``_handle_traps``): what is pending, the effect math, and the two-phase
announce-then-apply flow that keeps a trap from replaying."""

from __future__ import annotations

import asyncio
import itertools
import os
import random
import unittest
from unittest import mock

# See test_deathlink.py for why these must run before importing client.client.
os.environ.setdefault("SKIP_REQUIREMENTS_UPDATE", "1")

import worlds

if "network_data_package" not in worlds.__dict__:
    worlds.network_data_package = {"games": {}}
    worlds.network_data_package_single_game = {}

from NetUtils import NetworkItem

from ..client.client import MetroidPrime2Context, _handle_freeze_window, _handle_traps
from ..client.traps import (
    AMMO_ITEM_IDS,
    FREEZE_GAP_RANGE,
    FREEZE_LENGTH_RANGE,
    FREEZE_RETRY_DELAY,
    MIN_TRAP_SPACING,
    TrapState,
    max_health,
    pending_traps,
    plan_damage,
    trap_message,
)


class TestPlanDamage(unittest.TestCase):
    def test_removes_quarter_of_max_energy(self) -> None:
        self.assertEqual(1099.0 - 0.25 * 1499.0, plan_damage(1099.0, 1499.0))

    def test_never_kills(self) -> None:
        self.assertEqual(1.0, plan_damage(50.0, 1499.0))

    def test_never_raises_health(self) -> None:
        self.assertEqual(1.0, plan_damage(1.0, 1499.0))
        self.assertEqual(0.5, plan_damage(0.5, 1499.0))

    def test_max_health_scales_with_tanks_and_energy_per_tank(self) -> None:
        self.assertEqual(99.0, max_health(100, 0))
        self.assertEqual(1499.0, max_health(100, 14))
        self.assertEqual(3 * 50 - 1, max_health(50, 2))


class TestPendingTraps(unittest.TestCase):
    RECEIVED = ["Morph Ball", "Damage Trap", "Missile Expansion", "Freeze Trap", "Ammo Depletion Trap"]

    def test_all_pending_in_order(self) -> None:
        self.assertEqual(
            [(1, "Damage Trap"), (3, "Freeze Trap"), (4, "Ammo Depletion Trap")],
            pending_traps(self.RECEIVED, 0, 0),
        )

    def test_processed_index_skips_handled_traps(self) -> None:
        self.assertEqual([(3, "Freeze Trap"), (4, "Ammo Depletion Trap")], pending_traps(self.RECEIVED, 0, 2))

    def test_start_inventory_never_triggers(self) -> None:
        self.assertEqual([(4, "Ammo Depletion Trap")], pending_traps(self.RECEIVED, 4, 0))

    def test_nothing_pending_when_caught_up(self) -> None:
        self.assertEqual([], pending_traps(self.RECEIVED, 0, 5))


class TestTrapMessage(unittest.TestCase):
    def test_messages_fit_the_hud(self) -> None:
        for name in ("Damage Trap", "Ammo Depletion Trap", "Freeze Trap"):
            self.assertLessEqual(len(trap_message(name, 30)), 90)

    def test_freeze_message_names_window(self) -> None:
        self.assertIn("2 minutes", trap_message("Freeze Trap", 120))
        self.assertIn("1 minute", trap_message("Freeze Trap", 60))
        self.assertIn("90 seconds", trap_message("Freeze Trap", 90))


class _FakeGameInterface:
    def __init__(self, *, health: float | None = 500.0) -> None:
        self.health = health
        self.pending_op = False
        self.messages: list[str] = []
        self.amount_writes: list[tuple[int, int]] = []
        self.freeze_calls: list[float] = []
        self.frozen_timeout: float | None = 0.0
        self.freeze_takes = True

    def freeze_player(self, seconds: float) -> None:
        self.freeze_calls.append(seconds)
        self.pending_op = True
        if self.freeze_takes:
            self.frozen_timeout = seconds

    def read_frozen_timeout(self) -> float | None:
        return self.frozen_timeout

    def has_pending_op(self) -> bool:
        return self.pending_op

    def send_hud_message(self, message: str) -> bool:
        if self.pending_op:
            return False
        self.messages.append(message)
        self.pending_op = True  # the game consumes it before the next free tick
        return True

    def get_current_health(self) -> float | None:
        return self.health

    def set_current_health(self, value: float) -> None:
        self.health = value

    def set_item_amount(self, item_id: int, amount: int) -> None:
        self.amount_writes.append((item_id, amount))


class _FakeItemNames:
    def __init__(self, names: dict[int, str]) -> None:
        self._names = names

    def lookup_in_game(self, item_id: int, game: str) -> str:
        return self._names[item_id]


_NAMES = {1: "Morph Ball", 2: "Damage Trap", 3: "Ammo Depletion Trap", 4: "Freeze Trap"}
_INVENTORY = {42: (4, 4)}  # four Energy Tanks


def _context(item_ids: list[int], *, processed_index: int | None = 0, health: float | None = 500.0):
    ctx = object.__new__(MetroidPrime2Context)
    ctx.items_received = [NetworkItem(item_id, 100 + index, 1) for index, item_id in enumerate(item_ids)]
    ctx.item_names = _FakeItemNames(_NAMES)
    ctx.game = "Metroid Prime 2: Echoes"
    ctx.team = 0
    ctx.slot = 1
    ctx.slot_data = {"first_non_starting_item_index": 0, "energy_per_tank": 100}
    ctx.game_interface = _FakeGameInterface(health=health)  # type: ignore[assignment]
    ctx.trap_state = TrapState(processed_index=processed_index)
    ctx.trap_rng = random.Random(1234)
    ctx.sent: list[dict] = []  # type: ignore[misc]

    async def send_msgs(msgs):
        ctx.sent.extend(msgs)

    ctx.send_msgs = send_msgs  # type: ignore[method-assign]
    return ctx


def _tick(ctx) -> None:
    asyncio.run(_handle_traps(ctx, _INVENTORY))


class TestHandleTraps(unittest.TestCase):
    def test_nothing_before_datastorage_reply(self) -> None:
        ctx = _context([2], processed_index=None)
        _tick(ctx)
        self.assertEqual([], ctx.game_interface.messages)

    def test_damage_trap_announces_then_applies_then_records(self) -> None:
        ctx = _context([1, 2])
        _tick(ctx)  # phase 1: HUD message
        self.assertEqual(1, len(ctx.game_interface.messages))
        self.assertEqual(500.0, ctx.game_interface.health)
        self.assertEqual(0, len(ctx.sent))

        _tick(ctx)  # message still pending: nothing yet
        self.assertEqual(500.0, ctx.game_interface.health)

        ctx.game_interface.pending_op = False  # game consumed the message
        _tick(ctx)  # phase 2: effect
        # 4 tanks at 100 each -> max 499; 25% of that is 124.75
        self.assertEqual(500.0 - 0.25 * 499.0, ctx.game_interface.health)
        self.assertEqual(2, ctx.trap_state.processed_index)
        self.assertEqual("max", ctx.sent[0]["operations"][0]["operation"])
        self.assertEqual(2, ctx.sent[0]["operations"][0]["value"])

    def test_ammo_trap_zeroes_amounts_only(self) -> None:
        ctx = _context([3])
        _tick(ctx)
        ctx.game_interface.pending_op = False
        _tick(ctx)
        self.assertEqual([(item_id, 0) for item_id in AMMO_ITEM_IDS], ctx.game_interface.amount_writes)

    def test_handled_trap_does_not_replay(self) -> None:
        ctx = _context([2], processed_index=1)
        _tick(ctx)
        self.assertEqual([], ctx.game_interface.messages)

    def test_start_inventory_trap_ignored(self) -> None:
        ctx = _context([2])
        ctx.slot_data["first_non_starting_item_index"] = 1
        _tick(ctx)
        self.assertEqual([], ctx.game_interface.messages)

    def test_traps_are_spaced_out(self) -> None:
        ctx = _context([2, 2])
        _tick(ctx)
        ctx.game_interface.pending_op = False
        _tick(ctx)  # first applied
        _tick(ctx)  # second held back by the spacing
        self.assertEqual(1, len(ctx.game_interface.messages))
        ctx.trap_state.last_applied -= MIN_TRAP_SPACING
        _tick(ctx)
        self.assertEqual(2, len(ctx.game_interface.messages))

    def test_damage_waits_while_health_unreadable(self) -> None:
        ctx = _context([2], health=None)
        _tick(ctx)
        ctx.game_interface.pending_op = False
        _tick(ctx)
        self.assertEqual(0, ctx.trap_state.processed_index)
        self.assertEqual([], ctx.sent)
        ctx.game_interface.health = 500.0
        _tick(ctx)
        self.assertEqual(1, ctx.trap_state.processed_index)


class _Clock:
    def __init__(self) -> None:
        self.now = 1_000_000.0

    def __call__(self) -> float:
        return self.now


def _freeze_tick(ctx) -> None:
    asyncio.run(_handle_freeze_window(ctx))


class TestFreezeTrap(unittest.TestCase):
    def setUp(self) -> None:
        self.clock = _Clock()
        patcher = mock.patch("time.time", self.clock)
        patcher.start()
        self.addCleanup(patcher.stop)

    def _received(self, item_ids: list[int], window: int = 90):
        ctx = _context(item_ids)
        ctx.slot_data["freeze_trap_duration"] = window
        return ctx

    def _receive_freeze(self, ctx) -> None:
        _tick(ctx)  # HUD message
        ctx.game_interface.pending_op = False
        _tick(ctx)  # effect: opens the window

    def _advance(self, ctx, seconds: float, step: float = 0.5) -> None:
        """Runs the freeze handler every ``step`` seconds, with the fake game
        consuming any armed body and thawing the player in between."""
        game = ctx.game_interface
        for _ in range(round(seconds / step)):
            self.clock.now += step
            game.pending_op = False
            if game.frozen_timeout:
                game.frozen_timeout = max(0.0, game.frozen_timeout - step)
            _freeze_tick(ctx)

    def test_receiving_opens_a_window_and_records_the_trap(self) -> None:
        ctx = self._received([4])
        start = self.clock.now
        self._receive_freeze(ctx)
        self.assertEqual(start + 90, ctx.trap_state.freeze_window_end)
        low, high = FREEZE_GAP_RANGE
        self.assertTrue(start + low <= ctx.trap_state.next_freeze_at <= start + high)
        self.assertEqual(1, ctx.trap_state.processed_index)
        self.assertEqual([], ctx.game_interface.freeze_calls)  # not frozen right away
        self.assertEqual(1, ctx.sent[0]["operations"][0]["value"])

    def test_freezes_happen_at_random_moments_within_the_window(self) -> None:
        ctx = self._received([4])
        self._receive_freeze(ctx)
        window_end = ctx.trap_state.freeze_window_end

        freeze_times: list[float] = []
        original = ctx.game_interface.freeze_player

        def record(seconds: float) -> None:
            freeze_times.append(self.clock.now)
            original(seconds)

        ctx.game_interface.freeze_player = record  # type: ignore[method-assign]
        self._advance(ctx, 300)

        self.assertGreater(len(freeze_times), 2)
        self.assertTrue(all(time <= window_end + 1 for time in freeze_times))
        gaps = [later - earlier for earlier, later in itertools.pairwise(freeze_times)]
        self.assertTrue(
            all(FREEZE_GAP_RANGE[0] <= gap <= FREEZE_GAP_RANGE[1] + FREEZE_LENGTH_RANGE[1] + 1 for gap in gaps)
        )
        self.assertGreater(len(set(gaps)), 1, "gaps should vary")

    def test_each_freeze_has_a_random_length_in_range(self) -> None:
        ctx = self._received([4], window=600)
        self._receive_freeze(ctx)
        self._advance(ctx, 600)
        lengths = ctx.game_interface.freeze_calls
        self.assertGreater(len(lengths), 5)
        self.assertTrue(all(FREEZE_LENGTH_RANGE[0] <= length <= FREEZE_LENGTH_RANGE[1] for length in lengths))
        self.assertGreater(len(set(lengths)), 1)

    def test_no_freezes_after_the_window_closes(self) -> None:
        ctx = self._received([4], window=30)
        self._receive_freeze(ctx)
        self._advance(ctx, 40)
        calls = len(ctx.game_interface.freeze_calls)
        self._advance(ctx, 120)
        self.assertEqual(calls, len(ctx.game_interface.freeze_calls))

    def test_refused_freeze_is_retried_soon(self) -> None:
        ctx = self._received([4])
        self._receive_freeze(ctx)
        ctx.game_interface.freeze_takes = False
        self.clock.now = ctx.trap_state.next_freeze_at
        _freeze_tick(ctx)  # arms
        self.assertEqual(1, len(ctx.game_interface.freeze_calls))
        ctx.game_interface.pending_op = False
        _freeze_tick(ctx)  # timeout still 0: schedule a quick retry
        self.assertEqual(self.clock.now + FREEZE_RETRY_DELAY, ctx.trap_state.next_freeze_at)

        ctx.game_interface.freeze_takes = True
        self.clock.now = ctx.trap_state.next_freeze_at
        _freeze_tick(ctx)
        self.assertEqual(2, len(ctx.game_interface.freeze_calls))

    def test_second_freeze_trap_extends_the_window(self) -> None:
        ctx = self._received([4, 4])
        start = self.clock.now
        self._receive_freeze(ctx)
        self.clock.now += MIN_TRAP_SPACING
        _tick(ctx)
        ctx.game_interface.pending_op = False
        _tick(ctx)
        self.assertEqual(start + 180, ctx.trap_state.freeze_window_end)
        self.assertEqual(2, ctx.trap_state.processed_index)

    def test_waits_while_dead_or_op_pending(self) -> None:
        ctx = self._received([4])
        self._receive_freeze(ctx)
        self.clock.now = ctx.trap_state.next_freeze_at
        ctx.game_interface.health = 0.0
        _freeze_tick(ctx)
        ctx.game_interface.health = 500.0
        ctx.game_interface.pending_op = True
        _freeze_tick(ctx)
        self.assertEqual([], ctx.game_interface.freeze_calls)
        ctx.game_interface.pending_op = False
        _freeze_tick(ctx)
        self.assertEqual(1, len(ctx.game_interface.freeze_calls))

    def test_does_not_refreeze_a_frozen_player(self) -> None:
        ctx = self._received([4])
        self._receive_freeze(ctx)
        self.clock.now = ctx.trap_state.next_freeze_at
        ctx.game_interface.frozen_timeout = 3.0
        _freeze_tick(ctx)
        self.assertEqual([], ctx.game_interface.freeze_calls)
        self.assertGreater(ctx.trap_state.next_freeze_at, self.clock.now)


if __name__ == "__main__":
    unittest.main()
