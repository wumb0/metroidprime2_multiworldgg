"""DB-derived helpers shared by the manual tests (MANUAL_TEST_PLAN.md
section 3.5): door-distance BFS, the verified "independent pickup" bench,
and the per-counter-group pickup picks MT08 collects while detached.
"""

from __future__ import annotations

from collections import deque

from ...locations import LOCATION_TABLE
from ...logic.db_reader import NodeId, load_game_database

AreaKey = tuple[str, str]

# The 14 pickups within 8 doors of Landing Site used as the standard plando
# bench by MT06/MT10: all in the two light starting regions (Temple Grounds,
# Great Temple), none of them gating or perturbing another. Verified against
# the vendored DB by ``test_manual_plan.py`` (existence, distance, region).
INDEPENDENT_PICKUP_INDICES: tuple[int, ...] = (0, 1, 2, 4, 5, 6, 8, 9, 12, 13, 14, 20, 21, 22)

_DEFAULT_MAX_DISTANCE = 8


def area_key(ap_name: str) -> AreaKey:
    """``"Region/Area/Node"`` -> ``("Region", "Area")``.

    Splits with ``maxsplit=2`` because node names themselves can contain
    ``/`` (e.g. ``Sky Temple Grounds/Sky Temple Gateway/Spawn Point/Front of
    Teleporter``); region and area names never do.
    """
    region, area, *_rest = ap_name.split("/", 2)
    return region, area


def _start_area(from_area: NodeId | AreaKey | str) -> AreaKey:
    if isinstance(from_area, NodeId):
        return from_area.region, from_area.area
    if isinstance(from_area, tuple):
        return from_area
    return area_key(from_area)


def door_distance(from_area: NodeId | AreaKey | str) -> dict[AreaKey, int]:
    """BFS over ``default_connection`` docks, returning the number of doors
    between ``from_area`` and every reachable area. The start area itself is
    distance 0. Areas unreachable through vanilla connections are absent."""
    db = load_game_database()
    adjacency: dict[AreaKey, set[AreaKey]] = {}
    for node in db.all_nodes():
        if node.default_connection is None:
            continue
        source = (node.id.region, node.id.area)
        target = (node.default_connection.region, node.default_connection.area)
        adjacency.setdefault(source, set()).add(target)
        adjacency.setdefault(target, set()).add(source)

    start = _start_area(from_area)
    distances: dict[AreaKey, int] = {start: 0}
    queue: deque[AreaKey] = deque([start])
    while queue:
        current = queue.popleft()
        for neighbour in sorted(adjacency.get(current, ())):
            if neighbour not in distances:
                distances[neighbour] = distances[current] + 1
                queue.append(neighbour)
    return distances


def independent_pickups(
    start_area: NodeId | AreaKey | str = "Temple Grounds/Landing Site",
    max_distance: int = _DEFAULT_MAX_DISTANCE,
    count: int = len(INDEPENDENT_PICKUP_INDICES),
) -> list[int]:
    """The first ``count`` pickups from the verified bench
    (:data:`INDEPENDENT_PICKUP_INDICES`) that are within ``max_distance``
    doors of ``start_area``. Pinned to the checked-in bench rather than
    recomputed, because "independent" is a property of the specific rooms
    (verified by playing), not a clean graph predicate.
    """
    distances = door_distance(start_area)
    chosen: list[int] = []
    for index in INDEPENDENT_PICKUP_INDICES:
        location = LOCATION_TABLE[index]
        distance = distances.get((location.region, location.area))
        if distance is None or distance > max_distance:
            continue
        chosen.append(index)
        if len(chosen) >= count:
            break
    if len(chosen) < count:
        raise ValueError(
            f"only {len(chosen)} of the verified independent pickups are within "
            f"{max_distance} doors of {_start_area(start_area)!r} (needed {count})"
        )
    return chosen


def pickups_spanning_counter_groups(
    start_area: NodeId | AreaKey | str = "Temple Grounds/Landing Site",
    per_group: int = 1,
) -> dict[int, list[int]]:
    """``{counter group -> pickup indices}``, for MT08.

    PLAN.md section P spreads the 119 pickups one bit per pickup across
    four persistent counters, with ``index // BITS_PER_COUNTER`` choosing
    the counter. A collect-while-detached test only exercises the decode
    across counters if the pickups it collects land in *different* groups,
    so this picks the ``per_group`` pickups closest to ``start_area`` by
    door distance within each group (ties broken by pickup index, so the
    picks are stable). Areas unreachable through vanilla connections are
    skipped, the same as ``door_distance`` leaves them out.
    """
    from ...pickup_encoding import BITS_PER_COUNTER

    distances = door_distance(start_area)
    by_group: dict[int, list[tuple[int, int]]] = {}
    for index, location in enumerate(LOCATION_TABLE):
        distance = distances.get((location.region, location.area))
        if distance is None:
            continue
        by_group.setdefault(index // BITS_PER_COUNTER, []).append((distance, index))

    chosen: dict[int, list[int]] = {}
    for group, entries in sorted(by_group.items()):
        if len(entries) < per_group:
            raise ValueError(
                f"counter group {group} only has {len(entries)} reachable pickups (needed {per_group})"
            )
        chosen[group] = [index for _distance, index in sorted(entries)[:per_group]]
    return chosen
