"""Regression tests for ``client/client.py``'s ``_handle_grant_items`` HUD
"Received X from Y" messages:

* no announcement (and no spam) while a large ``start_inventory`` block
  (every manual test uses ``ALL_ITEMS_START`` -- PLAN.md) is still being
  caught up across several ticks (``grant()``'s 420-byte remote-execution
  body budget -- PLAN.md Context fact 33/Risk L5);
* several copies of an item from one sender are grouped into one message.
"""

from __future__ import annotations

import asyncio
import os
import unittest

# See test_deathlink.py for why these two lines must run before importing
# client.client.
os.environ.setdefault("SKIP_REQUIREMENTS_UPDATE", "1")

import worlds

if "network_data_package" not in worlds.__dict__:
    worlds.network_data_package = {"games": {}}
    worlds.network_data_package_single_game = {}

from NetUtils import NetworkItem

from ..client.client import MetroidPrime2Context, _handle_grant_items
from ..client.notification_manager import HUD_MAX_CHARS, NotificationManager


class _FakeGameInterface:
    """Records ``grant()`` calls instead of touching Dolphin."""

    def __init__(self) -> None:
        self.grant_calls: list[list[tuple[int, int]]] = []

    def grant(self, deltas: list[tuple[int, int]]) -> list[tuple[int, int]]:
        self.grant_calls.append(list(deltas))
        return []


class _FakeItemNames:
    def __init__(self, names: dict[int, str]) -> None:
        self._names = names

    def lookup_in_game(self, item_id: int, game: str) -> str:
        return self._names[item_id]


_MORPH_BALL_NETWORK_ID = 1
_MISSILE_EXPANSION_NETWORK_ID = 2
_ENERGY_TANK_NETWORK_ID = 3


def _bare_context(
    *, items_received: list[NetworkItem], first_non_starting: int, slot: int = 1
) -> MetroidPrime2Context:
    """Builds a ``MetroidPrime2Context`` without running
    ``CommonContext.__init__``, mirroring ``test_deathlink.py``'s
    ``_bare_context`` -- only the attributes ``_handle_grant_items`` touches
    are set by hand."""
    ctx = object.__new__(MetroidPrime2Context)
    ctx.items_received = items_received
    ctx.item_names = _FakeItemNames(
        {
            _MORPH_BALL_NETWORK_ID: "Morph Ball",
            _MISSILE_EXPANSION_NETWORK_ID: "Missile Expansion",
            _ENERGY_TANK_NETWORK_ID: "Energy Tank",
        }
    )
    ctx.game = "Metroid Prime 2: Echoes"
    ctx.slot = slot
    ctx.slot_data = {"first_non_starting_item_index": first_non_starting}
    ctx.player_names = {2: "OtherPlayer", 3: "ThirdPlayer"}
    ctx.last_announced_index = None
    ctx.game_interface = _FakeGameInterface()  # type: ignore[assignment]
    ctx.notification_manager = NotificationManager(4.0, lambda _message: True)
    return ctx


def _queued(ctx: MetroidPrime2Context) -> list[str]:
    return [str(entry) for entry in ctx.notification_manager.notification_queue]


