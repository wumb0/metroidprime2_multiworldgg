"""Deferring the extra powerups (``extra_powerup_placement``).

Double Damage, Unlimited Missiles and Unlimited Beam Ammo are ``useful``,
not progression. The fill places every progression item first and then drops
useful and filler items into whatever locations are left, in random order,
so nothing keeps them out of the first sphere, where they can make the whole
seed easy. A world can't tell the fill "late": rules only say which items a
location accepts, and "late" isn't a property of a location until the seed is
filled, and then depends on every other world in the multiworld.

So this runs after the fill (``post_fill``), when the answer is known:

1. Order every filled, non-event location of the multiworld by logical sphere
   (``MultiWorld.get_spheres``); locations the playthrough never reaches
   count as last.
2. The last ``LATE_FRACTION[mode]`` of them (half for ``late``, a quarter
   for ``very_late``) are the late locations.
3. Each of this world's extra powerups that sits in an earlier location is
   swapped with the item of a randomly chosen late location, provided both
   locations accept the other's item (``Location.can_fill`` with the access
   check off, so every item rule, ``local_items``, exclusions and the like
   are honoured) and neither is locked.

Why a swap is safe. The late location's item moves *earlier*. If it is
progression, then at every point of the playthrough you hold at least what you
did before: the extra powerup isn't progression, so nothing depended on it,
and the swapped item's new location is reachable before its old one (a
sphere-order argument: it is in an earlier sphere, whose reachability never
depended on an item sitting in a later one). If it is not progression, nothing
changes for logic at all. Either way the seed is exactly as beatable as
before; only how soon you are handed things changes. Candidates are tried
non-progression items first, then Missile/Power Bomb/ammo expansions (the
skip-balancing progression), then other progression, then traps (which
nobody wants early).

What it can't do, and why. It can only move an extra powerup to a late
location that holds an item that may go where the powerup is. A multiworld in
which every late location holds something its own rules pin there leaves the
powerup where it was (a warning says so). Progression balancing runs after
this and only ever moves useful items later. And "late" is measured over
the *whole* multiworld: in a big one, a location late for the multiworld can
be early for this player's own game, and the other way round.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from BaseClasses import ItemClassification

from .options import ExtraPowerupPlacement

if TYPE_CHECKING:
    from BaseClasses import Item, Location

    from . import MetroidPrime2World

logger = logging.getLogger(__name__)

EXTRA_POWERUP_NAMES: frozenset[str] = frozenset({"Double Damage", "Unlimited Missiles", "Unlimited Beam Ammo"})
"""The items ``extra_powerup_placement`` moves."""

LATE_FRACTION: dict[int, float] = {
    ExtraPowerupPlacement.option_late: 0.5,
    ExtraPowerupPlacement.option_very_late: 0.75,
}
"""Share of locations, counted from the start of the playthrough, that is NOT
late."""


def _partner_preference(item: Item) -> int:
    """Lower is tried first when picking what to swap with."""
    if item.classification & ItemClassification.trap:
        return 3
    if not item.advancement:
        return 0
    if item.classification & ItemClassification.skip_balancing:
        return 1
    return 2


def sphere_order(world: MetroidPrime2World) -> dict[Location, int]:
    """Logical sphere of every filled location of the multiworld; the ones
    the playthrough never reaches are one past the last sphere."""
    order: dict[Location, int] = {}
    unreachable = 0
    for index, sphere in enumerate(world.multiworld.get_spheres()):
        if not sphere:
            unreachable = index + 1  # the empty set separates reachable from not
            continue
        for location in sphere:
            order[location] = unreachable or index
    return order


def late_locations(order: dict[Location, int], fraction: float) -> set[Location]:
    """The locations with a real item and a place on the playthrough whose
    sphere is at least that of the one ``fraction`` of the way through (ties
    on the cut sphere all count as late)."""
    ranked = sorted(
        (loc for loc in order if loc.address is not None), key=lambda loc: (order[loc], loc.player, loc.name)
    )
    if not ranked:
        return set()
    cut = order[ranked[min(len(ranked) - 1, int(len(ranked) * fraction))]]
    return {loc for loc in ranked if order[loc] >= cut}


def _swap(first: Location, second: Location) -> None:
    first.item, second.item = second.item, first.item
    first.item.location = first  # type: ignore[union-attr]
    second.item.location = second  # type: ignore[union-attr]


def _own_extras(world: MetroidPrime2World) -> list[Location]:
    return sorted(
        (
            location
            for location in world.multiworld.get_filled_locations()
            if location.address is not None
            and not location.locked
            and location.item is not None
            and location.item.player == world.player
            and location.item.name in EXTRA_POWERUP_NAMES
        ),
        key=lambda loc: loc.name,
    )


def defer_extra_powerups(world: MetroidPrime2World) -> int:
    """Moves this world's too-early extra powerups to late locations (see the
    module docstring). Returns how many it moved."""
    mode = world.options.extra_powerup_placement.value
    multiworld = world.multiworld
    if mode == ExtraPowerupPlacement.option_anywhere or hasattr(multiworld, "generation_is_fake"):
        return 0

    state = multiworld.state
    moved = 0
    given_up: set[str] = set()
    while True:
        own = [loc for loc in _own_extras(world) if loc.name not in given_up]
        if not own:
            return moved
        # Recomputed after every swap: a progression item that moved earlier
        # can pull other locations' spheres earlier too, and the safety
        # argument above needs the order as it is *now*.
        order = sphere_order(world)
        late = late_locations(order, LATE_FRACTION[mode])
        early = [loc for loc in own if loc in order and loc not in late]
        if not early:
            return moved
        location = early[0]
        extra = location.item
        assert extra is not None
        candidates = [
            other
            for other in late
            if not other.locked
            and other.item is not None
            and not (other.item.player == world.player and other.item.name in EXTRA_POWERUP_NAMES)
            and other.can_fill(state, extra, check_access=False)
            and location.can_fill(state, other.item, check_access=False)
        ]
        if not candidates:
            logger.warning(
                "%s: couldn't move %s out of %s (sphere %d) to a late location: no late location holds an "
                "item that may go there.",
                world.player_name,
                extra.name,
                location.name,
                order[location],
            )
            given_up.add(location.name)
            continue
        best = min(_partner_preference(loc.item) for loc in candidates)  # type: ignore[arg-type]
        pool = sorted(
            (loc for loc in candidates if _partner_preference(loc.item) == best),  # type: ignore[arg-type]
            key=lambda loc: (loc.player, loc.name),
        )
        target = world.random.choice(pool)
        logger.debug(
            "%s: swapping %s (%s) with %s (%s)", world.player_name, extra.name, location.name, target.item, target.name
        )
        _swap(location, target)
        moved += 1
