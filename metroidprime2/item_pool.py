"""Item pool construction for Metroid Prime 2: Echoes.

Called from ``create_items`` (in ``__init__.py``, a later milestone) after
``create_regions`` has run, so every location already exists -- this is
required because Sky Temple Key "all_bosses"/"all_guardians" modes lock
keys directly onto specific locations with ``place_locked_item``.

See ``PLAN.md`` section F ("STK modes") and section K (M1) for the exact
behavior this module must implement.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from BaseClasses import Item

from . import constants
from .items import ITEM_TABLE
from .locations import LOCATION_TABLE
from .options import SkyTempleKeysLocations

if TYPE_CHECKING:
    from . import MetroidPrime2World

STK_ITEM_NAMES: tuple[str, ...] = tuple(f"Sky Temple Key {n}" for n in range(1, 10))

# Progressive-related item names that need special pool-count handling
# depending on progressive_suit/progressive_grapple.
_SUIT_TRIO = ("Dark Suit", "Light Suit", "Progressive Suit")
_GRAPPLE_TRIO = ("Grapple Beam", "Screw Attack", "Progressive Grapple")

# Beam-ammo alternatives gated by split_beam_ammo (see items.py's entries
# 36-38): split -> 10 Dark + 10 Light Ammo Expansions; unified -> 20 Beam
# Ammo Expansions. Both total 200 Dark + 200 Light ammo across 20 pickups.
_SPLIT_AMMO_COUNT = 10
_UNIFIED_AMMO_COUNT = 20

# Items that are only in the pool when their enable_*_pickup toggle is on.
_OPTIONAL_PICKUP_OPTIONS: dict[str, str] = {
    "Unlimited Missiles": "enable_unlimited_missiles_pickup",
    "Double Damage": "enable_double_damage_pickup",
    "Unlimited Beam Ammo": "enable_unlimited_beam_ammo_pickup",
}

# Guardian pickup_index values (Amorbis, Chykka, Quadraxis), in the order
# Sky Temple Keys 1-3 are locked onto them for the "all_guardians" mode.
_GUARDIAN_PICKUP_INDICES: tuple[int, ...] = (43, 79, 115)


def _pool_count_for(item_name: str, world: MetroidPrime2World) -> int:
    """Number of copies of ``item_name`` that enter the general pool,
    given the world's progressive_suit/progressive_grapple options.
    Sky Temple Keys are handled separately by ``_apply_sky_temple_keys``.
    """
    data = ITEM_TABLE[item_name]
    progressive_suit = bool(world.options.progressive_suit)
    progressive_grapple = bool(world.options.progressive_grapple)

    if item_name in ("Dark Suit", "Light Suit"):
        return 0 if progressive_suit else 1
    if item_name == "Progressive Suit":
        return 2 if progressive_suit else 0
    if item_name in ("Grapple Beam", "Screw Attack"):
        return 0 if progressive_grapple else 1
    if item_name == "Progressive Grapple":
        return 2 if progressive_grapple else 0

    split_beam_ammo = bool(world.options.split_beam_ammo)
    if item_name in ("Dark Ammo Expansion", "Light Ammo Expansion"):
        return _SPLIT_AMMO_COUNT if split_beam_ammo else 0
    if item_name == "Beam Ammo Expansion":
        return 0 if split_beam_ammo else _UNIFIED_AMMO_COUNT

    optional_pickup = _OPTIONAL_PICKUP_OPTIONS.get(item_name)
    if optional_pickup is not None:
        return int(bool(getattr(world.options, optional_pickup)))

    return data.default_pool_count


def _boss_locations_in_pickup_order() -> list[str]:
    """The 9 boss/guardian-tagged location names, sorted by pickup_index
    (LOCATION_TABLE is already in that order)."""
    return [loc.name for loc in LOCATION_TABLE if loc.boss]


def _guardian_location_names() -> list[str]:
    return [LOCATION_TABLE[index].name for index in _GUARDIAN_PICKUP_INDICES]


def sky_temple_keys_present_count(world: MetroidPrime2World) -> int:
    """Number of Sky Temple Keys that are real, findable items under the
    current ``sky_temple_keys`` value -- the rest are precollected for
    free. This is just ``sky_temple_keys`` itself: regardless of
    ``sky_temple_keys_locations``, exactly that many keys end up locked
    onto a location or in the general pool, and the remainder (9 minus
    that many) are precollected. Shared with ``logic/regions.py`` (the Sky
    Temple Gateway gate rule) and ``patch_data.py``/``__init__.py`` (the
    physical gate patch, ``sky_temple_keys_required``) so "present" means
    the same thing in the pool, the logic, and the patched ISO.
    """
    return world.options.sky_temple_keys.value


def sky_temple_keys_required_count(world: MetroidPrime2World) -> int:
    """Resolved ``sky_temple_keys_required`` value: the option's raw value
    clamped to ``sky_temple_keys_present_count`` (a seed can never require
    more keys than could possibly be held)."""
    return min(world.options.sky_temple_keys_required.value, sky_temple_keys_present_count(world))


def _apply_sky_temple_keys(world: MetroidPrime2World, pool: list[Item]) -> None:
    """Implements the sky_temple_keys/sky_temple_keys_locations options
    (PLAN.md section F). ``n = sky_temple_keys`` keys are findable, keys
    n+1..9 are precollected (start already owned); ``generate_early``
    validates the ``sky_temple_keys_locations`` preconditions below before
    this ever runs.

    - locations=off: the ``n`` findable keys go straight into the general
      pool.
    - locations=all_bosses (requires n == 9): all 9 keys are locked, in
      order, onto the 9 boss/guardian pickup locations (sorted by
      pickup_index); none enter the general pool.
    - locations=all_guardians (requires n >= 3): keys 1-3 are locked onto
      the 3 dark temple guardian locations (pickup_index 43, 79, 115);
      keys 4..n are shuffled into the general pool like locations=off.
    """
    multiworld = world.multiworld
    world.sky_temple_key_locations = []

    n = world.options.sky_temple_keys.value
    locations_mode = world.options.sky_temple_keys_locations.value

    if locations_mode == SkyTempleKeysLocations.option_all_bosses:
        boss_locations = _boss_locations_in_pickup_order()
        assert len(boss_locations) == 9, f"expected 9 boss locations, got {len(boss_locations)}"
        for key_name, location_name in zip(STK_ITEM_NAMES, boss_locations, strict=False):
            location = world.get_location(location_name)
            location.place_locked_item(world.create_item(key_name))
            world.sky_temple_key_locations.append(location_name)
        return

    if locations_mode == SkyTempleKeysLocations.option_all_guardians:
        guardian_locations = _guardian_location_names()
        assert len(guardian_locations) == 3, f"expected 3 guardian locations, got {len(guardian_locations)}"
        for key_name, location_name in zip(STK_ITEM_NAMES[:3], guardian_locations, strict=False):
            location = world.get_location(location_name)
            location.place_locked_item(world.create_item(key_name))
            world.sky_temple_key_locations.append(location_name)
        pool.extend(world.create_item(key_name) for key_name in STK_ITEM_NAMES[3:n])
        for key_name in STK_ITEM_NAMES[n:]:
            multiworld.push_precollected(world.create_item(key_name))
        return

    # locations=off: the n findable keys go into the pool, the rest are precollected.
    pool.extend(world.create_item(key_name) for key_name in STK_ITEM_NAMES[:n])
    for key_name in STK_ITEM_NAMES[n:]:
        multiworld.push_precollected(world.create_item(key_name))


def create_item_pool(world: MetroidPrime2World) -> list[Item]:
    multiworld = world.multiworld
    player = world.player

    # (a) Vanilla starting inventory, always precollected regardless of
    # options (start_inventory copies of these are meaningless/ignored,
    # per PLAN.md).
    for name in constants.DEFAULT_STARTING_ITEMS:
        multiworld.push_precollected(world.create_item(name))

    pool: list[Item] = []

    for item_name in ITEM_TABLE:
        if item_name in STK_ITEM_NAMES:
            continue  # handled by _apply_sky_temple_keys
        count = _pool_count_for(item_name, world)
        pool.extend(world.create_item(item_name) for _ in range(count))

    # (b) Sky Temple Key modes -- may lock items directly onto locations
    # or push precollected items, in addition to (or instead of) adding
    # to `pool`.
    _apply_sky_temple_keys(world, pool)

    # (e) Pad with filler (Missile Expansion) or trim so the pool size
    # matches the number of not-yet-filled locations for this player
    # (some locations may already have a locked item from step (b)).
    unfilled_locations = [
        location for location in multiworld.get_locations(player) if location.item is None
    ]
    target = len(unfilled_locations)

    filler_name = world.get_filler_item_name()
    while len(pool) < target:
        pool.append(world.create_item(filler_name))
    # Drop surplus filler first so a full pool never loses a real item
    # (the tail of the pool is the Sky Temple Keys).
    while len(pool) > target and any(item.name == filler_name for item in pool):
        for index in range(len(pool) - 1, -1, -1):
            if pool[index].name == filler_name:
                del pool[index]
                break
    if len(pool) > target:
        pool = pool[:target]

    return pool


def starting_inventory_names(world: MetroidPrime2World) -> list[str]:
    """Names of every item this player starts with (pushed via
    push_precollected), in insertion order. Convenience for patch_data.py
    (M2) -- not required for M1."""
    return [item.name for item in world.multiworld.precollected_items[world.player]]
