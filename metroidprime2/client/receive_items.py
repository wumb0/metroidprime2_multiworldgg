"""Pure item-receipt logic for Metroid Prime 2: Echoes (PLAN.md section J
deliverable 4).

Both functions here are pure (no Dolphin/AP context dependency) so they
can be unit tested directly (``test/test_client_receive.py``) and are
idempotent: ``compute_desired_capacities`` is recomputed from scratch from
the *entire* received-items list every tick, and ``plan_grants`` only ever
asks for capacity increases -- never decreases -- so calling either
function twice with the same inputs is always safe.

Generic items (anything whose OPR inventory slot isn't one of the
"counted ammo" ids below) get their capacity from ``items.ITEM_TABLE``'s
``gains``/``gains_for`` directly, so adding a new plain item to
``items.py`` works here without any change to this module. Only the ids
that need cross-item arithmetic (missile/power bomb/beam ammo capacities,
which depend on *which other items* were received, and Varia Suit/Energy
Tank, which are clamped) are special-cased.
"""

from __future__ import annotations

import logging

from .. import constants
from ..items import ITEM_TABLE, gains_for

logger = logging.getLogger(__name__)

# Item ids (OPR PlayerItemEnum inventory slots) whose desired capacity is
# NOT simply "1 if received" or "sum of gains" -- they depend on which
# *other* items were received, or are clamped to a fixed maximum. Skipped
# during the generic gains accumulation below and computed explicitly
# afterward. See PLAN.md sections F and J.
_MISSILE_ITEM = 44
_MISSILE_LAUNCHER_FLAG = 73
_POWER_BOMB_ITEM = 43
_DARK_AMMO_ITEM = 45
_LIGHT_AMMO_ITEM = 46
_ENERGY_TANK_ITEM = 42
_VARIA_ITEM = 12  # Reused by OPR as the Defense Up counter; capacity must
# always be exactly 1 (PLAN.md Context fact 31 / Risk L7).

_COUNTED_AMMO_IDS = frozenset(
    {
        _MISSILE_ITEM,
        _MISSILE_LAUNCHER_FLAG,
        _POWER_BOMB_ITEM,
        _DARK_AMMO_ITEM,
        _LIGHT_AMMO_ITEM,
        _ENERGY_TANK_ITEM,
        _VARIA_ITEM,
    }
)

_ENERGY_TANK_CAP = 14

_SEEKER_LAUNCHER = "Seeker Launcher"
_MISSILE_LAUNCHER = "Missile Launcher"
_MISSILE_EXPANSION = "Missile Expansion"
_POWER_BOMB = "Power Bomb"
_POWER_BOMB_EXPANSION = "Power Bomb Expansion"
_DARK_BEAM = "Dark Beam"
_LIGHT_BEAM = "Light Beam"
_DARK_AMMO_EXPANSION = "Dark Ammo Expansion"
_LIGHT_AMMO_EXPANSION = "Light Ammo Expansion"
_BEAM_AMMO_EXPANSION = "Beam Ammo Expansion"
_ENERGY_TANK = "Energy Tank"


