"""MT05 -- the warp target follows ``starting_area``, not "nearest save"."""

from __future__ import annotations

from . import harness, presets
from .harness import ManualTest, Step

TEST = ManualTest(
    slug="mt05_warp_to_start_remote_room",
    title="Warp to Start: target follows a non-save-station starting room",
    priority="P0",
    proves="warp-to-start returns to the configured starting_area, even when it isn't a save station",
    seed=1_000_005,
    config_sha256="9f7c292a409a0f55ae104aeb999d76f1011fdfc5c5ed92b21f66aa62c68ed9bd",
    starting_room="Temple Grounds/Windchamber Gateway/Door to Path of Eyes",
    options=presets.merge(
        presets.NO_RANDO_OPTIONS,
        presets.MAP_OPTIONS,
        presets.FAST_RETRY_OPTIONS,
        {"starting_room": "anywhere"},
    ),
    start_inventory=dict(presets.ALL_ITEMS_START),
    steps=[
        Step(
            "Start New Game and note the room you spawn in.",
            "You spawn in Windchamber Gateway (a non-save-station room).",
        ),
        Step(
            "Travel to the nearest save station and decline with L + R held.",
            "You land back in Windchamber Gateway, not the save station.",
        ),
    ],
    pass_criteria=[
        "The warp target is the forced starting room (Windchamber Gateway).",
        "The 18 save rooms are the only warp sources (you cannot warp from elsewhere).",
    ],
    on_failure=[
        "`client/warp_patch.py` (`warp_patch.register` uses `configuration.starting_area`)",
        "`logic/regions.py::can_warp_to_start`",
    ],
)

if __name__ == "__main__":
    harness.cli(TEST)
