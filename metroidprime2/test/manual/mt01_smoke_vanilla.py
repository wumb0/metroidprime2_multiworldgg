"""MT01 -- smoke test: a default-options patched ISO boots, plays, saves."""

from __future__ import annotations

from . import harness, presets
from .harness import ManualTest, Step

TEST = ManualTest(
    slug="mt01_smoke_vanilla",
    title="Smoke: a vanilla patched ISO boots, plays, and saves",
    priority="P0",
    proves="a default-options patched ISO boots, starts, saves, and reports a check",
    seed=1_000_001,
    config_sha256="527ae6a267147f578f5db8d33559d7cea7f53ccf205bdd3f98c356965f5f0e06",
    options=presets.merge(presets.NO_RANDO_OPTIONS, presets.MAP_OPTIONS),
    steps=[
        Step("Boot the patched ISO in Dolphin.", "The game reaches the title screen; New Game works."),
        Step(
            "Start New Game and skip the ship cutscene with Start.",
            "You spawn at the vanilla Landing Site save station.",
        ),
        Step(
            "Walk to Hive Chamber A and collect the pickup there.",
            "The game plays the pickup animation and the client logs the location check; the server "
            "shows the check, and the HUD memo names the item.",
        ),
        Step("Return to the ship and save at the save station.", "The save completes normally."),
        Step("Quit to the main menu and load the save.", "The save loads and the pickup is still collected."),
    ],
    pass_criteria=[
        "The ISO boots and reaches gameplay with no crash.",
        "Hive Chamber A's check is reported exactly once (no duplicate location check).",
        "The in-game HUD memo matches the item's name.",
        "Saving, quitting, and loading works.",
    ],
    on_failure=[
        "`client/patcher_runner.py` (the DOL writes and the patch pipeline)",
        "`patch_data.py` (the generated `config.json`)",
        "the pinned open-prime-rando version (`utils.OPEN_PRIME_RANDO_VERSION`)",
    ],
)

if __name__ == "__main__":
    harness.cli(TEST)
