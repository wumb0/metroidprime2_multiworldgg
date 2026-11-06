"""MT27 -- `map_rooms_reveal_dark_world_map`: a map station also maps the dark world."""

from __future__ import annotations

from . import harness, presets
from .harness import ManualTest, Step, Variant

_SLUG = "mt27_map_rooms_reveal_dark_world_map"

TEST = ManualTest(
    slug=_SLUG,
    title="Map Rooms Reveal Dark World Map: using Agon Map Station also maps Dark Agon Wastes",
    priority="P1",
    proves=(
        "client/map_reveal_patch.py makes a map station reveal the dark-world rooms of its world "
        "(vanilla only maps the light world), and does nothing when the option is off"
    ),
    seed=1_000_027,
    config_sha256="75e708a9d769e3d26ab9104a5d11f462641980e73d0a0f648db859dd53ba18d3",
    starting_room="Agon Wastes/Mining Plaza/Door to Plaza Access",
    options=presets.merge(
        presets.NO_RANDO_OPTIONS,
        presets.GOD_MODE_OPTIONS,
        presets.FAST_RETRY_OPTIONS,
        # Deliberately not MAP_OPTIONS: full_map would draw every room from the start and hide the
        # difference, and item dots would add noise.
        {
            "map_visibility": "vanilla",
            "item_map_dots": "off",
            "unvisited_room_names": True,
            "map_rooms_reveal_dark_world_map": True,
        },
    ),
    start_inventory=presets.merge_inventory(
        presets.ALL_ITEMS_START,
        presets.GOD_MODE_START_INVENTORY,
    ),
    notes=[
        "You start in Mining Plaza with everything. Agon Map Station is the room right next to the "
        "start (through the Morph Ball door); the route to the dark world is Mining Plaza -> Save "
        "Station A -> Transport Center -> Portal Terminal, whose portal leads to Dark Agon Wastes "
        "(Portal Site).",
        "Don't explore Dark Agon Wastes in step 1 beyond Portal Site: the test needs the other dark "
        "rooms to be unvisited.",
        "If the Portal Terminal portal won't activate, Transport Center's portal (to Crossroads) "
        "works the same way; use that dark room as the one you stand in instead.",
        "Each world has its own map station flag, so only Agon's station matters here. Temple Grounds "
        "and the other worlds are not part of this test.",
    ],
    steps=[
        Step(
            "Start New Game and connect the client. Walk Mining Plaza -> Save Station A -> Transport "
            "Center -> Portal Terminal and take the portal to Portal Site (Dark Agon Wastes). Open the "
            "pause map and look at the Dark Agon Wastes rooms.",
            "Only Portal Site (where you stand) is drawn among the dark rooms. Crossroads, Judgment Pit, "
            "Duelling Range, Trial Grounds, Dark Oasis and Doomed Entry are not.",
            why="vanilla map: an unvisited room isn't drawn without a map station. This is the "
            "baseline the rest of the test is compared with.",
        ),
        Step(
            "Return through the portal, walk back to Mining Plaza, go through the Morph Ball door to "
            "Agon Map Station and use the station.",
            "The station plays its map download and the light-world Agon rooms you haven't visited "
            "become drawn on the map.",
        ),
        Step(
            "Go back to Portal Site through the same portal and open the pause map on the Dark Agon "
            "Wastes rooms. Hover the cursor over rooms you have never entered.",
            "Every Dark Agon Wastes room is now drawn (Crossroads, Judgment Pit, Duelling Range, Trial "
            "Grounds, Dark Oasis, Doomed Entry and the rest), and hovering one shows its name.",
            why="the patch makes IsWorldVisible ignore the dark-world flag, so the station reveals "
            "dark rooms; unvisited_room_names (on here) then allows their names.",
        ),
        Step(
            "Save at a save station, quit to the main menu, reload the save and open the map in Dark "
            "Agon Wastes again.",
            "The dark rooms are still drawn.",
            why="the map-station-used flag is saved with the world's map data.",
        ),
    ],
    variants={
        "off": Variant(
            config_sha256="1b68650755d648d818df1e24d9f58ed1081a18e0f4c41e1d07895ef965c3a1b3",
            options={"map_rooms_reveal_dark_world_map": False},
            steps=[
                Step(
                    "Start New Game, connect the client, take the portal at Portal Terminal to Portal Site "
                    "and look at the pause map.",
                    "Only Portal Site is drawn among the dark rooms.",
                ),
                Step(
                    "Return, use Agon Map Station in Mining Plaza's side room, go back to Portal Site and "
                    "open the pause map again.",
                    "The unvisited light-world Agon rooms are drawn as in vanilla, but the Dark Agon Wastes "
                    "rooms you haven't visited are still not drawn. Nothing changed on the dark side.",
                    why="vanilla: a station only maps the light world.",
                ),
            ],
            pass_criteria=[
                "With the option off, using the station never reveals an unvisited dark room.",
                "The light-world part of the station's reveal still works.",
            ],
        ),
        "no_names": Variant(
            config_sha256="addb53a3409b9f832ec837fa3fb7df70af67ffd607e586aed353d55ffeed98bc",
            options={"unvisited_room_names": False},
            steps=[
                Step(
                    "Start New Game, connect the client, use Agon Map Station, then take the portal at "
                    "Portal Terminal to Portal Site and open the pause map.",
                    "Every Dark Agon Wastes room is drawn.",
                    why="the reveal doesn't depend on unvisited_room_names.",
                ),
                Step(
                    "Hover the cursor over a dark room you have never entered, then over Portal Site.",
                    "The unvisited room shows no name; Portal Site (visited) does.",
                ),
            ],
            pass_criteria=[
                "With unvisited_room_names off the dark rooms are still revealed by the station, "
                "but only visited ones show their name.",
            ],
        ),
    },
    pass_criteria=[
        "Before the station, only the visited dark room is drawn.",
        "After Agon Map Station, every Dark Agon Wastes room is drawn and shows its name on hover.",
        "The reveal survives a save and reload.",
        "With the option off the dark rooms stay hidden; with unvisited_room_names off they are drawn "
        "without names.",
        "No client traceback.",
    ],
    on_failure=[
        "`client/map_reveal_patch.py::reveal_dark_rooms_on_map_station` (the `li r3, 1` write at NTSC "
        "0x8010F428 / PAL 0x8010F5DC)",
        "`client/patcher_runner.py::map_reveal_installed` and the `map_rooms_reveal_dark_world_map` key "
        "in options.json (a missing key reads as off)",
        "`test/test_map_reveal_patch.py`",
    ],
)

if __name__ == "__main__":
    harness.cli(TEST)
