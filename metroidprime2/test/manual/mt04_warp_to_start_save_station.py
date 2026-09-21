"""MT04 -- warp-to-start: SCLY layer + DOL hook, from a save-station start."""

from __future__ import annotations

from . import harness, presets
from .harness import ManualTest, Step, Variant

_BASE_STEPS = [
    Step(
        "Spawn in Hive Save Station and activate the save station.",
        'The prompt text carries the extra line "Hold L + R while choosing No to warp to the '
        'starting room."',
    ),
    Step(
        "Choose No *without* holding L + R.",
        "Bit-for-bit vanilla behavior: the no-save cinematic plays, no warp, no HUD memo.",
    ),
    Step(
        "Choose No *with* L + R held.",
        'The HUD memo "Returning to starting room..." appears, then a room transition ~3s later '
        "back into this same room.",
    ),
    Step(
        "Walk two rooms away, come back, and repeat the L+R decline.",
        "Same result: the layer is per-room, not a one-shot.",
    ),
    Step(
        "Travel to a different save station (Temple Grounds/Landing Site/Save Station, the ship) "
        "and repeat the L+R decline.",
        "The warp returns you to Hive Save Station, not the ship.",
    ),
]

TEST = ManualTest(
    slug="mt04_warp_to_start_save_station",
    title="Warp to Start: save-station warp layer + DOL hook",
    priority="P0",
    proves="L+R decline warps; plain decline is vanilla; the prompt shows the hint; the target is the starting room",
    seed=1_000_004,
    config_sha256="5db0bfca2fdf49f5f996727b060488672164d2a9e64bcf3155cc3543424e9316",
    starting_room="Temple Grounds/Hive Save Station/Save Station",
    options=presets.merge(presets.NO_RANDO_OPTIONS, presets.FAST_RETRY_OPTIONS),
    start_inventory=dict(presets.ALL_ITEMS_START),
    steps=_BASE_STEPS,
    variants={
        "off": Variant(
            options={"warp_to_start": False},
            config_sha256="c45504052fe0052aaf4d0f009e32fae347d1f651cf7d369a61b41ffd1276e582",
            steps=[
                Step(
                    "Spawn in Hive Save Station, activate it, and choose No with L + R held.",
                    "No hint line and no warp: with `warp_to_start: false` the warp layer/hook are "
                    "never installed.",
                )
            ],
        )
    },
    pass_criteria=[
        "The hint line appears only when the warp option is on.",
        "Plain decline (no L+R) is unchanged from vanilla.",
        "L+R decline warps to the starting room every time, from every save station.",
        "`--variant off` produces no hint and no warp.",
    ],
    on_failure=[
        "`client/warp_patch.py`",
        "`client/versions.py::WarpToStartAddresses`",
        "`tools/find_warp_addresses.py` (re-derive the hook address for this build)",
    ],
)

if __name__ == "__main__":
    harness.cli(TEST)
