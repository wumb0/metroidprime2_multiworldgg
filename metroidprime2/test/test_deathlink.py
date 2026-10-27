"""Tests for ``client/death_link.py``'s ``death_link_check`` -- the pure
DeathLink polling decision (health -> should-send/pending-reset-flag),
exercised without any Dolphin/CommonContext dependency, mirroring
``test_client_receive.py``'s approach to ``receive_items.py``.

Also covers ``MetroidPrime2Context.on_deathlink`` itself (the incoming-
DeathLink handler in ``client/client.py``), which is what actually sets
the pending-reset flag that ``death_link_check`` consumes.
"""

from __future__ import annotations

import os
import unittest
from typing import Any

# client.client imports CommonClient, which (a) runs ModuleUpdate.update()
# (a pip pass over every world's requirements.txt) at import time unless
# this env var is set -- and it must be set before ModuleUpdate's own first
# import anywhere in the process, since it reads the var into a module-level
# flag exactly once; a later `ModuleUpdate.update_ran = True` does not
# reliably stick (other worlds' requirements.txt registration ANDs it back
# down) -- and (b) does a top-level `from worlds import network_data_package,
# ...`, and `worlds.network_data_package` is a lazy attribute that, the first
# time anything reads it, imports every world package to build it. That
# includes worlds/dk64, which -- unconditionally, on its own, nothing to do
# with ModuleUpdate -- shells out to `pip install -r requirements.txt`
# (cloning a git dependency) at import time in this environment because
# `pkg_resources` isn't installed here. Stubbing the attribute before the
# CommonClient import short-circuits that lazy load so this narrow unit test
# doesn't pay for (or depend on the network for) importing every world.
# (Verified: without both of these, importing client.client here actually
# shelled out to pip and cloned from GitHub on every test run.)
os.environ.setdefault("SKIP_REQUIREMENTS_UPDATE", "1")

import worlds

if "network_data_package" not in worlds.__dict__:
    worlds.network_data_package = {"games": {}}
    worlds.network_data_package_single_game = {}

from ..client.client import MetroidPrime2Context
from ..client.death_link import death_link_check, death_message
from ..tracker_data import area_region_name, area_room_name


class TestDeathLinkCheck(unittest.TestCase):
    def test_disconnected_never_sends_and_keeps_pending_flag(self) -> None:
        self.assertEqual((False, False), death_link_check(None, False))
        self.assertEqual((False, True), death_link_check(None, True))

    def test_health_at_or_below_zero_sends_once(self) -> None:
        self.assertEqual((True, True), death_link_check(0.0, False))
        self.assertEqual((True, True), death_link_check(-5.0, False))

    def test_health_still_nonpositive_does_not_resend(self) -> None:
        self.assertEqual((False, True), death_link_check(0.0, True))
        self.assertEqual((False, True), death_link_check(-5.0, True))

    def test_positive_health_clears_pending_flag_without_sending(self) -> None:
        self.assertEqual((False, False), death_link_check(99.0, True))

    def test_positive_health_without_pending_flag_is_a_noop(self) -> None:
        self.assertEqual((False, False), death_link_check(99.0, False))

    def test_cleared_alive_flag_sends_even_with_positive_health(self) -> None:
        self.assertEqual((True, True), death_link_check(50.0, False, alive=False))

    def test_cleared_alive_flag_does_not_resend_while_pending(self) -> None:
        self.assertEqual((False, True), death_link_check(50.0, True, alive=False))

    def test_pending_flag_holds_until_alive_flag_returns(self) -> None:
        self.assertEqual((False, True), death_link_check(99.0, True, alive=False))
        self.assertEqual((False, False), death_link_check(99.0, True, alive=True))

    def test_unknown_alive_flag_falls_back_to_health(self) -> None:
        self.assertEqual((False, False), death_link_check(99.0, False, alive=None))
        self.assertEqual((True, True), death_link_check(0.0, False, alive=None))


class TestDeathMessage(unittest.TestCase):
    def test_names_room_and_region_when_known(self) -> None:
        self.assertEqual(
            "Sam died in Sanctuary Fortress's Main Research",
            death_message("Sam", "Main Research", "Sanctuary Fortress"),
        )

    def test_names_whichever_is_known(self) -> None:
        self.assertEqual("Sam died in Agon Wastes", death_message("Sam", None, "Agon Wastes"))
        self.assertEqual("Sam died in Main Research", death_message("Sam", "Main Research", None))

    def test_falls_back_without_location(self) -> None:
        self.assertEqual("Sam ran out of energy.", death_message("Sam", None, None))

    def test_room_lookup_uses_live_mlvl_and_area_index(self) -> None:
        self.assertEqual("Main Research", area_room_name(0x1BAA96C2, 11))
        self.assertIsNone(area_room_name(None, 11))
        self.assertIsNone(area_room_name(0x1BAA96C2, 9999))
        self.assertIsNone(area_room_name(0xDEADBEEF, 0))

    def test_region_lookup_uses_live_mlvl_and_area_index(self) -> None:
        self.assertEqual("Sanctuary Fortress", area_region_name(0x1BAA96C2, 0))
        self.assertEqual("Ing Hive", area_region_name(0x1BAA96C2, 12))

    def test_region_lookup_unknown_is_none(self) -> None:
        self.assertIsNone(area_region_name(None, 0))
        self.assertIsNone(area_region_name(0x1BAA96C2, None))
        self.assertIsNone(area_region_name(0x1BAA96C2, 9999))
        self.assertIsNone(area_region_name(0xDEADBEEF, 0))


