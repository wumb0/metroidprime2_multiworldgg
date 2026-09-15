"""Item table for Metroid Prime 2: Echoes.

Built from ``PLAN.md`` section F. ``ITEM_TABLE`` positions are append-only:
each entry's AP item id is ``constants.ITEM_ID_BASE + position`` where
``position`` is the entry's (fixed) index in the table below.

``gains`` entries are ``(PlayerItemEnum id, amount)`` pairs -- the OPR/DOL
inventory slot index and the amount to grant -- as consumed by
``client/receive_items.py`` (M3) and ``patch_data.py`` (M2). They have
nothing to do with the randovania logic-database item ids used by
``logic/item_mapping.py``.

Note on ``default_pool_count``: taken verbatim, per item, from the PLAN.md
F table (using the *default* option values: ``progressive_suit=True``,
``progressive_grapple=False``, ``sky_temple_keys=9``). Summed across every
row this totals 118, one short of the 119 pickup locations -- the suit
trio (Dark Suit/Light Suit/Progressive Suit) and the grapple trio
(Grapple Beam/Screw Attack/Progressive Grapple) both always contribute
exactly 2 to the total regardless of which of progressive_suit/
progressive_grapple is active, so no combination of those toggles can
close the gap; the plan's own summary arithmetic ("26 majors + 14 tanks +
61 expansions + 9 dark keys + 9 STK = 119") appears to have a one-item
rounding slip (26 vs. the table's actual 25). This is harmless: creating
the item pool is designed (PLAN.md section F / item_pool.py) to pad any
shortfall against the location count with filler (Missile Expansion), so
the single extra filler item that appears under fully-default options is
expected behavior, not a bug. See test/test_items_locations.py for the
exact total this module produces.
"""

from __future__ import annotations

from dataclasses import dataclass

from BaseClasses import Item, ItemClassification

from . import constants

# (id, amount) pair as granted through the OPR/DOL inventory (see
# client/receive_items.py, M3) -- NOT a randovania logic-db item id.
Gain = tuple[int, int]
Gains = tuple[Gain, ...]
# One tuple of Gains per progressive stage, in the order copies are
# received (stage 0 = first copy, stage 1 = second copy, ...).
ProgressiveStages = tuple[Gains, ...]


@dataclass(frozen=True)
class ItemData:
    name: str
    code: int
    classification: ItemClassification
    gains: Gains
    progression: ProgressiveStages | None
    model: str
    default_pool_count: int


class MetroidPrime2Item(Item):
    game = "Metroid Prime 2: Echoes"


def _entry(
    position: int,
    name: str,
    classification: ItemClassification,
    gains: Gains,
    model: str,
    default_pool_count: int,
    progression: ProgressiveStages | None = None,
) -> ItemData:
    return ItemData(
        name=name,
        code=constants.ITEM_ID_BASE + position,
        classification=classification,
        gains=gains,
        progression=progression,
        model=model,
        default_pool_count=default_pool_count,
    )


PROG = ItemClassification.progression
PROG_SKIP = ItemClassification.progression_skip_balancing
USEFUL = ItemClassification.useful
FILLER = ItemClassification.filler

# --------------------------------------------------------------------------
# ITEM_TABLE -- append-only; position in this tuple IS the id offset.
# --------------------------------------------------------------------------

