"""MT17 -- the `goal` option: skipping Emperor Ing, Dark Samus 3 & 4, or both."""

from __future__ import annotations

from . import harness, presets
from .harness import ManualTest, Step, Variant

TEST = ManualTest(
    slug="mt17_goal_boss_skip",
    title="Goal: both_bosses (default), emperor_ing, and keys all report the goal correctly",
    priority="P0",
    proves=(
        "options.py's Goal choice controls when the multiworld goal is reported: both_bosses "
        "patches nothing and reports at the Credits; emperor_ing and keys patch a warp to the "
        "Credits into the ISO (client/goal_warp_patch.py) the moment their condition is met, "
        "and the client reports the goal on reaching it"
    ),
    seed=1_000_017,
    config_sha256="968142eb15adb5ff84534ea504c8c18a8bbc71c1a32335f8f0c356276a60be2f",
    starting_room="Sky Temple Grounds/Sky Temple Gateway/Spawn Point/Front of Teleporter",
    options=presets.merge(
        presets.NO_RANDO_OPTIONS,
        presets.MAP_OPTIONS,
        presets.GOD_MODE_OPTIONS,
        presets.FAST_RETRY_OPTIONS,
        # All 9 keys precollected: the Gateway's ring is already open at
        # spawn, so every variant below starts able to walk straight into
        # Sky Temple without first having to go find any keys.
        {"sky_temple_keys": 9},
    ),
    start_inventory=presets.merge_inventory(
        presets.ALL_ITEMS_START,
        presets.GOD_MODE_START_INVENTORY,
    ),
    steps=[
        Step(
            "Start New Game.",
            "You spawn at Sky Temple Gateway, facing the teleporter with its ring of columns "
            "already lowered (all 9 keys are precollected).",
        ),
        Step(
            "Walk into the teleporter and through Sky Temple Energy Controller.",
            "No goal is reported yet -- `goal` defaults to both_bosses, which only accepts the "
            "Credits.",
        ),
        Step(
            "Continue to the Sanctum and kill Emperor Ing.",
            "No goal is reported yet; the escape sequence begins.",
        ),
        Step(
            "Complete the escape sequence and the Dark Samus 3 & 4 fight back at Sky Temple Gateway.",
            "The Credits area loads. After at least one client tick (0.5s), the client logs the "
            "goal, sends StatusUpdate(GOAL), and the server marks the slot finished (`!status` "
            "shows goal) -- the same behavior as MT02, reached from a different spawn point.",
        ),
    ],
    pass_criteria=[
        "The goal is reported exactly once, only once the Credits are reached.",
        "No spurious location checks are sent around any of the transitions above.",
        "No client traceback.",
    ],
    variants={
        "emperor_ing": Variant(
            config_sha256="d9a194ca2532ab93ec88c60a1c2cf3f1fea3fbea3bbf91fdcdb125448aff45ed",
            options={"goal": "emperor_ing"},
            steps=[
                Step(
                    "Start New Game, then walk into Sky Temple Energy Controller.",
                    "No goal is reported and no warp happens: entering that room alone does not "
                    "satisfy emperor_ing, and its arrival cinematic plays as in vanilla.",
                ),
                Step(
                    "Continue to the Sanctum and kill Emperor Ing, then leave the Sanctum.",
                    "No goal is reported yet -- the escape sequence's forced camera run starts "
                    "as normal, and leaving the Sanctum does not report anything.",
                ),
                Step(
                    "Run the escape sequence back to Sky Temple Energy Controller and use its "
                    "teleporter to return to Sky Temple Gateway.",
                    "About a second after arriving in Sky Temple Gateway you are warped to the "
                    "Credits (the Dark Samus 3 & 4 intro cinematic does not play). Within one "
                    "client tick of the Credits area loading, the client logs the goal, sends "
                    "StatusUpdate(GOAL), and the server marks the slot finished.",
                ),
            ],
            pass_criteria=[
                "The warp to the Credits happens on the first return to Sky Temple Gateway "
                "after Emperor Ing's death, with no Dark Samus 3 & 4 fight.",
                "Nothing warps or reports the goal on the first visit to Sky Temple Gateway "
                "(before Ing), on entering Sky Temple Energy Controller, or on leaving the "
                "Sanctum.",
                "The goal is reported exactly once, with no spurious location checks.",
            ],
        ),
        "keys": Variant(
            config_sha256="ced88757e36a584cf6d179929da52f21c09c909756995ae27c522733e09fa6ad",
            options={"goal": "keys"},
            steps=[
                Step(
                    "Start New Game, then walk into the teleporter and through to Sky Temple "
                    "Energy Controller.",
                    "The arrival cinematic does not play; about a second after arriving you are "
                    "warped to the Credits. The client logs the goal, sends StatusUpdate(GOAL), "
                    "and the server marks the slot finished -- before reaching the Sanctum or "
                    "fighting either boss.",
                ),
            ],
            pass_criteria=[
                "The warp to the Credits happens on arriving in Sky Temple Energy Controller, "
                "before either boss.",
                "The goal is reported exactly once, with no spurious location checks.",
            ],
        ),
    },
    notes=[
        (
            "Detection is a memory read (current MLVL + CStateManager::m_nextAreaId, "
            "EchoesInterface.current_mlvl/current_area_id): the Credits areas for every goal, "
            "plus Sky Temple Energy Controller for keys. emperor_ing has no client-side proxy "
            "for Ing's death; the ISO patch keys off the game's own state instead (Sanctum's "
            "death sequence activates the Gateway's `Dark Samus Battle3 Intro` layer, and the "
            "warp hangs off that layer's OcclusionRelay)."
        ),
        (
            "Both warps are SCLY-only edits (no DOL patch) that replace the room's own arrival "
            "cinematic with a 1s timer into a WorldTeleporter to `!!game_end_part3`; their "
            "wiring was checked against the retail NTSC-U and PAL rooms but never run in-game "
            "before this test."
        ),
        (
            "If the warp misbehaves (stuck camera, white screen, wrong room), suspect the "
            "removed cinematic: it normally hands control back to the player, and the warp "
            "leaves before that would happen."
        ),
    ],
    on_failure=[
        "`constants.GOAL_BOTH_BOSSES` / `GOAL_EMPEROR_ING` / `GOAL_KEYS` / "
        "`GREAT_TEMPLE_SKY_TEMPLE_MLVL` / `SKY_TEMPLE_ENERGY_CONTROLLER_AREA_INDEX` / "
        "`SKY_TEMPLE_ENERGY_CONTROLLER_MREA` / `CREDITS_MREA`",
        "`options.py::Goal`",
        "`client/goal_warp_patch.py`",
        "`client/patcher_runner.py::goal_warp_installed`",
        "`client/client.py::_handle_check_goal`",
        "`test/test_goal_detection.py::TestBossSkipGoals`",
        "`test/test_goal_warp_patch.py`",
    ],
)

if __name__ == "__main__":
    harness.cli(TEST)