class _FakeGameInterface:
    """Stands in for ``EchoesInterface``: records the health/alive writes
    ``on_deathlink`` performs without touching Dolphin. ``health=None``
    simulates a null CPlayerState (writes fail)."""

    def __init__(self, health: float | None = 99.0) -> None:
        self.health = health
        self.last_health_written: float | None = None
        self.last_alive_written: bool | None = None

    def get_current_health(self) -> float | None:
        return self.health

    def set_current_health(self, new_health_amount: float) -> bool:
        if self.health is None:
            return False
        self.last_health_written = new_health_amount
        self.health = new_health_amount
        return True

    def set_alive(self, alive: bool) -> bool:
        if self.health is None:
            return False
        self.last_alive_written = alive
        return True


def _bare_context(health: float | None = 99.0) -> MetroidPrime2Context:
    """Builds a ``MetroidPrime2Context`` instance without running
    ``CommonContext.__init__`` (which schedules an asyncio task and needs a
    running event loop) -- only the attributes ``on_deathlink`` and its
    ``super().on_deathlink()`` call actually touch are set by hand."""
    ctx = object.__new__(MetroidPrime2Context)
    ctx.last_death_link = 0.0
    ctx.game_interface = _FakeGameInterface(health)  # type: ignore[assignment]
    ctx.is_pending_death_link_reset = False
    ctx.pending_incoming_death = False
    ctx.pending_incoming_death_since = 0.0
    return ctx


class TestOnDeathlink(unittest.TestCase):
    """Regression test for the ping-pong bug: an incoming DeathLink must
    mark ``is_pending_death_link_reset`` so the next poll tick's
    ``death_link_check`` call treats the (already externally-induced)
    non-positive health as already reported, instead of re-sending it as a
    fresh outgoing DeathLink."""

    def test_incoming_deathlink_kills_player_and_arms_pending_reset(self) -> None:
        ctx = _bare_context()
        data: dict[str, Any] = {"time": 123.0, "cause": "ran out of energy", "source": "OtherPlayer"}

        ctx.on_deathlink(data)

        self.assertEqual(-1.0, ctx.game_interface.last_health_written)  # type: ignore[attr-defined]
        self.assertEqual(False, ctx.game_interface.last_alive_written)  # type: ignore[attr-defined]
        self.assertTrue(ctx.is_pending_death_link_reset)

        # The follow-up poll tick sees health <= 0 with the flag already
        # armed, so it must NOT decide to send a new DeathLink out.
        should_send, new_pending = death_link_check(
            ctx.game_interface.last_health_written,  # type: ignore[attr-defined]
            ctx.is_pending_death_link_reset,
        )
        self.assertEqual((False, True), (should_send, new_pending))

    def test_null_player_state_queues_death_until_valid(self) -> None:
        ctx = _bare_context(health=None)
        ctx.on_deathlink({"time": 1.0, "cause": "x", "source": "Other"})

        self.assertTrue(ctx.pending_incoming_death)
        self.assertFalse(ctx.is_pending_death_link_reset)
        self.assertIsNone(ctx.game_interface.last_alive_written)  # type: ignore[attr-defined]

        # Still null on a later tick: stays queued.
        ctx.apply_pending_death()
        self.assertTrue(ctx.pending_incoming_death)

        # Player state becomes valid: the queued death lands and arms the debounce.
        ctx.game_interface.health = 99.0  # type: ignore[attr-defined]
        ctx.apply_pending_death()
        self.assertFalse(ctx.pending_incoming_death)
        self.assertEqual(-1.0, ctx.game_interface.last_health_written)  # type: ignore[attr-defined]
        self.assertEqual(False, ctx.game_interface.last_alive_written)  # type: ignore[attr-defined]
        self.assertTrue(ctx.is_pending_death_link_reset)

    def test_queued_death_expires_after_timeout(self) -> None:
        ctx = _bare_context(health=None)
        ctx.on_deathlink({"time": 1.0, "cause": "x", "source": "Other"})
        self.assertTrue(ctx.pending_incoming_death)

        ctx.pending_incoming_death_since -= 31.0
        ctx.game_interface.health = 99.0  # type: ignore[attr-defined]
        ctx.apply_pending_death()

        self.assertFalse(ctx.pending_incoming_death)
        self.assertIsNone(ctx.game_interface.last_alive_written)  # type: ignore[attr-defined]
        self.assertFalse(ctx.is_pending_death_link_reset)

    def test_already_dead_player_drops_queued_death(self) -> None:
        ctx = _bare_context(health=0.0)
        ctx.on_deathlink({"time": 1.0, "cause": "x", "source": "Other"})

        self.assertFalse(ctx.pending_incoming_death)
        self.assertIsNone(ctx.game_interface.last_alive_written)  # type: ignore[attr-defined]


if __name__ == "__main__":
    unittest.main()
