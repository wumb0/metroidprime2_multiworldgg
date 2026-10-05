"""MT19 -- item_map_dots: item locations drawn on the map and minimap."""

from __future__ import annotations

from . import harness, presets
from .harness import ManualTest, Step, Variant

TEST = ManualTest(
    slug="mt19_item_map_dots",
    title="Item Map Dots: a dot at every item in visited or map-station-revealed rooms",
    priority="P1",
    proves=(
        "item_map_dots draws a dot on the map and minimap at each item location once its room has "
        "been visited or revealed by a map station, hides the dot once the item is collected, and "
        "keeps it hidden across a save and reload"
    ),
    seed=1_000_019,
    config_sha256="648c6312937156d455afd6b6c92283887e94083a6eb0edb7c90dfa24040ff1fa",
    options=presets.merge(
        presets.NO_RANDO_OPTIONS,
        presets.FAST_RETRY_OPTIONS,
        presets.GOD_MODE_OPTIONS,
        {"map_visibility": "full_map", "item_map_dots": "on", "unvisited_room_names": True},
    ),
    # Every upgrade from the start so any room can be reached; the in-game
    # pickups still hold their items (start_inventory, not _from_pool).
    start_inventory=dict(presets.ALL_ITEMS_START),
    steps=[
        Step(
            "Load the game and open the map (pause, Map) in Landing Site. Move the map over to "
            "GFMC Compound without going there.",
            "Every Temple Grounds room is drawn (full_map), but GFMC Compound shows no item dots: "
            "you haven't visited it and no map station has revealed it.",
            why="dots use the same rule as door icons, so a map revealed from the start doesn't "
            "reveal them.",
        ),
        Step(
            "Walk into GFMC Compound and look at the minimap, then the pause map.",
            "Two white dots: one at the Missile Launcher pickup and one on the crashed ship "
            "(the second Missile). Both show on the minimap and on the pause map.",
        ),
        Step(
            "Collect the Missile Launcher location's item, then look at the minimap and pause map "
            "again.",
            "Its dot is gone. The ship's dot is still there.",
        ),
        Step(
            "Save at a save station, quit to the main menu, reload the save and look at GFMC "
            "Compound on the map.",
            "Still exactly one dot (the ship's).",
            why="the collected flag is saved with the world's map data.",
        ),
        Step(
            "Travel to Agon Wastes and use its map station (Agon Map Station) without visiting the "
            "rooms around it. Open the map and look at light-world Agon rooms you haven't been in "
            "that hold items (e.g. Mining Station A, Central Mining Station).",
            "Those rooms now show item dots although you have never entered them.",
        ),
    ],
    variants={
        "off": Variant(
            config_sha256="7f465e17f631505b768160837f09e398ae60894df3eb2923e363f6724e4cd9d9",
            options={"item_map_dots": "off"},
            steps=[
                Step(
                    "Load the game, walk into GFMC Compound and look at the minimap and pause map.",
                    "No item dots anywhere, in any room, even after visiting it.",
                ),
            ],
        ),
        "always": Variant(
            config_sha256="66855660e22a6e8fe1a226a29b4f7b3b8b95dab36b197b3ef63b4c6d4855bdea",
            options={"item_map_dots": "always"},
            steps=[
                Step(
                    "Load the game and open the pause map without leaving Landing Site. Move the "
                    "map over to GFMC Compound.",
                    "GFMC Compound already shows its two dots although you have never been there. "
                    "Every other drawn room with items shows its dots too.",
                ),
                Step(
                    "Go to GFMC Compound and collect the Missile Launcher location's item.",
                    "Its dot disappears; the ship's dot stays.",
                ),
            ],
        ),
        "map_station": Variant(
            config_sha256="c662dc37e00056faa31e74a60873068c7cee9779976c8cb4cc95f4b06a7f363c",
            options={"item_map_dots": "map_station"},
            steps=[
                Step(
                    "Load the game, walk into GFMC Compound and look at the minimap and pause map.",
                    "No dots anywhere, although you have visited GFMC Compound and the whole map is "
                    "drawn (full_map).",
                    why="dots wait for the world's map station, not for the room.",
                ),
                Step(
                    "Travel to Agon Wastes, open the pause map and look at light-world Agon rooms you "
                    "haven't been in that hold items (e.g. Mining Station A, Central Mining Station). "
                    "Then use Agon Map Station and look again.",
                    "No dots before the map station. After it, every Agon room holding an item shows "
                    "its dot, visited or not. Collecting an item makes its dot disappear.",
                ),
                Step(
                    "Go back to Temple Grounds and look at GFMC Compound on the map. Then use the "
                    "map station in Hive Chamber A and look again.",
                    "No dots in Temple Grounds before its own station (Agon's doesn't count). After "
                    "Hive Chamber A's station, GFMC Compound's dots appear.",
                    why="each world's map station only unlocks that world's dots.",
                ),
            ],
        ),
    },
    pass_criteria=[
        "A room's item dots appear once it is visited or its world's map station is used, and "
        "not before (even with the full map revealed).",
        "A collected item's dot disappears and stays gone after a save and reload.",
        "With the off variant no dot is ever drawn.",
        "With the always variant every drawn room shows its dots from the start.",
        "With the map_station variant no dot shows until the world's map station is used, then "
        "every drawn room in that world shows its dots, visited or not.",
    ],
    on_failure=[
        "No dots at all: `client/item_map_dots_patch.py` (jump table entry for type 0x12 and the "
        "cave), and that `pickup_map_icon.TXTR` made it into GGuiSys.pak",
        "Dots in unvisited rooms (or missing from them with always): the mode passed to "
        "`pickup_icon_visibility_installed`",
        "Dots that never go away: the pickup's `TranslatorDoorLocation` SpecialFunction "
        "(open-prime-rando `pickups/location.py`) or the cave's editor id argument",
        "Dots that come back after reloading: the world's SAVW `unmappable_objects`",
    ],
    notes=[
        "A crash or garbled icon when opening the map points at the cave first (wrong register "
        "for the object or CMapWorldInfo on this DOL version); run MT13 on PAL too.",
    ],
)

if __name__ == "__main__":
    harness.cli(TEST)
