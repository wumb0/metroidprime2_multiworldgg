"""Maps randovania ``prime2`` logic-database item short names to Archipelago
item state expressions.

See ``PLAN.md`` section D ("Item mapping") for the source table. Nothing
here imports randovania or MultiWorldGG framework modules; ``state`` is any
object exposing ``has(name, player) -> bool`` and ``count(name, player) ->
int`` (i.e. a ``CollectionState``, or the fake state used in
``test/test_requirements.py``).
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .db_reader import GameDatabase

# A compiled item expression is (kind, callable):
#   "bool"  -> callable(state) -> bool   (item is "present")
#   "count" -> callable(state) -> int    (item quantity owned)
#   "const" -> callable(state) -> int    (fixed value, state ignored;
#                                          state may be None when folding)
Kind = str
Expression = Callable[[object], object]

EVENT_ITEM_PREFIX = "Event - "


def event_item_name(db: GameDatabase, short_name: str) -> str:
    """The AP event-item name placed at an event node for ``short_name``."""
    return EVENT_ITEM_PREFIX + db.events[short_name]


# --------------------------------------------------------------------------
# Simple 1:1 boolean items: DB short_name -> AP item name.
#
# These are items whose logic-DB presence check is exactly
# ``state.has(<AP item name>, player)`` with no progressive-alternative or
# counted-ammo logic layered on top. Exported for the vanilla-placement test
# (which needs to know, given a DB short name, which single AP item to place
# at the corresponding vanilla pickup location).
#
# Deliberately excluded: DarkSuit/LightSuit/Grapple/ScrewAttack (progressive
# alternatives), Missile/PowerBomb/DarkAmmo/LightAmmo/EnergyTank (counted
# expressions), and the constant-0 items (Percent, Multiworld, ETM,
# ObjectCount, Health, Temporary1, Temporary2, ChargeCombo).
# --------------------------------------------------------------------------
DB_ITEM_TO_AP_ITEM: dict[str, str] = {
    "Power": "Power Beam",
    "Charge": "Charge Beam",
    "Combat": "Combat Visor",
    "Scan": "Scan Visor",
    "Varia": "Varia Suit",
    "MorphBall": "Morph Ball",
    "Dark": "Dark Beam",
    "Light": "Light Beam",
    "Annihilator": "Annihilator Beam",
    "Supers": "Super Missile",
    "Darkburst": "Darkburst",
    "Sunburst": "Sunburst",
    "SonicBoom": "Sonic Boom",
    "DarkVisor": "Dark Visor",
    "Echo": "Echo Visor",
    "Boost": "Boost Ball",
    "Spider": "Spider Ball",
    "Bombs": "Morph Ball Bomb",
    "SpaceJump": "Space Jump Boots",
    "Gravity": "Gravity Boost",
    "Seekers": "Seeker Launcher",
    "Violet": "Violet Translator",
    "Amber": "Amber Translator",
    "Emerald": "Emerald Translator",
    "Cobalt": "Cobalt Translator",
    "MissileLauncher": "Missile Launcher",
    "TempleKey1": "Sky Temple Key 1",
    "TempleKey2": "Sky Temple Key 2",
    "TempleKey3": "Sky Temple Key 3",
    "TempleKey4": "Sky Temple Key 4",
    "TempleKey5": "Sky Temple Key 5",
    "TempleKey6": "Sky Temple Key 6",
    "TempleKey7": "Sky Temple Key 7",
    "TempleKey8": "Sky Temple Key 8",
    "TempleKey9": "Sky Temple Key 9",
    "AgonKey1": "Dark Agon Key 1",
    "AgonKey2": "Dark Agon Key 2",
    "AgonKey3": "Dark Agon Key 3",
    "TorvusKey1": "Dark Torvus Key 1",
    "TorvusKey2": "Dark Torvus Key 2",
    "TorvusKey3": "Dark Torvus Key 3",
    "HiveKey1": "Ing Hive Key 1",
    "HiveKey2": "Ing Hive Key 2",
    "HiveKey3": "Ing Hive Key 3",
    "DoubleDamage": "Double Damage",
    "UnlimitedMissiles": "Unlimited Missiles",
    "UnlimitedBeamAmmo": "Unlimited Beam Ammo",
    "CannonBall": "Cannon Ball",
}

# Items whose logic value is always 0 (never required by any real template;
# asserted, not enforced, at the DB level).
CONST_ZERO_ITEMS: frozenset[str] = frozenset(
    {
        "Percent",
        "Multiworld",
        "ETM",
        "ObjectCount",
        "Health",
        "Temporary1",
        "Temporary2",
        "ChargeCombo",
    }
)


def expression(
    short_name: str, player: int, missile_expansions_unlock_launcher: bool = False
) -> tuple[Kind, Expression]:
    """Return ``(kind, callable)`` for a DB item short_name.

    ``missile_expansions_unlock_launcher`` mirrors the
    ``missile_expansions_unlock_launcher`` option (PLAN.md section M): when
    set, it changes the ``Missile`` expression below so that owning at
    least one Missile Expansion is enough to count missile capacity, even
    without the Missile Launcher itself. This is the generation-time half
    of that option; ``client/receive_items.py``'s
    ``compute_desired_capacities`` implements the identical rule for the
    in-game grant, and the two must be kept in sync.

    Raises ``KeyError`` for unknown short names.
    """
    if short_name in DB_ITEM_TO_AP_ITEM:
        ap_name = DB_ITEM_TO_AP_ITEM[short_name]
        return ("bool", lambda state, _n=ap_name, _p=player: state.has(_n, _p))

    if short_name == "DarkSuit":
        return (
            "bool",
            lambda state, _p=player: state.has("Dark Suit", _p)
            or state.count("Progressive Suit", _p) >= 1,
        )
    if short_name == "LightSuit":
        return (
            "bool",
            lambda state, _p=player: state.has("Light Suit", _p)
            or state.count("Progressive Suit", _p) >= 2,
        )
    if short_name == "Grapple":
        return (
            "bool",
            lambda state, _p=player: state.has("Grapple Beam", _p)
            or state.count("Progressive Grapple", _p) >= 1,
        )
    if short_name == "ScrewAttack":
        return (
            "bool",
            lambda state, _p=player: state.has("Screw Attack", _p)
            or state.count("Progressive Grapple", _p) >= 2,
        )

    if short_name == "Missile":
        def _missile(state, _p=player, _unlock=missile_expansions_unlock_launcher):
            launcher = 1 if state.has("Missile Launcher", _p) else 0
            expansions = state.count("Missile Expansion", _p)
            if not launcher and not (_unlock and expansions):
                return 0
            return 5 * (launcher + state.count("Seeker Launcher", _p) + expansions)

        return ("count", _missile)

    if short_name == "PowerBomb":
        def _power_bomb(state, _p=player):
            if not state.has("Power Bomb", _p):
                return 0
            return 2 + state.count("Power Bomb Expansion", _p)

        return ("count", _power_bomb)

    if short_name == "DarkAmmo":
        return (
            "count",
            lambda state, _p=player: (
                50 * state.count("Dark Beam", _p)
                + 20 * state.count("Dark Ammo Expansion", _p)
                + 200 * state.count("Beam Ammo Expansion", _p)
            ),
        )
    if short_name == "LightAmmo":
        return (
            "count",
            lambda state, _p=player: (
                50 * state.count("Light Beam", _p)
                + 20 * state.count("Light Ammo Expansion", _p)
                + 200 * state.count("Beam Ammo Expansion", _p)
            ),
        )

    if short_name == "EnergyTank":
        return ("count", lambda state, _p=player: state.count("Energy Tank", _p))

    if short_name in CONST_ZERO_ITEMS:
        return ("const", lambda state: 0)

    raise KeyError(short_name)
