"""MT17 -- the `goal` option: skipping Emperor Ing, Dark Samus 3 & 4, or both."""

from __future__ import annotations

from . import harness, presets
from .harness import ManualTest, Step, Variant

TEST = ManualTest(
    slug="mt17_goal_boss_skip",
    title="Goal: both_bosses (default), emperor_ing, and keys all report the goal correctly",
    priority="P0",
    proves=(
        "options.py's Goal choice controls which of the three memory-read conditions in "
        "client.py's _handle_check_goal reports the multiworld goal, and none of them change "
        "what's patched into the ISO -- the escape sequence and Dark Samus 3 & 4 fight always "
        "play out exactly as in vanilla regardless of the setting"
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
                    "No goal is reported: entering that room alone does not satisfy emperor_ing.",
                ),
                Step(
                    "Continue to the Sanctum and kill Emperor Ing.",
                    "No goal is reported yet -- the escape sequence's forced camera run starts "
                    "as normal.",
                ),
                Step(
                    "Let the escape run carry you out of the Sanctum into Sanctum Access (the "
                    "very first room transition after his death).",
                    "Within one client tick of that transition, the client logs the goal, sends "
                    "StatusUpdate(GOAL), and the server marks the slot finished -- well before "
                    "reaching Sky Temple Gateway or fighting Dark Samus 3 & 4.",
                ),
                Step(
                    "Keep playing through the rest of the escape sequence and the Dark Samus "
                    "3 & 4 fight to the Credits.",
                    "Everything plays out exactly like vanilla (nothing was skipped or patched); "
                    "the goal is not reported a second time.",
                ),
            ],
            pass_criteria=[
                "The goal fires immediately after leaving the Sanctum post-kill, not merely on "
                "entering Sky Temple Energy Controller and not only at the Credits.",
                "The escape sequence and Dark Samus 3 & 4 fight are unaffected and still playable.",
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
                    "Within one client tick of entering that room, the client logs the goal, "
                    "sends StatusUpdate(GOAL), and the server marks the slot finished -- before "
                    "reaching the Sanctum, fighting either boss, or seeing the Credits.",
                ),
                Step(
                    "Keep playing through the Sanctum, Emperor Ing, the escape sequence, and "
                    "Dark Samus 3 & 4 to the Credits.",
                    "Everything plays out exactly like vanilla; the goal is not reported again.",
                ),
            ],
            pass_criteria=[
                "The goal fires on entering Sky Temple Energy Controller, before either boss.",
                "The goal is reported exactly once, with no spurious location checks.",
            ],
        ),
    },
    notes=[
        (
            "All three conditions are plain memory reads (current MLVL + "
            "CStateManager::m_nextAreaId, EchoesInterface.current_mlvl/current_area_id) -- no ISO "
            "patch is involved for any of them, so the escape sequence and Dark Samus 3 & 4 fight "
            "are identical across every variant of this test."
        ),
        (
            "emperor_ing's detection is a proxy, not a read of his health/state: "
            "constants.SKY_TEMPLE_SANCTUM_AREA_INDEX (his arena, which -- like every other "
            "Guardian boss room in this game -- seals shut on entry and only opens once he's "
            "dead) is latched on entry, and the goal fires the first time the area changes again."
        ),
    ],
    on_failure=[
        "`constants.GOAL_BOTH_BOSSES` / `GOAL_EMPEROR_ING` / `GOAL_KEYS` / "
        "`GREAT_TEMPLE_SKY_TEMPLE_MLVL` / `SKY_TEMPLE_ENERGY_CONTROLLER_AREA_INDEX` / "
        "`SKY_TEMPLE_SANCTUM_AREA_INDEX`",
        "`options.py::Goal`",
        "`client/client.py::_handle_check_goal`",
        "`test/test_goal_detection.py::TestBossSkipGoals`",
    ],
)

if __name__ == "__main__":
    harness.cli(TEST)