class TestGrantItemsHudMessage(unittest.TestCase):
    def test_start_inventory_catchup_does_not_announce(self) -> None:
        # Two start-inventory copies of Morph Ball still outstanding
        # (nothing past first_non_starting_item_index has arrived yet):
        # grant() must still run to catch the inventory up, but must not
        # queue a "Received ... from ..." HUD message while doing so.
        items = [
            NetworkItem(item=_MORPH_BALL_NETWORK_ID, location=0, player=2)
            for _ in range(2)
        ]
        ctx = _bare_context(items_received=items, first_non_starting=2)

        asyncio.run(_handle_grant_items(ctx, {}))
        asyncio.run(_handle_grant_items(ctx, {}))

        self.assertEqual(2, len(ctx.game_interface.grant_calls))  # type: ignore[attr-defined]
        self.assertEqual([], _queued(ctx))

    def test_genuine_receive_past_start_inventory_announces_sender(self) -> None:
        items = [
            NetworkItem(item=_MORPH_BALL_NETWORK_ID, location=0, player=2),  # start inventory
            NetworkItem(item=_MORPH_BALL_NETWORK_ID, location=10, player=2),  # real in-game receive
        ]
        ctx = _bare_context(items_received=items, first_non_starting=1)

        asyncio.run(_handle_grant_items(ctx, {}))

        self.assertEqual(1, len(ctx.game_interface.grant_calls))  # type: ignore[attr-defined]
        self.assertEqual(["Received Morph Ball from OtherPlayer"], _queued(ctx))

    def test_own_item_past_start_inventory_never_announces(self) -> None:
        # The game already shows its own pickup HUD message for a
        # self-found item; _handle_grant_items must not double it up.
        items = [NetworkItem(item=_MORPH_BALL_NETWORK_ID, location=10, player=1)]
        ctx = _bare_context(items_received=items, first_non_starting=0, slot=1)

        asyncio.run(_handle_grant_items(ctx, {}))

        self.assertEqual(1, len(ctx.game_interface.grant_calls))  # type: ignore[attr-defined]
        self.assertEqual([], _queued(ctx))

    def test_same_item_same_sender_grouped(self) -> None:
        items = [
            NetworkItem(item=_MISSILE_EXPANSION_NETWORK_ID, location=10 + i, player=2)
            for i in range(3)
        ]
        items.append(NetworkItem(item=_ENERGY_TANK_NETWORK_ID, location=20, player=2))
        items.append(NetworkItem(item=_ENERGY_TANK_NETWORK_ID, location=21, player=2))
        items.append(NetworkItem(item=_MISSILE_EXPANSION_NETWORK_ID, location=30, player=3))
        ctx = _bare_context(items_received=items, first_non_starting=0)

        asyncio.run(_handle_grant_items(ctx, {}))

        self.assertEqual(
            [
                "Received 15 Missiles, Energy Tank x2 from OtherPlayer",
                "Received Missile Expansion from ThirdPlayer",
            ],
            _queued(ctx),
        )

    def test_large_backlog_is_listed_not_collapsed(self) -> None:
        # e.g. reconnecting after a long break: every item is still named,
        # split across as many HUD-sized messages as needed.
        names = {100 + i: f"Test Item Number {i}" for i in range(12)}
        items = [NetworkItem(item=item_id, location=item_id, player=2) for item_id in names]
        ctx = _bare_context(items_received=items, first_non_starting=0)
        ctx.item_names = _FakeItemNames(names)

        asyncio.run(_handle_grant_items(ctx, {}))

        queued = _queued(ctx)
        self.assertGreater(len(queued), 1)
        for message in queued:
            self.assertLessEqual(len(message), HUD_MAX_CHARS)
            self.assertTrue(message.endswith(" from OtherPlayer"))
        joined = " ".join(queued)
        for name in names.values():
            self.assertIn(name, joined)

    def test_later_copies_merge_into_still_queued_message(self) -> None:
        items = [NetworkItem(item=_MISSILE_EXPANSION_NETWORK_ID, location=10, player=2)]
        ctx = _bare_context(items_received=items, first_non_starting=0)
        asyncio.run(_handle_grant_items(ctx, {}))

        items.append(NetworkItem(item=_MISSILE_EXPANSION_NETWORK_ID, location=11, player=2))
        asyncio.run(_handle_grant_items(ctx, {}))

        self.assertEqual(["Received 10 Missiles from OtherPlayer"], _queued(ctx))

    def test_already_announced_items_not_reannounced(self) -> None:
        # grant() leftovers keep deltas nonempty across ticks; the same
        # receipt must not be counted again on the next tick.
        items = [NetworkItem(item=_MORPH_BALL_NETWORK_ID, location=10, player=2)]
        ctx = _bare_context(items_received=items, first_non_starting=0)

        asyncio.run(_handle_grant_items(ctx, {}))
        ctx.notification_manager.notification_queue.clear()
        asyncio.run(_handle_grant_items(ctx, {}))

        self.assertEqual([], _queued(ctx))


if __name__ == "__main__":
    unittest.main()


class TestHandleNotificationsReturn(unittest.TestCase):
    def test_returns_true_only_when_a_message_was_sent(self) -> None:
        sent: list[str] = []
        manager = NotificationManager(4.0, lambda message: sent.append(message) or True)
        self.assertFalse(manager.handle_notifications())

        manager.queue_notification("hello")
        self.assertTrue(manager.handle_notifications())
        self.assertEqual(["hello"], sent)

        # Within the cooldown: nothing sent, nothing reported.
        manager.queue_notification("again")
        self.assertFalse(manager.handle_notifications())

    def test_returns_false_when_send_is_refused(self) -> None:
        manager = NotificationManager(4.0, lambda _message: False)
        manager.queue_notification("hello")
        self.assertFalse(manager.handle_notifications())
        self.assertEqual(["hello"], list(manager.notification_queue))
