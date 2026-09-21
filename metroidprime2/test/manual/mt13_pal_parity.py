"""MT13 -- re-run the per-build-DOL-address tests on a PAL ISO.

Not a separate build of its own: this section tells the tester to re-run
MT01, MT03, MT04, and MT07 with ``--pal``. Those are the tests whose
subjects are per-build DOL addresses (warp hook,
``powerup_should_persist``/``powerup_max``, the current-area goal offset).
"""

from __future__ import annotations

from . import harness, presets
from .harness import ManualTest, Step

TEST = ManualTest(
    slug="mt13_pal_parity",
    title="PAL parity: the per-build DOL address tests on a PAL ISO",
    priority="P1",
    proves="MT01/MT03/MT04/MT07 pass identically on a PAL ISO (different DOL addresses)",
    seed=1_000_013,
    config_sha256="df56e050f34fffe9b8d2bfc66029d977ccc9ad28ab58a06c0bc082167404fac7",
    build_flags="--pal",
    options=presets.NO_RANDO_OPTIONS,
    notes=[
        (
            "This is not a separate build: it is a checklist to re-run the per-build-address "
            "tests with `--pal`."
        ),
        (
            "Any difference from the NTSC run means `client/versions.py` (or "
            "`tools/find_warp_addresses.py`) needs a PAL-specific fix."
        ),
    ],
    steps=[
        Step(
            "Run MT01 (`mt01_smoke_vanilla`) with `--pal`.",
            "It passes exactly as on NTSC.",
        ),
        Step("Run MT03 (`mt03_goal_area_poke`) with `--pal`.", "It passes exactly as on NTSC."),
        Step(
            "Run MT04 (`mt04_warp_to_start_save_station`) with `--pal`.",
            "It passes exactly as on NTSC.",
        ),
        Step("Run MT07 (`mt07_counter_persistence`) with `--pal`.", "It passes exactly as on NTSC."),
    ],
    pass_criteria=[
        "Every re-run test passes on PAL.",
        "No PAL-specific crash or address mismatch.",
    ],
    on_failure=[
        "`client/versions.py` (`PAL` address table)",
        "`tools/find_warp_addresses.py` (re-derive the warp hook for PAL)",
        "`client/warp_patch.py`",
    ],
)

if __name__ == "__main__":
    harness.cli(TEST)
