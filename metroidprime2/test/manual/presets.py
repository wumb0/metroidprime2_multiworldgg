"""Reusable option / start-inventory / plando bundles for the manual tests
(MANUAL_TEST_PLAN.md section 3.4).
"""

from __future__ import annotations

from typing import Any

from ...items import ITEM_TABLE
from .harness import SlotSpec

# --------------------------------------------------------------------------
# ALL_ITEMS_START
# --------------------------------------------------------------------------


def all_items_start() -> dict[str, int]:
    """Every ``ITEM_TABLE`` item at "max count", derived from the table so it
    can't drift: progressive items get one copy per stage (so the second
    copy lands on the second stage), everything else gets at least one copy
    (items with ``default_pool_count == 0`` are still granted -- e.g. Power
    Beam or Double Damage -- and items the pool places many of get that
    many).

    Uses ``start_inventory`` (not ``start_inventory_from_pool``), so every
    location keeps holding a real item while the connect-time grant path is
    still exercised against a fully-populated inventory.
    """
    result: dict[str, int] = {}
    for name, data in ITEM_TABLE.items():
        if data.progression is not None:
            count = len(data.progression)
        else:
            count = max(1, data.default_pool_count)
        result[name] = count
    return result


ALL_ITEMS_START: dict[str, int] = all_items_start()


# --------------------------------------------------------------------------
# GOD_MODE
# --------------------------------------------------------------------------

GOD_MODE_OPTIONS: dict[str, Any] = {
    "energy_per_tank": 500,
    "defense_up_damage_reduction": 90,
    "double_damage_multiplier": 500,
}

GOD_MODE_START_INVENTORY: dict[str, int] = {
    "Energy Tank": 14,
    "Double Damage": 1,
}


# --------------------------------------------------------------------------
# NO_RANDO
# --------------------------------------------------------------------------

NO_RANDO_OPTIONS: dict[str, Any] = {
    "door_lock_rando": False,
    "elevator_rando": False,
    "portal_rando": False,
    "translator_gate_rando": "vanilla",
}


# --------------------------------------------------------------------------
# FAST_RETRY
# --------------------------------------------------------------------------

FAST_RETRY_OPTIONS: dict[str, Any] = {
    "warp_to_start": True,
}


# --------------------------------------------------------------------------
# MAP
# --------------------------------------------------------------------------

# Every manual test is easier to navigate with the full map visible: item
# dots at every location from the start, and room names shown before the
# room has been visited.
MAP_OPTIONS: dict[str, Any] = {
    "map_visibility": "full_map_and_items",
    "unvisited_room_names": True,
}


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------


def merge(*option_dicts: dict[str, Any]) -> dict[str, Any]:
    """Later dicts win. Small helper so a test can write
    ``merge(NO_RANDO_OPTIONS, {"starting_room": "anywhere"})``."""
    result: dict[str, Any] = {}
    for options in option_dicts:
        result.update(options)
    return result


def merge_inventory(*inventory_dicts: dict[str, int]) -> dict[str, int]:
    result: dict[str, int] = {}
    for inventory in inventory_dicts:
        for name, count in inventory.items():
            result[name] = result.get(name, 0) + count
    return result


def filler_slot(index: int) -> SlotSpec:
    """A cheap extra player (``Clique``) for tests that only need a second
    slot to exist (cross-slot item sends, Death Link)."""
    return SlotSpec(name=f"Filler{index}", game="Clique", options={})
