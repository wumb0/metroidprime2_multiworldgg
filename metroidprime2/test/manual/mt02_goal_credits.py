"""MT02 -- the real end-to-end goal path: kill Emperor Ing, escape, credits."""

from __future__ import annotations

from . import harness, presets
from .harness import ManualTest, Step

TEST = ManualTest(
    slug="mt02_goal_credits",
    title="Goal: beating the game reaches Credits and marks the goal",
    priority="P0",
    proves="beating the game reaches Credits and the client's current-area memory read marks the goal",
    seed=1_000_002,
    config_sha256="7c52a3a89f940eb48301dd5e121893e93e8d35f6ec1864ef71c88d4f3eaa08a4",
    starting_room="Sky Temple/Sanctum/Door to Sanctum Access",
    options=presets.merge(
        presets.NO_RANDO_OPTIONS,
        presets.MAP_OPTIONS,
        presets.GOD_MODE_OPTIONS,
        {"sky_temple_keys": 9},
    ),
    start_inventory=presets.merge_inventory(
        presets.ALL_ITEMS_START,
        presets.GOD_MODE_START_INVENTORY,
    ),
    steps=[
        Step("Start New Game.", "You spawn in the Emperor Ing arena (Sky Temple/Sanctum)."),
        Step(
            "Kill Emperor Ing.",
            "The boss dies; the escape sequence begins.",
        ),
        Step(
            "Complete the escape sequence and the Dark Samus 3 & 4 fight at Sky Temple Gateway.",
            "The Credits area loads.",
        ),
        Step(
            "Let the Credits area load for at least one client tick (0.5s).",
            "The client logs the goal, sends StatusUpdate(GOAL), and the server marks the slot "
            "finished (`!status` shows goal). The player never triggers a spurious location check.",
        ),
    ],
    pass_criteria=[
        "The goal is reported exactly once.",
        "No spurious location checks are sent around the Credits load.",
        "No client traceback.",
    ],
    notes=[
        (
            "The Credits room is `!!game_end_part3` (randovania Temple Grounds/Credits asset id "
            "`constants.CREDITS_MREA`); its TAreaId index is in `constants.GAME_END_AREA_INDICES`. "
            "Detection is `game_interface.current_mlvl()` == `constants.TEMPLE_GROUNDS_MLVL` plus "
            "`game_interface.current_area_id()` in that set -- no ISO patch involved."
        ),
    ],
    on_failure=[
        "`constants.GAME_END_AREA_INDICES` / `constants.TEMPLE_GROUNDS_MLVL`",
        "`client/game_interface.py::current_area_id` / `current_mlvl`",
        "`client/versions.py` AREA_ID_OFFSET for this build",
        "`client/client.py::_handle_check_goal`",
    ],
)

if __name__ == "__main__":
    harness.cli(TEST)
