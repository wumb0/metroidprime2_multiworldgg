"""Regression test for ``client/client.py``'s ``_handle_grant_items``: the
HUD "Received X from Y" message must not spam every ~0.5s tick while a large
``start_inventory`` block (every manual test uses ``ALL_ITEMS_START`` --
PLAN.md) is still being caught up across several ticks (``grant()``'s
420-byte remote-execution body budget -- PLAN.md Context fact 33/Risk L5).
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


class _FakeGameInterface:
    """Records ``grant()`` calls instead of touching Dolphin."""

    def __init__(self) -> None:
        self.grant_calls: list[tuple[list[tuple[int, int]], str | None]] = []

    def grant(
        self, deltas: list[tuple[int, int]], message: str | None = None
    ) -> list[tuple[int, int]]:
        self.grant_calls.append((list(deltas), message))
        return []


class _FakeItemNames:
    def __init__(self, names: dict[int, str]) -> None:
        self._names = names

    def lookup_in_game(self, item_id: int, game: str) -> str:
        return self._names[item_id]


_MORPH_BALL_NETWORK_ID = 1


def _bare_context(
    *, items_received: list[NetworkItem], first_non_starting: int, slot: int = 1
) -> MetroidPrime2Context:
    """Builds a ``MetroidPrime2Context`` without running
    ``CommonContext.__init__``, mirroring ``test_deathlink.py``'s
    ``_bare_context`` -- only the attributes ``_handle_grant_items`` touches
    are set by hand."""
    ctx = object.__new__(MetroidPrime2Context)
    ctx.items_received = items_received
    ctx.item_names = _FakeItemNames({_MORPH_BALL_NETWORK_ID: "Morph Ball"})
    ctx.game = "Metroid Prime 2: Echoes"
    ctx.slot = slot
    ctx.slot_data = {"first_non_starting_item_index": first_non_starting}
    ctx.player_names = {2: "OtherPlayer"}
    ctx.game_interface = _FakeGameInterface()  # type: ignore[assignment]
    return ctx


class TestGrantItemsHudMessage(unittest.TestCase):
    def test_start_inventory_catchup_does_not_announce(self) -> None:
        # Two start-inventory copies of Morph Ball still outstanding
        # (nothing past first_non_starting_item_index has arrived yet):
        # grant() must still run to catch the inventory up, but must not
        # show a "Received ... from ..." HUD message while doing so.
        items = [
            NetworkItem(item=_MORPH_BALL_NETWORK_ID, location=0, player=2)
            for _ in range(2)
        ]
        ctx = _bare_context(items_received=items, first_non_starting=2)

        asyncio.run(_handle_grant_items(ctx, {}))

        self.assertEqual(1, len(ctx.game_interface.grant_calls))  # type: ignore[attr-defined]
        _, message = ctx.game_interface.grant_calls[0]  # type: ignore[attr-defined]
        self.assertIsNone(message)

    def test_genuine_receive_past_start_inventory_announces_sender(self) -> None:
        items = [
            NetworkItem(item=_MORPH_BALL_NETWORK_ID, location=0, player=2),  # start inventory
            NetworkItem(item=_MORPH_BALL_NETWORK_ID, location=10, player=2),  # real in-game receive
        ]
        ctx = _bare_context(items_received=items, first_non_starting=1)

        asyncio.run(_handle_grant_items(ctx, {}))

        self.assertEqual(1, len(ctx.game_interface.grant_calls))  # type: ignore[attr-defined]
        _, message = ctx.game_interface.grant_calls[0]  # type: ignore[attr-defined]
        self.assertEqual("Received Morph Ball from OtherPlayer", message)

    def test_own_item_past_start_inventory_never_announces(self) -> None:
        # The game already shows its own pickup HUD message for a
        # self-found item; _handle_grant_items must not double it up.
        items = [NetworkItem(item=_MORPH_BALL_NETWORK_ID, location=10, player=1)]
        ctx = _bare_context(items_received=items, first_non_starting=0, slot=1)

        asyncio.run(_handle_grant_items(ctx, {}))

        self.assertEqual(1, len(ctx.game_interface.grant_calls))  # type: ignore[attr-defined]
        _, message = ctx.game_interface.grant_calls[0]  # type: ignore[attr-defined]
        self.assertIsNone(message)


if __name__ == "__main__":
    unittest.main()
