"""Static constants for the Metroid Prime 2: Echoes world.

Values here are pulled from the randovania ``prime2`` logic database
(schema_version 34) and from open-prime-rando; see ``PLAN.md`` sections A
and D for provenance. Nothing in this module depends on randovania or
open-prime-rando being importable at runtime.
"""

from __future__ import annotations

import uuid
from typing import Any

GAME_NAME = "Metroid Prime 2: Echoes"

# Fixed namespace for uuid5(NAMESPACE_UUID, f"{seed_name}/{player}") world_uuid
# generation (PLAN.md sections H and K, __init__.py generate_early /
# fill_slot_data). Deterministic and world-specific so it never collides
# with another world's uuid5 namespace.
NAMESPACE_UUID = uuid.uuid5(uuid.NAMESPACE_DNS, "metroidprime2.multiworldgg")

# --- id ranges -------------------------------------------------------------
# Prime 1 uses 5031000/5031100; Echoes gets its own disjoint range.
ITEM_ID_BASE = 5033000
LOCATION_ID_BASE = 5033200

# The multiworld "magic" counter item (randovania short_name "Multiworld",
# item_id 74 == PersistentCounter8). Every in-ISO pickup grants only this
# item, with amount == pickup_index + 1; the client is the sole source of
# truth for what a player actually owns.
MAGIC_ITEM = 74

# --- asset ids ---------------------------------------------------------------
# Temple Grounds region MLVL and its Landing Site / Credits area MREAs.
TEMPLE_GROUNDS_MLVL = 1006255871
LANDING_SITE_MREA = 1655756413
CREDITS_MREA = 1393588666
# Sky Temple Grounds is a "dark" region (no MLVL of its own; it shares
# Temple Grounds' MLVL via extra.associated_region). Sky Temple Gateway is
# the area whose "Event - Dark Samus 3 and 4" node is the real victory
# condition node (the Temple Grounds/Credits copy of that node is dangling).
SKY_TEMPLE_GATEWAY_MREA = 2278776548

# The 5 distinct MLVL ids across all 10 regions (5 light regions carry an
# asset_id; the 5 dark regions resolve to their light counterpart via
# extra.associated_region). Frozen copy of OPR's NAME_TO_ID_MLVL values.
REGION_MLVL_IDS = frozenset(
    {
        0x3BFA3EFF,  # Temple Grounds / Sky Temple Grounds -> 1006255871
        0x863FCD72,  # Great Temple / Sky Temple -> 2252328306
        0x42B935E4,  # Agon Wastes / Dark Agon Wastes -> 1119434212
        0x3DFD2249,  # Torvus Bog / Dark Torvus Bog -> 1039999561
        0x1BAA96C2,  # Sanctuary Fortress / Ing Hive -> 464164546
    }
)

# --- pre-granted events ------------------------------------------------------
# Events considered always-true by the new (patch_iso) OPR patcher: it does
# not model these gates as obstacles in the shipped ISO, so the logic
# compiler must treat them as pre-collected rather than requiring the
# player to reach the event node that would normally grant them.
PREGRANTED_EVENTS = frozenset(
    {
        "Event2",
        "Event4",
        "Event71",
        "Event78",
        "Event73",
        "Event75",
    }
)