_ROWS: tuple[ItemData, ...] = (
    _entry(0, "Power Beam", PROG, ((0, 1),), "PowerBeam", 0),
    _entry(1, "Charge Beam", PROG, ((22, 1),), "ChargeBeam", 0),
    _entry(2, "Dark Beam", PROG, ((1, 1), (45, 50)), "DarkBeam", 1),
    _entry(3, "Light Beam", PROG, ((2, 1), (46, 50)), "LightBeam", 1),
    _entry(4, "Annihilator Beam", PROG, ((3, 1),), "AnnihilatorBeam", 1),
    _entry(5, "Super Missile", PROG, ((4, 1),), "SuperMissile", 1),
    _entry(6, "Darkburst", PROG, ((5, 1),), "Darkburst", 1),
    _entry(7, "Sunburst", PROG, ((6, 1),), "Sunburst", 1),
    _entry(8, "Sonic Boom", PROG, ((7, 1),), "SonicBoom", 1),
    _entry(9, "Combat Visor", PROG, ((8, 1),), "CombatVisor", 0),
    _entry(10, "Scan Visor", PROG, ((9, 1),), "ScanVisor", 0),
    _entry(11, "Dark Visor", PROG, ((10, 1),), "DarkVisor", 1),
    _entry(12, "Echo Visor", PROG, ((11, 1),), "EchoVisor", 1),
    # default_pool_count=0: always a starting item (constants.
    # DEFAULT_STARTING_ITEMS), never actually placed as a pickup, so its
    # "VariaSuit" model is never rendered in practice -- see the
    # "Progressive Suit" entry below for why that model crashes the game
    # if a location's item ever does use it.
    _entry(13, "Varia Suit", PROG, ((12, 1),), "VariaSuit", 0),
    # Dark Suit / Light Suit / Progressive Suit: default_pool_count below
    # assumes the default progressive_suit=True (DefaultOnToggle); when
    # progressive_suit is off, item_pool.py puts Dark Suit/Light Suit (1
    # each) in the pool instead of Progressive Suit (2).
    _entry(14, "Dark Suit", PROG, ((13, 1),), "DarkSuit", 0),
    _entry(15, "Light Suit", PROG, ((14, 1),), "LightSuit", 0),
    _entry(
        16,
        "Progressive Suit",
        PROG,
        ((13, 1),),  # unused directly; see `progression` stages
        # "DarkSuit", not "VariaSuit" -- deliberate. Placing a pickup with
        # the "VariaSuit" model (open_prime_rando.echoes.pickups.
        # model_database.PICKUP_MODELS) anywhere other than its own
        # vanilla location crashes the game on room load, before the
        # player even reaches the pickup. Confirmed empirically: swapping
        # just this model string to "DarkSuit" (itself a normal,
        # frequently-relocated suit model) with the exact same seed/
        # location made the crash disappear. Root cause not identified
        # further (likely an open-prime-rando bug in that specific model
        # entry) -- if open-prime-rando ever fixes this, "VariaSuit" would
        # be the more thematically fitting model for a suit that isn't
        # exclusively Dark or Light.
        "DarkSuit",
        2,
        progression=(((13, 1),), ((14, 1),)),
    ),
    _entry(17, "Morph Ball", PROG, ((15, 1),), "MorphBall", 0),
    _entry(18, "Morph Ball Bomb", PROG, ((18, 1),), "MorphBallBomb", 1),
    _entry(19, "Boost Ball", PROG, ((16, 1),), "BoostBall", 1),
    _entry(20, "Spider Ball", PROG, ((17, 1),), "SpiderBall", 1),
    _entry(21, "Power Bomb", PROG, ((43, 2),), "PowerBomb", 1),
    _entry(22, "Space Jump Boots", PROG, ((24, 1),), "SpaceJumpBoots", 1),
    _entry(23, "Gravity Boost", PROG, ((25, 1),), "GravityBoost", 1),
    # Grapple Beam / Screw Attack / Progressive Grapple: default_pool_count
    # below assumes the default progressive_grapple=False (Toggle, off).
    _entry(24, "Grapple Beam", PROG, ((23, 1),), "GrappleBeam", 1),
    _entry(25, "Screw Attack", PROG, ((27, 1),), "ScrewAttack", 1),
    _entry(
        26,
        "Progressive Grapple",
        PROG,
        ((23, 1),),  # unused directly; see `progression` stages
        "GrappleBeam",
        0,
        progression=(((23, 1),), ((27, 1),)),
    ),
    _entry(27, "Missile Launcher", PROG, ((73, 1), (44, 5)), "MissileLauncher", 1),
    _entry(28, "Seeker Launcher", PROG, ((26, 1), (44, 5)), "SeekerLauncher", 1),
    _entry(29, "Violet Translator", PROG, ((97, 1),), "VioletTranslator", 1),
    _entry(30, "Amber Translator", PROG, ((98, 1),), "AmberTranslator", 1),
    _entry(31, "Emerald Translator", PROG, ((99, 1),), "EmeraldTranslator", 1),
    _entry(32, "Cobalt Translator", PROG, ((100, 1),), "CobaltTranslator", 1),
    _entry(33, "Energy Tank", PROG, ((42, 1),), "EnergyTank", 14),
    _entry(34, "Missile Expansion", PROG_SKIP, ((44, 5),), "MissileExpansion", 33),
    _entry(35, "Power Bomb Expansion", PROG_SKIP, ((43, 1),), "PowerBombExpansion", 8),
    # Dark/Light Ammo Expansion vs. Beam Ammo Expansion are mutually
    # exclusive alternatives selected by the `split_beam_ammo` option (see
    # item_pool.py's `_pool_count_for`) -- Randovania's own "Split Beam
    # Ammo Expansions" toggle. Both economies total 200 Dark + 200 Light
    # ammo across 20 pickups; only the split changes (10+10 expansions of
    # 20 each vs. 20 unified expansions of 10+10 each). Their equivalent
    # `logic/item_mapping.py` DarkAmmo/LightAmmo multipliers must stay in
    # sync with the per-pickup amounts here.
    _entry(36, "Dark Ammo Expansion", PROG_SKIP, ((45, 20),), "DarkBeamAmmoExpansion", 10),
    _entry(37, "Light Ammo Expansion", PROG_SKIP, ((46, 20),), "LightBeamAmmoExpansion", 10),
    _entry(38, "Beam Ammo Expansion", PROG_SKIP, ((45, 10), (46, 10)), "BeamAmmoExpansion", 0),
    # Sky Temple Keys 1-9 (positions 39-47). default_pool_count=1 assumes
    # the default sky_temple_keys=9 (all 9 keys in the pool); item_pool.py
    # overrides actual placement/precollection per the configured STK mode.
    _entry(39, "Sky Temple Key 1", PROG, ((29, 1),), "SkyTempleKey", 1),
    _entry(40, "Sky Temple Key 2", PROG, ((30, 1),), "SkyTempleKey", 1),
    _entry(41, "Sky Temple Key 3", PROG, ((31, 1),), "SkyTempleKey", 1),
    _entry(42, "Sky Temple Key 4", PROG, ((101, 1),), "SkyTempleKey", 1),
    _entry(43, "Sky Temple Key 5", PROG, ((102, 1),), "SkyTempleKey", 1),
    _entry(44, "Sky Temple Key 6", PROG, ((103, 1),), "SkyTempleKey", 1),
    _entry(45, "Sky Temple Key 7", PROG, ((104, 1),), "SkyTempleKey", 1),
    _entry(46, "Sky Temple Key 8", PROG, ((105, 1),), "SkyTempleKey", 1),
    _entry(47, "Sky Temple Key 9", PROG, ((106, 1),), "SkyTempleKey", 1),
    _entry(48, "Dark Agon Key 1", PROG, ((32, 1),), "DarkTempleKey", 1),
    _entry(49, "Dark Agon Key 2", PROG, ((33, 1),), "DarkTempleKey", 1),
    _entry(50, "Dark Agon Key 3", PROG, ((34, 1),), "DarkTempleKey", 1),
    _entry(51, "Dark Torvus Key 1", PROG, ((35, 1),), "DarkTempleKey", 1),
    _entry(52, "Dark Torvus Key 2", PROG, ((36, 1),), "DarkTempleKey", 1),
    _entry(53, "Dark Torvus Key 3", PROG, ((37, 1),), "DarkTempleKey", 1),
    _entry(54, "Ing Hive Key 1", PROG, ((38, 1),), "DarkTempleKey", 1),
    _entry(55, "Ing Hive Key 2", PROG, ((39, 1),), "DarkTempleKey", 1),
    _entry(56, "Ing Hive Key 3", PROG, ((40, 1),), "DarkTempleKey", 1),
    _entry(57, "Double Damage", USEFUL, ((58, 1),), "MassiveDamage", 0),
    _entry(58, "Unlimited Missiles", USEFUL, ((81, 1),), "UnlimitedMissiles", 0),
    _entry(59, "Unlimited Beam Ammo", USEFUL, ((82, 1),), "UnlimitedBeamAmmo", 0),
    _entry(60, "Cannon Ball", FILLER, ((96, 1),), "CannonBall", 0),
)

