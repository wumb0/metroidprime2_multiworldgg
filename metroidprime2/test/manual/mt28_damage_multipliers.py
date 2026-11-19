"""MT28 -- incoming and outgoing damage multipliers.

One room (Dark Agon Temple) exercises both hooks: the Dark Aether ambience
hits the player every second (``CStateManager::ApplyLocalDamage``), and the
Amorbis fight measures outgoing shot damage. The A/B is the build against its
``off`` variant -- both runs use the same inventory, so no vanilla reference
numbers are needed.
"""

from __future__ import annotations

from . import harness, presets
from .harness import ManualTest, Step, Variant

_SLUG = "mt28_damage_multipliers"

# Double Damage would stack on top of the outgoing multiplier and muddy the
# per-shot comparison; the suits keep the dark ambience survivable so the
# tick rate can be watched rather than raced against.
_START_INVENTORY = {
    name: count
    for name, count in presets.ALL_ITEMS_START.items()
    if name != "Double Damage"
} | {"Energy Tank": 10}

TEST = ManualTest(
    slug=_SLUG,
    title="Incoming and outgoing damage multipliers",
    priority="P1",
    proves=(
        "`incoming_damage_multiplier` scales every hit on Samus (Dark Aether ambience included) at "
        "`ApplyLocalDamage` before suit reduction and Defense Up, and `outgoing_damage_multiplier` "
        "scales the beams, missiles and bombs the way Double Damage scales them, stacking with it"
    ),
    seed=1_000_028,
    config_sha256="8fd478183bd07b9fdc5d75d45160bd4d8867340baac16bc888fe3b1deeeff260",
    starting_room="Dark Agon Wastes/Dark Agon Temple/Door to Dark Agon Temple Access",
    options=presets.merge(
        presets.NO_RANDO_OPTIONS,
        {
            "incoming_damage_multiplier": 200,
            "outgoing_damage_multiplier": 200,
            "energy_per_tank": 100,
        },
    ),
    start_inventory=_START_INVENTORY,
    setup=[
        "10 Energy Tanks at 100 energy each means full energy is 1099; note it on the pause screen.",
        "Amorbis is in this room. Fight it with fully charged Power Beam shots only, and count shots "
        "to kill; the same count applies in the `off` variant run.",
        "Run this module back-to-back with `--variant off` for the A/B comparison in the steps.",
    ],
    notes=[
        "The multiplier is raw damage before the Dark Suit reduction, so the A/B tick rates compare "
        "cleanly while the suit keeps you alive either way.",
        "Both multipliers are percent options (10-500, default 100 = vanilla); 200 is used here so "
        "the difference is unmistakable.",
    ],
    steps=[
        Step(
            "Start New Game, connect, spawn in Dark Agon Temple, and stand still without shooting.",
            "Energy drops about twice as fast as in the `off` variant run (roughly double the ~6 HP/s "
            "dark ambience tick), and a rough 20 s stand still costs about twice the energy.",
        ),
        Step(
            "Kill Amorbis with fully charged Power Beam shots, counting shots to the kill.",
            "Amorbis dies in roughly half the shots the `off` variant run needs; its health bar drops "
            "visibly further per hit.",
        ),
        Step(
            "Get hit by Amorbis (sonar pulse / contact) in both runs.",
            "Its hits take roughly double the energy in this run.",
        ),
        Step(
            "Fire one missile and one Power Bomb at Amorbis (or a wall) in each run.",
            "Missiles and bombs are scaled too, not just beams.",
        ),
    ],
    variants={
        "off": Variant(
            config_sha256="40e89fd2ce430ea6a1ff8fba6aef655c793d0e4fd8fbe6f9468dfc734936c2de",
            options={
                "incoming_damage_multiplier": 100,
                "outgoing_damage_multiplier": 100,
            },
            notes=["This is the vanilla-feel A/B half: normal tick rate and vanilla Amorbis shot count."],
        ),
    },
    pass_criteria=[
        "Incoming dark ambience damage ticks ~2x at `incoming_damage_multiplier: 200`.",
        "Amorbis takes ~2x damage per shot and dies in ~half the shots.",
        "Missiles and bombs scale like the beams.",
        "The `off` variant matches vanilla rates in the same route.",
        "No crash, no client traceback.",
    ],
    on_failure=[
        "`client/damage_multiplier_patch.py` (the two caves: ApplyLocalDamage hook, ApplyDoubleDamage hook)",
        "`client/versions.py::DamageMultiplierAddresses` (ApplyLocalDamage hook NTSC 0x8003DA14 / PAL 0x8003DB64; ApplyDoubleDamage epilogue hook NTSC 0x8018A170)",
        "`options.py::incoming_damage_multiplier` / `outgoing_damage_multiplier`",
        "`test/test_damage_multiplier_patch.py`",
    ],
)

if __name__ == "__main__":
    harness.cli(TEST)
