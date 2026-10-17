"""MT23 -- item scan hints: scanning a pickup hints the item inside (PLAN.md section AA)."""

from __future__ import annotations

from . import harness, presets
from .harness import ManualTest, SlotSpec, Step, Variant

_SLUG = "mt23_item_scan_hints"
# Generate.handle_name() truncates player names to 16 chars (see MT10); the
# companion's plando entries target this world by its truncated name.
_PRIMARY_PLAYER_NAME = _SLUG[:16].strip()
_COMPANION = "Prime1"
_FOREIGN_LOCATIONS = (
    "Temple Grounds: Hive Chamber A - Pickup (Missile)",
    "Temple Grounds: Hive Chamber B - Pickup (Missile)",
)
_OWN_LOCATION = "Temple Grounds: Communication Area - Pickup (Missile)"

TEST = ManualTest(
    slug=_SLUG,
    title="Item scan hints: scanning a pickup hints its item",
    priority="P1",
    proves=(
        "scanning a pickup to completion, before collecting it, sends a hint for the item inside, and each "
        "pickup's scan is independent of every other pickup showing the same text"
    ),
    seed=1_000_023,
    config_sha256="57f67d800b79e536313820236b412a56dbaca557bc67d6c8c31a6f580a8b984c",
    starting_room="Temple Grounds/Hive Save Station/Save Station",
    options=presets.merge(
        presets.NO_RANDO_OPTIONS,
        presets.MAP_OPTIONS,
        presets.FAST_RETRY_OPTIONS,
        {"item_scan_hints": "other_players"},
    ),
    start_inventory=presets.ALL_ITEMS_START,
    # Two pickups holding the same foreign item share their scan text,
    # which is exactly what open-prime-rando would pool into one SCAN.
    companions=[
        SlotSpec(
            name=_COMPANION,
            game="Metroid Prime",
            plando=[
                {
                    "item": "Missile Expansion",
                    "location": location,
                    "world": _PRIMARY_PLAYER_NAME,
                    "from_pool": True,
                }
                for location in _FOREIGN_LOCATIONS
            ],
        )
    ],
    setup=[
        (
            "Host the generated multiworld and connect the MP2 client **and** the Prime1 (Metroid Prime) slot "
            "with a text client, so hint messages are visible from both sides."
        ),
    ],
    notes=[
        f"`{_FOREIGN_LOCATIONS[0]}` and `{_FOREIGN_LOCATIONS[1]}` each hold a `{_COMPANION}` "
        f"Missile Expansion (identical scan text); `{_OWN_LOCATION}` holds one of your own items.",
        "Any other pickup holding a `Prime1` item is hinted too; check the spoiler for the full list.",
    ],
    steps=[
        Step(
            f"Go to `{_FOREIGN_LOCATIONS[0]}` and Scan Visor the pickup, but let go before the bar fills.",
            "No hint is sent.",
            why="Only a finished scan (progress 255) counts.",
        ),
        Step(
            "Scan the same pickup to completion, without collecting it.",
            "The scan text reads \"Prime1's Missile Expansion.\" as before. "
            "A hint for that location appears in both clients.",
        ),
        Step(
            f"Scan the pickup at `{_FOREIGN_LOCATIONS[1]}`, which shows the exact same scan text.",
            "It sends its own hint. (A shared scan asset would have counted it as already scanned.)",
            why="open-prime-rando pools identical scan text into one SCAN; item_scan_patch gives each pickup its own.",
        ),
        Step(
            f"Scan your own item at `{_OWN_LOCATION}`.",
            "The scan completes normally and no hint is sent (`other_players`).",
        ),
        Step(
            "Collect a pickup you have not scanned, then close and restart the client and reconnect.",
            "No hints are re-sent for already-scanned pickups.",
        ),
    ],
    variants={
        "all": Variant(
            options={"item_scan_hints": "all"},
            steps=[
                Step(
                    f"Scan your own item at `{_OWN_LOCATION}` to completion.",
                    "A priority hint for it is sent.",
                ),
            ],
            pass_criteria=["Pickups holding your own items hint too, at priority."],
        ),
    },
    pass_criteria=[
        "A partial scan sends nothing; a completed scan sends exactly one hint for that pickup's location.",
        "Two pickups with identical scan text hint independently.",
        "Pickups with your own items hint only under `all`.",
        "The scan text and collection of every pickup are unchanged.",
    ],
    on_failure=[
        "`client/item_scan_patch.py` (unique SCAN creation) and `hint_scans.py::item_scan_id`",
        "`hint_scans.py::item_scan_hint_entries` / slot_data `hint_scans`",
        "`client/client.py::_handle_hint_scans`",
    ],
)

if __name__ == "__main__":
    harness.cli(TEST)
