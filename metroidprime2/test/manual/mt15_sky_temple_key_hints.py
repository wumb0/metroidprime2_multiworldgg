"""MT15 -- Sky Temple Key hint scans: pillar text and scan-triggered hints (PLAN.md section Q)."""

from __future__ import annotations

from ...item_pool import STK_ITEM_NAMES
from . import harness, presets
from .harness import ManualTest, Step, Variant

_SLUG = "mt15_sky_temple_key_hints"
# Generate.handle_name() truncates player names to 16 chars (see MT10); the
# plando entry below targets the companion by name, so keep it short.
_COMPANION = "Filler1"
_OWN_KEY_LOCATION = "Sky Temple Grounds: War Ritual Grounds - Pickup (Missile)"

TEST = ManualTest(
    slug=_SLUG,
    title="Sky Temple Key hints: pillar text and scan-triggered server hints",
    priority="P1",
    proves=(
        "each Sky Temple Gateway pillar names its key's real location, and only a completed scan "
        "sends that hint to the server"
    ),
    seed=1_000_015,
    config_sha256="ff879caf0cf848334ba65b199a8c23045ea11d2e64cc6cf95d115d5fe204ae50",
    starting_room="Sky Temple Grounds/Sky Temple Gateway/Spawn Point/Front of Teleporter",
    options=presets.merge(
        presets.NO_RANDO_OPTIONS,
        presets.MAP_OPTIONS,
        presets.FAST_RETRY_OPTIONS,
        # Keys 1-7 go into the pool, keys 8-9 start collected, so one run
        # covers "another player's world", "your world" and "already owned".
        {"sky_temple_keys": 7, "sky_temple_key_hints": "scanned"},
    ),
    # Every item except the keys themselves: a start-inventory key would
    # still be placed in the pool, but owning all 9 at spawn is not what a
    # real seed looks like in the gateway.
    start_inventory={**presets.ALL_ITEMS_START, **dict.fromkeys(STK_ITEM_NAMES, 0)},
    plando=[
        {"item": "Sky Temple Key 1", "location": "The Button", "world": _COMPANION, "from_pool": True},
        {"item": "Sky Temple Key 2", "location": _OWN_KEY_LOCATION, "from_pool": True},
    ],
    companions=[presets.filler_slot(1)],
    setup=[
        (
            "Host the generated multiworld and connect the MP2 client **and** the Filler1 (Clique) slot "
            "with a text client, so hint messages are visible from both sides."
        ),
    ],
    notes=[
        f"Key 1 is plando'd to `{_COMPANION}`'s `The Button`; key 2 to `{_OWN_KEY_LOCATION}`.",
        "Keys 3-7 are wherever fill put them (see the spoiler); keys 8 and 9 start collected.",
        (
            "The pillars are the 9 Luminoth scan posts around the gateway's teleporter. Each rewritten "
            "text names its key, so which post is which doesn't matter."
        ),
    ],
    steps=[
        Step(
            "Connect the client and wait a few seconds in the gateway without scanning anything.",
            "No hints are sent (`/hints` in the client shows none for the Sky Temple Keys).",
        ),
        Step(
            "Scan Visor on a pillar; hold scan until the bar is about half full, then let go / look away.",
            "No hint is sent and the client logs nothing about a hint scan.",
            why="Only progress == 255 (a finished scan) counts.",
        ),
        Step(
            "Scan the Sky Temple Key 1 pillar to completion.",
            f"Text reads \"Sky Temple Key 1 is in {_COMPANION}'s The Button.\" in item/player/location "
            "colors. The client logs `Hint scan complete`, and a priority hint for key 1 at "
            f"`{_COMPANION}`'s `The Button` shows up in both clients.",
        ),
        Step(
            "Scan the Sky Temple Key 2 pillar.",
            f'Text reads "Sky Temple Key 2 is in your {_OWN_KEY_LOCATION}." and the matching hint '
            "appears.",
        ),
        Step(
            "Scan the Sky Temple Key 8 and 9 pillars.",
            'Both read "... is already in your possession." No hint is sent for either.',
        ),
        Step(
            "Scan the pillars for keys 3-7.",
            "Each names the location the spoiler lists for that key, and each sends exactly one hint.",
        ),
        Step(
            "Open the Logbook (Sky Temple Key Hints).",
            "Each entry's body shows the same hint text as the scan.",
        ),
        Step(
            "Close and restart the MP2 client, then reconnect.",
            "No duplicate hint messages appear (the server ignores already-known hints).",
        ),
        Step(
            "Save, reset Dolphin, reload the save, and reconnect.",
            "The scanned pillars are still marked scanned; still no duplicate hints.",
        ),
    ],
    variants={
        "disabled": Variant(
            config_sha256="f98c656d0a1d0d4ab890e2d0d6ee37a3dc12f936fc7e365e405100db6a9e0145",
            options={"sky_temple_key_hints": "disabled"},
            steps=[
                Step(
                    "Scan any pillar to completion.",
                    'Text reads "Sky Temple Key N is lost somewhere in Aether." No hint is sent.',
                )
            ],
            pass_criteria=["No pillar reveals a location and no scan sends a hint."],
        ),
        "precollected": Variant(
            config_sha256="ab5d9e23e309e879b176eefae22562270fc3e99cd09ae7fe5b78f8f6550923f6",
            options={"sky_temple_key_hints": "precollected"},
            steps=[
                Step(
                    "Connect the client before scanning anything.",
                    "Hints for keys 1-7 are already known on connect; none for keys 8 and 9.",
                ),
                Step(
                    "Scan the Sky Temple Key 1 pillar.",
                    f"Text names `{_COMPANION}`'s `The Button`, and no new hint message appears.",
                ),
            ],
            pass_criteria=[
                "Every placed key's hint exists before any scan; pillar text still names each key's location."
            ],
        ),
    },
    pass_criteria=[
        "Every pillar's text names its key's real location (or says it's already owned).",
        "A partial scan sends nothing; a completed scan sends exactly one priority hint.",
        "Precollected keys never produce a hint.",
        "Client restarts and save reloads don't duplicate hints.",
    ],
    on_failure=[
        "`patch_data.py::_sky_temple_key_string_changes` (wrong or missing text)",
        "`hint_scans.py` (`SKY_TEMPLE_KEY_HINT_SCANS` strg/scan table, `newly_completed_hints`)",
        "`client/game_interface.py::read_scan_progress` / `client/versions.py::SCAN_STATES_OFFSET`",
        "`client/client.py::_handle_hint_scans`",
    ],
)

if __name__ == "__main__":
    harness.cli(TEST)
