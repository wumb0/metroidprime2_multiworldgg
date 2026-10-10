"""MT22 -- trap items: Damage, Ammo Depletion and Freeze."""

from __future__ import annotations

from . import harness, presets
from .harness import ManualTest, Step

_SLUG = "mt22_traps"

# The Unlimited pickups stop ammo from being consumed or displayed as a count,
# which would hide the Ammo Depletion Trap's effect.
_START_INVENTORY = {
    name: count
    for name, count in presets.ALL_ITEMS_START.items()
    if name not in ("Unlimited Missiles", "Unlimited Beam Ammo")
}

TEST = ManualTest(
    slug=_SLUG,
    title="Trap items: Damage Trap, Ammo Depletion Trap, Freeze Trap",
    priority="P1",
    proves=(
        "client._handle_traps announces each received trap on the HUD, then applies it once the game "
        "has shown the message: Damage Trap removes a random 25-75% of maximum energy and never kills, Ammo Depletion "
        "Trap zeroes Missiles / Power Bombs / Dark Ammo / Light Ammo without touching capacities, and "
        "Freeze Trap opens a `freeze_trap_duration`-second window in which Samus is frozen via CPlayer::Freeze at "
        "random moments; none of them replays after a client restart"
    ),
    seed=1_000_022,
    options=presets.merge(
        presets.NO_RANDO_OPTIONS,
        presets.MAP_OPTIONS,
        presets.FAST_RETRY_OPTIONS,
        {"energy_per_tank": 100, "freeze_trap_duration": 60},
    ),
    start_inventory=_START_INVENTORY,
    setup=[
        "Host the generated multiworld and keep the server console open; every step pastes a `/send` into it.",
        "The start inventory holds 14 Energy Tanks, so maximum energy is 1499 and one Damage Trap removes "
        "a random 25-75% of that (about 375 to 1124). Traps cannot be in the start inventory, so none fire on connect.",
        "The start inventory leaves out Unlimited Missiles and Unlimited Beam Ammo so ammo is a real count. "
        "Open the pause screen's inventory once to note your Missile / Power Bomb / Dark / Light ammo totals "
        "(or watch the HUD counters).",
    ],
    notes=[
        "A trap takes effect one HUD message after it arrives, and no sooner than ~5 s after the previous "
        "trap. Send several at once to see them drip out one by one.",
        "Freeze is the engine's own player freeze (the effect Samus gets from ice attacks). A Freeze Trap "
        "does not freeze immediately: it opens a window (60 s here, 120 s by default) in which a freeze of "
        "4-6 s (by default) happens every 5-20 s. Mashing jump breaks a freeze early. The game refuses a freeze in a few "
        "player states (e.g. mid morph-ball transition); the client retries about a second later.",
        "Disguised traps (`trap_disguise`) and the pool placement are generation-time and covered by "
        "`test/test_pool.py` and `test/test_patch_data.py`.",
    ],
    steps=[
        Step(
            "Start New Game, connect the client, and let the first room settle.",
            "Full energy, nothing frozen, no trap messages.",
        ),
        Step(
            f"Server console: `/send {_SLUG} Damage Trap`",
            "A HUD memo `Damage Trap! You lose N% of your maximum energy.` with N between 25 and 75, and then "
            "energy drops by N% of the maximum (of 1499), not N% of the current value. Send a few more: "
            "N varies from trap to trap.",
        ),
        Step(
            f"Repeat `/send {_SLUG} Damage Trap` until energy is below ~375, then send one more.",
            "Energy drops to exactly 1 and Samus does not die. No DeathLink is sent if enabled.",
            why="A trap must never be lethal.",
        ),
        Step(
            f"Heal up (pick up a refill or reload), then `/send {_SLUG} Ammo Depletion Trap`",
            "A HUD memo `Ammo Depletion Trap! Your ammo is gone.` and Missiles, Power Bombs, Dark Ammo "
            "and Light Ammo are all 0. Pause screen still shows the full capacities (Energy Tanks etc. "
            "unchanged), and collecting an ammo pickup works normally afterwards.",
            why="Only the amounts are zeroed; plan_grants compares capacities, so nothing refills them.",
        ),
        Step(
            f"Server console: `/send {_SLUG} Freeze Trap`",
            "A HUD memo `Freeze Trap! You will freeze at random for 1 minute.` Over the next 60 s Samus "
            "freezes in ice 2-6 times for 4-6 s each, at uneven intervals, unable to move or shoot. "
            "Mashing jump shatters a freeze early. After 60 s no more freezes happen and a HUD memo `The Freeze Trap has worn off.` appears.",
        ),
        Step(
            f"`/send {_SLUG} Freeze Trap`, then stay in Morph Ball (rolling around) for the whole minute.",
            "Either Samus freezes as a ball or the freezes are skipped and land once she unmorphs. No crash, "
            "no permanent stuck state.",
            why="CPlayer::Freeze bails out in some states; the client retries about a second later.",
        ),
        Step(
            f"Paste all three in one go: `/send {_SLUG} Damage Trap`, `/send {_SLUG} Ammo Depletion Trap`, "
            f"`/send {_SLUG} Freeze Trap`",
            "Three memos and the three effects, one at a time, at least ~5 s apart, none dropped; the "
            "freezes then start within the next 5-20 s.",
        ),
        Step(
            f"Pause the game (or trigger a cutscene) and `/send {_SLUG} Damage Trap`, then unpause.",
            "The effect lands only after the game resumes, not during the pause / cutscene.",
        ),
        Step(
            "Wait for everything to settle, kill the client and restart it, reconnect.",
            "No trap fires again: no memos, no energy loss, no freeze.",
            why="The handled-trap index lives in AP DataStorage, not the save, so a reconnect does not replay.",
        ),
        Step(
            f"`/send {_SLUG} Freeze Trap` twice, 10 s apart.",
            "The random freezes keep going for about two windows (~2 minutes) in total, not two overlapping "
            "schedules (no double-freeze bursts).",
            why="A second Freeze Trap extends the window instead of stacking a second schedule.",
        ),
        Step(
            "Reload an older save (or die and reload) while connected.",
            "Still no replayed traps.",
        ),
    ],
    pass_criteria=[
        "Each trap shows its HUD memo and then applies exactly once.",
        "Damage Trap removes the announced 25-75% of maximum energy, floors at 1 HP, and never kills.",
        "Ammo Depletion Trap zeroes all four ammo amounts and leaves capacities alone.",
        "Freeze Trap freezes Samus at random moments for the configured window, each freeze can be broken by mashing jump, and a memo announces when the window ends.",
        "Traps wait out pauses and cutscenes, and drip out ~5 s apart.",
        "A client restart or save reload never replays a trap.",
        "No client traceback.",
    ],
    on_failure=[
        "`client/client.py::_handle_traps` / `_apply_trap` / `_handle_freeze_window`",
        "`client/traps.py`",
        "`client/game_interface.py::freeze_player` / `set_item_amount`",
        "`client/versions.py::player_freeze` (CPlayer::Freeze; NTSC 0x800144A4, PAL 0x80014540)",
        "`test/test_client_traps.py`",
    ],
)

if __name__ == "__main__":
    harness.cli(TEST)