def compute_desired_capacities(
    received: list[tuple[str, int]], first_non_starting_item_index: int
) -> dict[int, int]:
    """Computes the capacity every OPR inventory slot *should* have, given
    the full list of ``(item_name, sender_slot)`` pairs received so far (in
    receipt order, i.e. ``ctx.items_received`` order).

    Every received copy counts, including the starting inventory the ISO
    already grants via ``starting_items_config``: this function computes the
    *target* state, and ``plan_grants`` only emits the positive difference
    against the live inventory, so already-granted starting items yield a
    zero delta while still contributing to counted totals (a precollected
    Missile Launcher must unlock later Missile Expansions).
    ``first_non_starting_item_index`` is accepted for slot_data
    compatibility and ignored.
    """
    desired: dict[int, int] = {}
    progressive_copy_index: dict[str, int] = {}

    has_missile_launcher = False
    has_power_bomb_main = False
    seeker_launchers = 0
    missile_expansions = 0
    power_bomb_expansions = 0
    dark_beams = 0
    light_beams = 0
    dark_ammo_expansions = 0
    light_ammo_expansions = 0
    beam_ammo_expansions = 0
    energy_tanks = 0

    for item_name, _sender_slot in received:
        data = ITEM_TABLE.get(item_name)
        if data is None:
            logger.warning(f"Received unknown item {item_name!r}; ignoring.")
            continue

        if item_name == _MISSILE_LAUNCHER:
            has_missile_launcher = True
        elif item_name == _SEEKER_LAUNCHER:
            seeker_launchers += 1
        elif item_name == _MISSILE_EXPANSION:
            missile_expansions += 1
        elif item_name == _POWER_BOMB:
            has_power_bomb_main = True
        elif item_name == _POWER_BOMB_EXPANSION:
            power_bomb_expansions += 1
        elif item_name == _DARK_BEAM:
            dark_beams += 1
        elif item_name == _LIGHT_BEAM:
            light_beams += 1
        elif item_name == _DARK_AMMO_EXPANSION:
            dark_ammo_expansions += 1
        elif item_name == _LIGHT_AMMO_EXPANSION:
            light_ammo_expansions += 1
        elif item_name == _BEAM_AMMO_EXPANSION:
            beam_ammo_expansions += 1
        elif item_name == _ENERGY_TANK:
            energy_tanks += 1

        if data.progression is not None:
            copy_index = progressive_copy_index.get(item_name, 0)
            progressive_copy_index[item_name] = copy_index + 1
            gains = gains_for(item_name, copy_index)
        else:
            gains = data.gains

        for item_id, amount in gains:
            if item_id in _COUNTED_AMMO_IDS or item_id == constants.MAGIC_ITEM:
                continue
            # Idempotent "at least" rather than a running sum: a boolean
            # item's gains amount is always the same regardless of how
            # many times it's (re)computed, and a progressive item's
            # successive stages land on different ids, so this never
            # needs to combine two different amounts for the same id.
            desired[item_id] = max(desired.get(item_id, 0), amount)

    # Varia Suit capacity is always exactly 1 (it's also OPR's Defense Up
    # counter -- never grant it more).
    desired[_VARIA_ITEM] = 1

    # Energy Tank: real max is 14 regardless of how many were received.
    desired[_ENERGY_TANK_ITEM] = min(energy_tanks, _ENERGY_TANK_CAP)

    # Missile: 0 without the launcher; otherwise 5 per (launcher + each
    # Seeker Launcher + each Missile Expansion).
    desired[_MISSILE_LAUNCHER_FLAG] = 1 if has_missile_launcher else 0
    desired[_MISSILE_ITEM] = (
        5 * (1 + seeker_launchers + missile_expansions) if has_missile_launcher else 0
    )

    # Power Bomb: 0 without the main pickup; otherwise 2 + expansions.
    desired[_POWER_BOMB_ITEM] = (2 + power_bomb_expansions) if has_power_bomb_main else 0

    # Dark/Light Beam ammo: 50 per beam, 20 per matching expansion, 200 per
    # (shared) Beam Ammo Expansion.
    desired[_DARK_AMMO_ITEM] = 50 * dark_beams + 20 * dark_ammo_expansions + 200 * beam_ammo_expansions
    desired[_LIGHT_AMMO_ITEM] = 50 * light_beams + 20 * light_ammo_expansions + 200 * beam_ammo_expansions

    return desired


def plan_grants(
    desired: dict[int, int], current_inventory: dict[int, tuple[int, int]]
) -> list[tuple[int, int]]:
    """Diffs ``desired`` capacities against ``current_inventory``
    (``{item_id: (amount, capacity)}`` from
    ``EchoesInterface.read_inventory``), returning only the *positive*
    (item_id, delta) pairs to grant, in ascending item-id order.

    Capacities only ever grow: a negative delta means the game's current
    capacity is somehow ahead of what we think it should be (should not
    happen in normal play -- e.g. a stale/mismatched save) and is logged
    rather than acted on.
    """
    grants: list[tuple[int, int]] = []
    for item_id in sorted(desired):
        desired_capacity = desired[item_id]
        _current_amount, current_capacity = current_inventory.get(item_id, (0, 0))
        delta = desired_capacity - current_capacity
        if delta > 0:
            grants.append((item_id, delta))
        elif delta < 0:
            logger.warning(
                f"Item {item_id}: current capacity {current_capacity} is already above the "
                f"desired {desired_capacity}; capacities only grow, not touching it."
            )
    return grants
