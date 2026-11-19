"""MT30 -- ``map_rooms_reveal_dark_world_map`` on the Temple Grounds station.

MT27 proved the reveal for Agon Map Station; this module covers the case that
motivated the feature: the Temple Grounds station in Hive Chamber A does not
carry a ``IsWorldVisible`` branch (its room wires fifteen teleporter ``TEL1``
connections instead), so a different hook site had to be patched. If this
module passes but MT27 fails, only the plain four-station hook is broken.
"""

from __future__ import annotations

from . import harness, presets
from .harness import ManualTest, Step, Variant

_SLUG = "mt30_temple_grounds_map_station"

TEST = ManualTest(
    slug=_SLUG,
    title="Map reveal on the Temple Grounds station (Hive Chamber A)",
    priority="P1",
    proves=(
        "`map_rooms_reveal_dark_world_map` works for the Temple Grounds map station in "
        "Hive Chamber A even though that station wires teleporters instead of an IsWorldVisible "
        "branch: using it draws the unvisited dark Temple Grounds rooms on the map, and the off "
        "variant stays vanilla"
    ),
    seed=1_000_030,
    config_sha256="d811c641523e76202bf377a0c68cd979d5fac94f98c2eac2d8a8a3c41c41a540",
    starting_room="Temple Grounds/Hive Chamber A/Dock to Hive Access Tunnel",
    options=presets.merge(
        presets.NO_RANDO_OPTIONS,
        # Deliberately not MAP_OPTIONS: full_map would draw everything and hide the difference.
        {
            "map_visibility": "vanilla",
            "item_map_dots": "off",
            "unvisited_room_names": True,
            "map_rooms_reveal_dark_world_map": True,
        },
    ),
    start_inventory=presets.ALL_ITEMS_START,
    setup=[
        "You start in the Hive Chamber A doorway, the room with the Temple Grounds map station. "
        "Do not use the station before step 1.",
    ],
    notes=[
        "Temple Grounds' dark half is roughly twenty rooms (the Sky Temple Grounds / Ing side); "
        "you never need to enter it here -- seeing it drawn unvisited is the whole point.",
        "This station is the odd one out: Agon, Torvus and Sanctuary's stations set the world-wide "
        "mMapStationUsed flag directly, while Hive Chamber A's wires fifteen teleporters and would "
        "skip that flag. `station_always_marks_world` is what makes it mark the world anyway.",
    ],
    steps=[
        Step(
            "Start New Game, connect, and open the pause map before touching the station.",
            "The Temple Grounds rooms near you are drawn as visited light rooms; no dark Temple "
            "Grounds room is drawn at all.",
            why="vanilla: an unvisited room isn't drawn without a map station.",
        ),
        Step(
            "Use the map station in Hive Chamber A.",
            "The station plays its map download.",
        ),
        Step(
            "Open the pause map and look at (and hover over) the dark Temple Grounds rooms.",
            "Every unvisited dark Temple Grounds room is now drawn and shows its name on hover, "
            "exactly like the Agon behaviour in MT27.",
            why="the patch sets the same map-station-used flag from Hive Chamber A's station hook, "
            "and IsWorldVisible stops honouring the dark-world flag.",
        ),
        Step(
            "Save, quit to the main menu, reload, and open the map again.",
            "The dark rooms are still drawn.",
        ),
    ],
    variants={
        "off": Variant(
            config_sha256="9770fedf2f8ae7a84f1d08b86ccaca4e5c8c9f237a3a2766417bf361f00d3dd0",
            options={"map_rooms_reveal_dark_world_map": False},
            steps=[
                Step(
                    "Start New Game, open the pause map, use the Hive Chamber A map station, then "
                    "open the pause map again.",
                    "Light rooms reveal as in vanilla; no dark Temple Grounds room is ever drawn.",
                ),
            ],
            pass_criteria=[
                "With the option off, the station never reveals a dark room.",
            ],
        ),
    },
    pass_criteria=[
        "Before the station no dark Temple Grounds room is drawn.",
        "After the station all of them are, with names on hover.",
        "The reveal survives a save and reload.",
        "The off variant stays vanilla.",
        "No client traceback.",
    ],
    on_failure=[
        "`client/map_reveal_patch.py::station_always_marks_world` (the AcceptMapStation flag-site `bne`; "
        "plus `reveal_dark_rooms_on_map_station` for the IsWorldVisible side)",
        "`client/patcher_runner.py::map_reveal_installed` and the `map_rooms_reveal_dark_world_map` "
        "key in options.json (a missing key reads as off)",
        "`test/test_map_reveal_patch.py`",
    ],
)

if __name__ == "__main__":
    harness.cli(TEST)