# --- static resource contexts ------------------------------------------------
# misc resources: fixed for v1 (no room/door rando, no drop rando; vanilla
# beam/visor/movement item placements assumed since those items are not
# entrance-randomized in v1).
STATIC_MISC = {
    "SafeZone": 1,
    "DarkWaterJump": 0,
    "RoomRando": 0,
    "DoorRando": 0,
    "Drops": 0,
    # Investigated (see PLAN.md task notes / logic/requirements.py's
    # module docstring for the full trail): randovania's own bootstrap
    # (randovania/games/prime2/generator/bootstrap.py) only enables this
    # resource when `configuration.teleporters.is_vanilla` -- but that
    # bootstrap targets randovania's OWN (non-OPR) patcher. This world's
    # ISO is ALWAYS produced by open-prime-rando's `patch_iso`, whose
    # `register_all` (open_prime_rando/echoes/specific_area_patches/
    # rebalance_patches.py) applies `temple_sanctuary_emerald_gate`
    # ("Keep the Emerald gate active from the beginning") UNCONDITIONALLY
    # for every seed -- no option/config check gates it at all. Randovania's
    # own dedicated OPR-paired game variant (games/prime2_opr, whose logic
    # database is built to model OPR's actual room layout) confirms this:
    # its Great Temple.json has NO "VanillaGreatTempleEmeraldGate"-gated
    # requirement here at all -- "Temple Sanctuary/Door to Transport A
    # Access" connects unconditionally to a node that doesn't even exist
    # under this name in the stable `prime2` DB this world vendors, and it
    # has no "Event - Transport A Gate Removal" node either. That's strong
    # evidence the stable DB's Event76/Event91/VanillaGreatTempleEmeraldGate
    # construct on this door models a DIFFERENT (non-OPR) patcher's room
    # behavior, not OPR's -- and that OPR's actual, always-applied behavior
    # ("gate active from the beginning") is exactly what leaving this
    # resource pinned at 1 already encodes: the "Room Center" edge's `(not
    # Event76 AND VanillaGreatTempleEmeraldGate) OR Event91` becomes freely
    # true from the start (Event76 hasn't fired yet), matching an
    # always-open gate. Toggling this to 0 for elevator_rando/
    # teleporter_rando (the reading PLAN.md's task notes suggested as
    # "safest") would make logic wrongly demand Event91 for a door OPR's
    # patcher keeps permanently open regardless of those options -- overly
    # strict, not unsafe, but not what the real ISO does either. Left
    # pinned at 1 for every option combination; NOT threaded through
    # StaticContext. If open-prime-rando ever makes this patch conditional,
    # revisit both this comment and requirements.py's StaticContext.misc
    # plumbing.
    "VanillaGreatTempleEmeraldGate": 1,
    "VanillaDarkBeam": 1,
    "VanillaLightBeam": 1,
    "VanillaSeekers": 1,
    "VanillaEcho": 1,
    "VanillaSA": 1,
    "VanillaGravity": 1,
    "VanillaBoost": 1,
    "VanillaSpider": 1,
    "VanillaDarkVisor": 1,
}

# version resources: NTSC-U and PAL ISOs only (OPR limitation); v1 always
# targets NTSC logic (both versions patch identically for logic purposes).
STATIC_VERSIONS = {
    "NTSC": 1,
    "PAL": 0,
    "Japan": 0,
    "Trilogy": 0,
}

# Items pushed via push_precollected regardless of options (the vanilla
# starting inventory at Landing Site / Save Station).
DEFAULT_STARTING_ITEMS = (
    "Power Beam",
    "Charge Beam",
    "Combat Visor",
    "Scan Visor",
    "Varia Suit",
    "Morph Ball",
)

