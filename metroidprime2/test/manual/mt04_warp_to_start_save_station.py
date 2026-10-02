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
    config_sha256="622aca92daef2dda68772ccb0f5207150208486ecb89d934a54c2c745dc82694",
    starting_room="Temple Grounds/Hive Save Station/Save Station",
    options=presets.merge(presets.NO_RANDO_OPTIONS, presets.MAP_OPTIONS, presets.FAST_RETRY_OPTIONS),
    start_inventory=dict(presets.ALL_ITEMS_START),
    steps=_BASE_STEPS,
    variants={
        "off": Variant(
            options={"warp_to_start": False},
            config_sha256="bcbf2d94f2dca3ef71bf2933ebbf95833bd9cf6bb88de0b0d824d0b64e62d561",
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