ITEM_TABLE: dict[str, ItemData] = {item.name: item for item in _ROWS}
assert len(ITEM_TABLE) == len(_ROWS), "duplicate item name in ITEM_TABLE"

item_name_to_id: dict[str, int] = {item.name: item.code for item in _ROWS}

# Every model referenced by an item must be a real OPR pickup model name.
for _item in _ROWS:
    assert _item.model in constants.OPR_MODEL_NAMES, (
        f"{_item.name}: model {_item.model!r} not in constants.OPR_MODEL_NAMES"
    )
del _item

# --------------------------------------------------------------------------
# Item groups
# --------------------------------------------------------------------------

ITEM_GROUPS: dict[str, set[str]] = {
    "Sky Temple Keys": {f"Sky Temple Key {n}" for n in range(1, 10)},
    "Dark Temple Keys": {
        f"{temple} Key {n}"
        for temple in ("Dark Agon", "Dark Torvus", "Ing Hive")
        for n in range(1, 4)
    },
    "Beams": {
        "Power Beam",
        "Dark Beam",
        "Light Beam",
        "Annihilator Beam",
        "Super Missile",
        "Darkburst",
        "Sunburst",
        "Sonic Boom",
        "Charge Beam",
    },
    "Visors": {"Combat Visor", "Scan Visor", "Dark Visor", "Echo Visor"},
    "Suits": {"Varia Suit", "Dark Suit", "Light Suit", "Progressive Suit"},
    "Translators": {
        "Violet Translator",
        "Amber Translator",
        "Emerald Translator",
        "Cobalt Translator",
    },
    "Expansions": {
        "Missile Expansion",
        "Power Bomb Expansion",
        "Dark Ammo Expansion",
        "Light Ammo Expansion",
        "Beam Ammo Expansion",
        "Energy Tank",
    },
}

# --------------------------------------------------------------------------
# Progressive item stage mapping (item name -> vanilla-equivalent stage
# names, in the order copies are received).
# --------------------------------------------------------------------------

PROGRESSIVE_ITEMS: dict[str, list[str]] = {
    "Progressive Suit": ["Dark Suit", "Light Suit"],
    "Progressive Grapple": ["Grapple Beam", "Screw Attack"],
}


def gains_for(item_name: str, copy_index: int = 0) -> Gains:
    """(id, amount) pairs to grant for one copy of ``item_name``.

    ``copy_index`` (0-based) selects the progressive stage for
    progressive items (0 = first copy received, 1 = second, ...); it is
    ignored for non-progressive items, which always grant their full
    ``gains``.
    """
    data = ITEM_TABLE[item_name]
    if data.progression is not None:
        stages = data.progression
        index = min(copy_index, len(stages) - 1)
        return stages[index]
    return data.gains
