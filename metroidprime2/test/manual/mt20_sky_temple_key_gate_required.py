"""MT20 -- `sky_temple_keys_required`: the Sky Temple Gateway opens at N keys, not 9."""

from __future__ import annotations

from ...item_pool import STK_ITEM_NAMES
from . import harness, presets
from .harness import ManualTest, Step

_SLUG = "mt20_sky_temple_key_gate_required"
_REQUIRED = 6

TEST = ManualTest(
    slug=_SLUG,
    title="Sky Temple Keys Required: the Gateway's ring lowers at 6 keys, not 9",
    priority="P1",
    proves=(
        "client/sky_temple_key_gate_patch.py moves the Gateway's `Count Keys Returned` Open "
        "connection to an earlier internal state, so the ring of columns lowers once "
        f"{_REQUIRED} keys are held and stays up with {_REQUIRED - 1}"
    ),
    seed=1_000_020,
    config_sha256="47e7f0d0f3f5e86a375b8ef2c3c911ea724586a4708d69412fdb853e357ec347",
    starting_room="Sky Temple Grounds/Sky Temple Gateway/Spawn Point/Front of Teleporter",
    options=presets.merge(
        presets.NO_RANDO_OPTIONS,
        presets.MAP_OPTIONS,
        presets.GOD_MODE_OPTIONS,
        presets.FAST_RETRY_OPTIONS,
        # All 9 keys findable (so the pool still holds them) but only 6 needed.
        {"sky_temple_keys": 9, "sky_temple_keys_required": _REQUIRED},
    ),
    # Everything except the keys, then keys 1-5 only: one short of the
    # requirement at spawn. Key 6 is sent from the server console below.
    start_inventory=presets.merge_inventory(
        {**presets.ALL_ITEMS_START, **dict.fromkeys(STK_ITEM_NAMES, 0)},
        presets.GOD_MODE_START_INVENTORY,
        dict.fromkeys(STK_ITEM_NAMES[: _REQUIRED - 1], 1),
    ),
    setup=[
        "Host the generated multiworld and keep the server console open; step 3 needs it.",
    ],
    notes=[
        f"Start inventory holds Sky Temple Keys 1-{_REQUIRED - 1}; `sky_temple_keys=9` still "
        "places all 9 in the pool, so the extra copies are wherever fill put them (see the spoiler).",
        "Vanilla needs 9. If the ring lowers early at 5 keys the patch moved the connection too far; "
        "if it needs 9 the patch was not applied.",
    ],
    steps=[
        Step(
            "Start New Game and connect the client.",
            f"You spawn at Sky Temple Gateway holding keys 1-{_REQUIRED - 1}. Five of the nine "
            "columns are raised, and the ring of columns around the teleporter is still up.",
        ),
        Step(
            "Walk around the teleporter and try to enter it. Wait at least 10 seconds.",
            "The teleporter stays blocked; nothing lowers.",
            why=f"{_REQUIRED - 1} keys is one short of the requirement.",
        ),
        Step(
            f"From the server console, run `/send <player> Sky Temple Key {_REQUIRED}`.",
            f"Once the client delivers the key the gate sequence runs: a \"Returned {_REQUIRED} "
            "Keys\" HUD message appears and the ring of columns lowers, with only 6 of the 9 "
            "keys held.",
        ),
        Step(
            "Walk into the teleporter.",
            "It works and you reach Sky Temple Energy Controller.",
        ),
        Step(
            "Return to the Gateway, save, reset Dolphin, reload the save and reconnect.",
            "The ring is lowered again on arrival (the keys are re-counted on room load).",
        ),
    ],
    pass_criteria=[
        f"With {_REQUIRED - 1} keys held the ring stays up.",
        f"With {_REQUIRED} keys held (not 9) the ring lowers and the teleporter is usable.",
        "No client traceback.",
    ],
    on_failure=[
        "`options.py::SkyTempleKeysRequired`",
        "`item_pool.py::sky_temple_keys_required_count`",
        "`client/sky_temple_key_gate_patch.py::set_sky_temple_key_requirement`",
        "`client/patcher_runner.py::sky_temple_keys_required_installed`",
        "`test/test_sky_temple_key_gate_patch.py`",
    ],
)

if __name__ == "__main__":
    harness.cli(TEST)
