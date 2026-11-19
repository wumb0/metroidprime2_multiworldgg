"""MT29 -- ``pre_scan_phazon_site``: the Phazon Site barrier starts solved.

The barrier in Dark Agon Wastes/Phazon Site normally drops after scanning the
three scan-post pillars, which plays the barrier cutscene. The patch pre-solves
the three relays through the SCLY so the room loads with the barrier already
down and no cutscene, and the ``Event - Phazon Site Barrier`` location folds
out of logic. The ``off`` variant re-checks the vanilla chain is untouched.
"""

from __future__ import annotations

from . import harness, presets
from .harness import ManualTest, Step, Variant

_SLUG = "mt29_phazon_site_barrier"

TEST = ManualTest(
    slug=_SLUG,
    title="Pre-scanned Phazon Site barrier (pre_scan_phazon_site)",
    priority="P1",
    proves=(
        "with `pre_scan_phazon_site` on, Dark Agon Wastes/Phazon Site loads with the barrier at the "
        "Watering Hole door already retracted and its scan cutscene never plays, the three scan posts "
        "are left in place but are inert, and the door is usable with zero scans; with it off the "
        "vanilla scan-three-then-cutscene chain still works"
    ),
    seed=1_000_029,
    config_sha256="797f7fc0a151c9db372f5788ee8b9d38881ef9cc0a15d397321935ba7a3b2b63",
    starting_room="Dark Agon Wastes/Phazon Site/Door to Bitter Well",
    options=presets.merge(presets.NO_RANDO_OPTIONS, {"pre_scan_phazon_site": True}),
    start_inventory=presets.ALL_ITEMS_START,
    setup=[
        "You start in Phazon Site on the Bitter Well side; the barrier and its three scan posts are "
        "toward the Watering Hole door.",
    ],
    notes=[
        "The patch flips the three relay connections to Active in the room SCLY (the same state the "
        "cutscene leaves behind); it does not remove the posts or the scan headers.",
        "The same mechanism is why the barrier event folds out of the logic: nothing can require a "
        "scan that never needs happening.",
    ],
    steps=[
        Step(
            "Start New Game and let Phazon Site finish loading.",
            "No scan cutscene plays. The barrier at the Watering Hole door is already gone; the three "
            "scan posts stand there visibly solved (glowing).",
        ),
        Step(
            "Walk straight to the Watering Hole door without scanning anything and go through.",
            "The door works immediately; zero scans were needed.",
        ),
        Step(
            "Go back and scan all three posts.",
            "Nothing happens: no cutscene, no sound cue, the room state does not change.",
        ),
        Step(
            "Save, reload the save, and re-enter the room.",
            "Barrier still down, still no cutscene.",
        ),
    ],
    variants={
        "off": Variant(
            config_sha256="51d48ba2222a39467ebe5d6689feee8c2b67bf1d956a356339d4aa4aaeb36683",
            options={"pre_scan_phazon_site": False},
            notes=[
                "Re-checks the vanilla chain in the same room: barrier present and blocking, "
                "scanning the three posts fires the cutscene and opens the door.",
            ],
        ),
    },
    pass_criteria=[
        "On: room loads with the barrier down, no cutscene, door usable with zero scans.",
        "On: re-scanning the posts is inert; the state survives save/reload.",
        "Off: barrier present; three scans -> cutscene -> door opens (vanilla chain intact).",
    ],
    on_failure=[
        "`client/phazon_site_patch.py` (SCLY relay solve in the Phazon Site room)",
        "`logic/requirements.py::extra_pregranted_events` (folds the barrier event when the option is on)",
        "`test/test_phazon_site_patch.py`",
    ],
)

if __name__ == "__main__":
    harness.cli(TEST)
