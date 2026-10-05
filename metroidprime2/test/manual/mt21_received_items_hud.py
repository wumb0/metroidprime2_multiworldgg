"""MT21 -- the grouped "Received ... from ..." HUD memo, incl. server-cheated items."""

from __future__ import annotations

from . import harness, presets
from .harness import ManualTest, Step

_SLUG = "mt21_received_items_hud"

TEST = ManualTest(
    slug=_SLUG,
    title="Received-items HUD memo: grouping, splitting, and server-cheated items",
    priority="P1",
    proves=(
        "client._announce_received_items groups everything received from one sender into a "
        "single 'Received ... from ...' HUD memo, splits an oversized list across several "
        "memos without truncating, and announces items cheated in by the server "
        "(`/send`, `/send_multiple`, `!getitem`) as from Archipelago"
    ),
    seed=1_000_021,
    config_sha256="f63f8c5bb9b342657e872123d1a7bf39b1f3246b8ecd8201f067de65749d3814",
    options=presets.merge(presets.NO_RANDO_OPTIONS, presets.MAP_OPTIONS, presets.FAST_RETRY_OPTIONS),
    start_inventory=dict(presets.ALL_ITEMS_START),
    setup=[
        "Host the generated multiworld and keep the server console open; most steps paste into it.",
        "`!getitem` (step 5) needs item cheating enabled on the server, which it is unless "
        "`disable_item_cheat` is set in host.yaml. It is typed into the client's own console, not the server's.",
    ],
    notes=[
        "Every item here is already held via `start_inventory`, so the HUD memo is the only visible effect "
        "except for Missile / Power Bomb capacity, which still grows (watch the missile counter).",
        "Server-cheated items arrive as sender `Archipelago` (slot 0). `!getitem` used to be skipped "
        "entirely because the server stamps your own slot as its sender, which the client mistook for "
        "a self-found pickup; this test is the regression check for that.",
        "Grouping is per sender and per memo, within a ~1s window. A burst pasted into the server console "
        "may legitimately land as two memos if it straddles that window -- what matters is that every "
        "item is named exactly once with the right count.",
        "Per-player attribution (two different real senders giving separate memos) is covered by "
        "`test/test_client_grant_message.py`; it needs a second player who actually holds items for you.",
    ],
    steps=[
        Step(
            "Start New Game and connect the client. Wait for the first room to settle.",
            "No 'Received ...' memo appears for the start inventory.",
            why="Start-inventory catch-up must never be announced.",
        ),
        Step(
            f"Server console: `/send {_SLUG} Missile Expansion`",
            "One memo: `Received Missile Expansion from Archipelago`. Missile capacity rises by 5.",
        ),
        Step(
            f"Server console: `/send_multiple 3 {_SLUG} Missile Expansion`",
            "One memo: `Received 15 Missiles from Archipelago` (not three memos). Capacity rises by 15.",
            why="Same-sender copies merge, and ammo expansions are shown as the total ammo.",
        ),
        Step(
            f"Paste these three lines into the server console in one go:\n"
            f"  `/send_multiple 2 {_SLUG} Missile Expansion`\n"
            f"  `/send_multiple 2 {_SLUG} Power Bomb Expansion`\n"
            f"  `/send {_SLUG} Boost Ball`",
            "A single memo listing all three groups, e.g. `Received 10 Missiles, 2 Power Bombs, Boost Ball "
            "from Archipelago` (a split across two memos is acceptable; a missing or miscounted entry is not).",
        ),
        Step(
            "In the client's console type `!getitem Missile Expansion`.",
            "A memo `Received Missile Expansion from Archipelago` appears and missile capacity rises by 5.",
            why="Regression: !getitem used to grant the item with no HUD memo at all.",
        ),
        Step(
            f"Server console, ten distinct items back to back: `/send {_SLUG} Dark Beam`, `... Light Beam`, "
            "`... Annihilator Beam`, `... Super Missile`, `... Darkburst`, `... Sunburst`, `... Sonic Boom`, "
            "`... Boost Ball`, `... Spider Ball`, `... Space Jump Boots`.",
            "The list is split across two or more memos. Every memo ends in `from Archipelago`, none is "
            "cut off mid-word, and all ten names appear somewhere across them, in order.",
            why="A HUD message holds ~97 characters; the rest must queue, not truncate.",
        ),
        Step(
            "Wait for the memos to finish, then kill the client and restart it.",
            "It re-syncs silently: no 'Received ...' memos for anything already seen.",
        ),
    ],
    pass_criteria=[
        "Every item sent from the server console or via `!getitem` produces a memo from Archipelago.",
        "Same-sender items are grouped into one memo; ammo expansions show total ammo.",
        "An oversized list splits into several well-formed memos with nothing dropped.",
        "The start inventory and a client restart never produce memos.",
        "No client traceback.",
    ],
    on_failure=[
        "`client/client.py::_announce_received_items`",
        "`client/notification_manager.py::queue_received_items`",
        "`test/test_client_grant_message.py`",
    ],
)

if __name__ == "__main__":
    harness.cli(TEST)