# --- translator gate holo/glow instance overrides -----------------------------
# 9 of the 17 configurable_node translator gates have vanilla rooms where
# open-prime-rando's default name-based lookups ("Gate Holo 1"/"Glow For Holo
# 1"/etc, see open_prime_rando.echoes.translator_gates.TranslatorGateModification)
# are ambiguous -- e.g. Temple Grounds/Meeting Grounds' gate has two objects
# both literally named "Glow For Holo 1", so OPR's name lookup raises
# MultipleInstances instead of picking one. Randovania's own prime2_opr game
# definition (randovania/games/prime2_opr/logic_database, NOT the prime2
# logic_database this world's data/ is vendored from -- prime2 has no
# equivalent field) carries a per-gate "gate_instances" override with
# disambiguating numeric instance ids for exactly these 9 gates; this table
# is that same data, hand-copied since our vendored DB doesn't have it.
# Keyed by Node.gate_index (patch_data.py's _translator_gate_modification
# merges the matching entry, if any, into the patcher-format dict -- same
# shape/effect as randovania's exporter's own
# ``**node.extra.get("gate_instances", {})`` spread).
TRANSLATOR_GATE_INSTANCE_OVERRIDES: dict[int, dict[str, Any]] = {
    1: {"holo1": {"hologram": "Gate Holo 1", "glow": 262226}},  # Temple Grounds/Meeting Grounds
    4: {"holo1": {"hologram": "Gate Holo 1", "glow": 917738}},  # Temple Grounds/Path of Eyes
    7: {  # Great Temple/Temple Sanctuary, Transport B Translator Gate
        "holo1": {"hologram": 131438, "glow": 131442},
        "holo2": {"hologram": 131441, "glow": 131444},
        "conditional_relay": 131460,
    },
    8: {  # Great Temple/Temple Sanctuary, Transport C Translator Gate
        "holo1": {"hologram": 131426, "glow": 131431},
        "holo2": {"hologram": 131408, "glow": 131415},
        "conditional_relay": 131459,
    },
    9: {  # Great Temple/Temple Sanctuary, Transport A Translator Gate
        "holo1": {"hologram": 131268, "glow": 131323},
        "holo2": {"hologram": 131273, "glow": 131237},
        "conditional_relay": 131458,
    },
    10: {"holo1": {"hologram": "Gate Holo 1", "glow": 131708}},  # Agon Wastes/Mining Plaza
    11: {"holo1": {"hologram": "Gate Holo 1", "glow": 655988}},  # Agon Wastes/Mining Station A
    13: {"holo1": {"hologram": "Gate Holo 1", "glow": 1770227}},  # Torvus Bog/Torvus Temple, Translator Gate
    14: {  # Torvus Bog/Torvus Temple, Elevator Translator Scan
        "holo1": {"hologram": "Lore Hologram", "glow": 1769711},
        "holo2": {"hologram": "Lore Hologram", "glow": 1769711},
        "conditional_relay": "Does Player Have Correct Translator?",
    },
}

# --- OPR pickup models -------------------------------------------------------
# Keys of open_prime_rando.echoes.pickups.model_database.PICKUP_MODELS
# (open-prime-rando v0.20.1-20), frozen so patch_data.py (M2) can validate
# model names without importing OPR at runtime.
OPR_MODEL_NAMES = frozenset(
    {
        "PowerBeam",
        "ChargeBeam",
        "DarkBeam",
        "LightBeam",
        "AnnihilatorBeam",
        "SuperMissile",
        "Darkburst",
        "Sunburst",
        "SonicBoom",
        "CombatVisor",
        "ScanVisor",
        "DarkVisor",
        "EchoVisor",
        "VariaSuit",
        "DarkSuit",
        "LightSuit",
        "MassiveDamage",
        "DefenseUp",
        "MorphBall",
        "BoostBall",
        "CannonBall",
        "SpiderBall",
        "MorphBallBomb",
        "PowerBomb",
        "PowerBombExpansion",
        "MissileExpansion",
        "MissileExpansionLarge",
        "MissileExpansionPrime1",
        "MissileLauncher",
        "SeekerLauncher",
        "UnlimitedMissiles",
        "GrappleBeam",
        "SpaceJumpBoots",
        "GravityBoost",
        "ScrewAttack",
        "EnergyTransferModule",
        "BeamAmmoExpansion",
        "DarkBeamAmmoExpansion",
        "LightBeamAmmoExpansion",
        "UnlimitedBeamAmmo",
        "VioletTranslator",
        "AmberTranslator",
        "EmeraldTranslator",
        "CobaltTranslator",
        "CrimsonTranslator",
        "ObsidianTranslator",
        "PearlTranslator",
        "EnergyTank",
        "EnergyTankSmall",
        "DarkTempleKey",
        "SkyTempleKey",
    }
)
