"""MT09 -- the live receive loop: remote items, queueing, reconnect resync."""

from __future__ import annotations

from . import harness, presets
from .harness import ManualTest, Step

_SLUG = "mt09_remote_items_reconnect"

TEST = ManualTest(
    slug=_SLUG,
    title="Remote items: arrival, queueing, and idempotent reconnect",
    priority="P0",
    proves="remote items arrive, queue, and re-sync idempotently across a client restart",
    seed=1_000_009,
    config_sha256="9eb342559f2f0e98504e13604c934c6b10e3b2a156f40ef7ebaf7c9984d0552d",
    options=presets.merge(presets.NO_RANDO_OPTIONS, presets.FAST_RETRY_OPTIONS),
    start_inventory=dict(presets.ALL_ITEMS_START),
    companions=[presets.filler_slot(1)],
    notes=[
        (
            "Driven from the **server console** (admin by virtue of being the console, so no "
            "host.yaml change is needed). Exact lines to paste:"
        ),
        f"  `/send_multiple 5 {_SLUG} Missile Expansion` -- 5 items in quick succession",
        f"  `/send {_SLUG} Super Missile` -- while a cutscene is playing",
        f"  `/send {_SLUG} Power Bomb Expansion` -- while the pause menu is open",
    ],
    steps=[
        Step(
            "While in-game, paste the first `/send_multiple` line above (5 items at once).",
            "5 HUD memos appear, correctly spaced (4s cooldown), and all 5 items are granted.",
        ),
        Step(
            "Send an item while a cutscene is playing.",
            "It queues and lands after the cutscene instead of being lost.",
        ),
        Step(
            "Open the pause menu and send an item.",
            "It queues and lands after the menu closes.",
        ),
        Step(
            "Kill the client mid-run and restart it.",
            "It re-syncs silently and idempotently: no re-granting spam, no duplicate HUD messages.",
        ),
    ],
    pass_criteria=[
        "All sent items are granted exactly once.",
        "HUD memos are throttled to the 4s cooldown and not dropped.",
        "A client restart re-syncs without duplicate grants or memos.",
    ],
    on_failure=[
        "`client/receive_items.plan_grants`",
        "`client/notification_manager.py`",
        "`client/client.py` (the Dolphin sync task / grant loop)",
    ],
)

if __name__ == "__main__":
    harness.cli(TEST)
