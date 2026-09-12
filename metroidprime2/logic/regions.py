"""Builds the MultiWorldGG region/entrance graph for Metroid Prime 2: Echoes
directly from the vendored randovania logic database.

See ``PLAN.md`` section E for the full specification. This module exposes
three override points, each consulting a per-seed assignment built once in
``generate_early`` (``world.dock_rando`` from ``logic/dock_rando.py``;
``world.translator_gate_assignment`` from
``logic/translator_gate_rando.py``) so entrance randomization and the rest
of ``create_regions`` stay decoupled:

* ``dock_target(world, node)``           -- which node a dock connects to.
* ``dock_weakness_for(world, db, node)`` -- which DockWeakness governs a dock.
* ``translator_gate_requirement(world, node)`` -- the requirement to pass a
  translator gate (``configurable_node``): each gate's vanilla color,
  unless ``translator_gate_rando`` reassigned it (see
  ``logic/translator_gate_rando.py``).
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from BaseClasses import ItemClassification, Region

from .. import constants
from ..items import MetroidPrime2Item
from ..locations import LOCATION_TABLE, MetroidPrime2Location
from ..options import damage_strictness_multiplier, dark_damage_per_second
from .db_reader import DockWeakness, GameDatabase, Node, NodeId, load_game_database
from .item_mapping import event_item_name
from .requirements import Impossible, RequirementCompiler, Rule, build_static_context, combine_and

if TYPE_CHECKING:
    from .. import MetroidPrime2World

logger = logging.getLogger(__name__)

# The Temple Grounds/Credits copy of "Event - Dark Samus 3 and 4" has no
# incoming connections anywhere in the logic database (verified in
# tools/sync_randovania_data.py / PLAN.md Context); the reachable node
# living under Sky Temple Grounds/Sky Temple Gateway is the real victory
# condition. Skip the dangling copy entirely -- it would otherwise become
# an unreachable region with a duplicate "Event - Dark Samus 3 and 4" item
# that no rule ever requires.
CREDITS_EVENT_NODE = NodeId("Temple Grounds", "Credits", "Event - Dark Samus 3 and 4")

VICTORY_EVENT_ITEM = "Event - Dark Samus 3 and 4"

TRANSLATOR_COLORS = ("Violet", "Amber", "Emerald", "Cobalt")


# --------------------------------------------------------------------------
# Override points (v1: vanilla-only; see module docstring).
# --------------------------------------------------------------------------


def dock_target(world: MetroidPrime2World, node: Node) -> NodeId | None:
    """The node a dock connects to: the vanilla ``default_connection``,
    unless ``world.dock_rando`` has reassigned this elevator or portal (see
    ``logic/dock_rando.py``). There's no ``dock_type == "teleporter"``
    left to handle here -- see ``dock_rando.build_elevator_assignment``'s
    docstring for why."""
    if node.dock_type == "elevator":
        return world.dock_rando.elevator.get(node.id, node.default_connection)
    if node.dock_type == "portal":
        return world.dock_rando.portal.get(node.id, node.default_connection)
    return node.default_connection


def dock_weakness_for(world: MetroidPrime2World, db: GameDatabase, node: Node) -> DockWeakness:
    """The DockWeakness governing a dock node: the vanilla
    ``default_dock_weakness``, unless ``world.dock_rando`` has reassigned
    this door's lock or this portal's "No Return Portal" arrival weakness
    (see ``logic/dock_rando.py``)."""
    if node.dock_type == "door":
        new_name = world.dock_rando.door_lock.get(node.id)
        if new_name is not None:
            return db.dock_weaknesses[("door", new_name)]
    elif node.dock_type == "portal":
        new_name = world.dock_rando.portal_weakness.get(node.id)
        if new_name is not None:
            return db.dock_weaknesses[("portal", new_name)]
    assert node.dock_type is not None, f"{node.ap_name}: dock_weakness_for called on a non-dock node"
    assert node.default_dock_weakness is not None, f"{node.ap_name}: dock node has no default_dock_weakness"
    return db.dock_weaknesses[(node.dock_type, node.default_dock_weakness)]


def translator_gate_requirement(world: MetroidPrime2World, node: Node) -> dict:
    """The requirement to pass a translator gate (``configurable_node``):
    Scan Visor, plus the translator color this gate currently requires --
    ``None`` (no translator at all -- an "Unlocked" gate, only possible
    under ``translator_gate_rando``'s "Random (Unlocked)" mode) is the one
    case where the second, color half of the requirement is omitted.

    When ``world.translator_gate_assignment`` has no entry for this gate
    (``translator_gate_rando`` left at its "Vanilla" default -- the dict is
    then empty for every gate, see ``logic/translator_gate_rando.py``),
    falls back to ``db.vanilla_translator_gates``, vendored verbatim from
    randovania's own ``prime2_opr`` starter preset (see
    ``data/vanilla_translator_gates.json`` and
    ``tools/sync_randovania_data.py``'s
    ``generate_vanilla_translator_gates``).

    That preset -- not the logic database's per-node
    ``extra.vanilla_actual``/``extra.vanilla_color`` -- is the authoritative
    definition of "vanilla" here, because open-prime-rando's patched game is
    not the retail game:

    * ``vanilla_actual`` is the unpatched retail requirement. Taking it
      literally deadlocks the start: every path out of the Temple Grounds
      "inner loop" (Hive area/Industrial Site/Temple Assembly Site) would be
      gated on a translator whose own vanilla pickup (Great Temple/Main
      Energy Controller) is only reachable back through that same set of
      gates.
    * ``vanilla_color`` fixes that for Meeting Grounds/GFMC Compound but is
      still wrong for Temple Grounds/Hive Transport Area and Temple
      Grounds/Industrial Site. OPR's always-on
      ``hive_access_tunnel_translator_gate`` rebalance patch relocates the
      Hive Access Tunnel gate to guard the drop to Hive Chamber A, which
      leaves the Landing Site start with no item-free exit at all unless
      those two downstream gates are gone -- so randovania's prime2_opr
      preset ships both as ``"removed"`` ("Unlocked": Scan Visor only, no
      translator item), i.e. ``None`` here.
    """
    if node.id in world.translator_gate_assignment:
        color = world.translator_gate_assignment[node.id]
    else:
        db = load_game_database()
        assert node.id in db.vanilla_translator_gates, f"{node.ap_name}: no vanilla translator requirement"
        color = db.vanilla_translator_gates[node.id]
        assert color is None or color in TRANSLATOR_COLORS, (
            f"{node.ap_name}: unexpected translator color {color!r}"
        )

    items = [
        {
            "type": "resource",
            "data": {"type": "items", "name": "Scan", "amount": 1, "negate": False},
        },
    ]
    if color is not None:
        items.append(
            {
                "type": "resource",
                "data": {"type": "items", "name": color, "amount": 1, "negate": False},
            }
        )
    return {"type": "and", "data": {"comment": None, "items": items}}


def can_warp_to_start(db: GameDatabase, player: int) -> Rule:
    """True iff any of the 18 save-station regions
    (``GameDatabase.starting_location_candidates("save_stations")``) is
    currently reachable -- the logic-side counterpart of
    ``client/warp_patch.py``'s real declining-a-save-with-L+R warp, which
    unconditionally retargets every one of those 18 rooms' WorldTeleporter
    at ``configuration.starting_area`` (== ``origin_region_name``),
    regardless of which one ended up as the start. Ported from
    MultiWorldGG's Metroid Prime 1 world (``worlds/metroidprime/
    Logic.py``'s ``can_warp_to_start``, which sweeps its own equivalent
    ``SAVE_ROOMS`` list).

    Deliberately keyed on the fixed 18-room save-station set regardless of
    which pool ``options.py``'s ``StartingRoom`` actually drew the start
    from: the decline-a-save warp physically exists only in those 18 rooms
    (verified against a real ISO), even when ``starting_room`` is
    "anywhere" and the player starts somewhere that has no save station at
    all (e.g. a boss arena). Under "vanilla" or "save_stations",
    ``origin_region_name`` is itself always one of these 18, so this Rule
    is trivially always true once a region graph exists (the origin region
    is always reachable, unconditionally -- see ``BaseClasses.
    CollectionState.update_reachable_regions``); under "anywhere" it is
    genuinely state-dependent -- false until some *other* save station has
    actually been reached.
    """
    ap_names = tuple(node_id.ap_name for node_id in db.starting_location_candidates("save_stations"))

    def rule(state, _names=ap_names, _player=player) -> bool:
        return any(state.can_reach_region(name, _player) for name in _names)

    return rule


def _lock_broken_event_item(node: Node) -> str:
    """The AP-only event item name for ``node``'s dock lock having been
    broken (either blasted from the front, or unlocked for free by having
    reached the target dock from the back). Not a DB event -- see the
    front-blast-back-free-unlock comment in the Step 5 loop below."""
    return f"Lock Broken - {node.ap_name}"


def _leave_requirement(world: MetroidPrime2World, node: Node) -> dict | None:
    """The additional requirement applied to every OUTGOING connection from
    ``node`` (PLAN.md section E step 3)."""
    if node.node_type == "configurable_node":
        return translator_gate_requirement(world, node)
    if node.node_type == "hint":
        return node.requirement_to_collect
    return None


# --------------------------------------------------------------------------
# Edge compilation (Steps 4/5) -- factored out of create_regions so
# logic/dock_rando.py's reject-and-retry reachability probe (see that
# module's docstring) can build the *exact* same (target, rule) edges
# against a candidate dock-rando assignment without duplicating this logic
# and risking the two drifting apart. Returns raw (NodeId, Rule|None, str)
# tuples rather than connecting real BaseClasses Regions, so both call
# sites can use them however they need.
# --------------------------------------------------------------------------


def _intra_area_edges(
    world: MetroidPrime2World, db: GameDatabase, compiler: RequirementCompiler, node: Node
) -> list[tuple[NodeId, Rule | None, str]]:
    """Step 4: every intra-area ``node.connections`` edge from ``node``,
    each ANDed with ``node``'s own "leave" requirement (translator gate /
    hint, if any). Skips edges whose combined requirement is Impossible."""
    leave_req = _leave_requirement(world, node)
    edges: list[tuple[NodeId, Rule | None, str]] = []
    for target_name, req in node.connections.items():
        target_id = NodeId(node.id.region, node.id.area, target_name)
        if target_id == CREDITS_EVENT_NODE:
            continue
        try:
            rule = compiler.compile_all([req, leave_req])
        except Impossible:
            continue
        edges.append((target_id, rule, f"{node.ap_name} -> {target_id.ap_name}"))
    return edges


def _dock_edge(
    world: MetroidPrime2World, db: GameDatabase, compiler: RequirementCompiler, node: Node
) -> tuple[NodeId, Rule | None, str] | None:
    """Step 5: ``node``'s single outgoing dock-connection edge, or
    ``None`` if ``node`` isn't a dock, has no live target, or its
    open/lock requirement compiles to Impossible. See the front-blast-
    back-free-unlock comment in ``create_regions`` for the lock-broken
    "alternative" semantics."""
    if node.node_type != "dock":
        return None
    target_id = dock_target(world, node)
    if target_id is None or target_id == CREDITS_EVENT_NODE:
        return None
    target_node = db.node(target_id)

    weakness = dock_weakness_for(world, db, node)
    # A node-specific open/lock override was authored against this node's
    # *vanilla* weakness; it no longer applies once door lock rando has
    # reassigned the node to a different weakness (logic/dock_rando.py).
    weakness_is_vanilla = weakness.name == node.default_dock_weakness
    override_open = node.override_default_open_requirement if weakness_is_vanilla else None
    override_lock = node.override_default_lock_requirement if weakness_is_vanilla else None

    open_req = override_open or weakness.requirement
    try:
        open_rule = compiler.compile(open_req)
        lock_rule = None
        if weakness.lock_requirement is not None:
            lock_req = override_lock or weakness.lock_requirement
            if target_node.node_type == "dock":
                # The target is itself a paired dock node -- reaching it at
                # all permanently unlocks this side for free, via a
                # synthetic "Lock Broken" event (see
                # ``_lock_broken_event_item``/create_regions's pre-pass).
                lock_rule = compiler.compile_with_alternative(lock_req, _lock_broken_event_item(node))
            else:
                # A one-way dock straight into a plain spawn point has no
                # back side to reach from, so there is no free-unlock
                # alternative.
                lock_rule = compiler.compile(lock_req)
    except Impossible:
        return None

    rule = combine_and([open_rule, lock_rule])
    return target_id, rule, f"{node.ap_name} -> {target_id.ap_name}"


# --------------------------------------------------------------------------
# create_regions
# --------------------------------------------------------------------------


def create_regions(world: MetroidPrime2World) -> None:
    db = load_game_database()
    player = world.player
    multiworld = world.multiworld

    ctx = build_static_context(
        player=player,
        trick_levels=world.trick_levels,
        damage_strictness=damage_strictness_multiplier(world.options),
        energy_per_tank=world.options.energy_per_tank.value,
        dark_aether_damage=dark_damage_per_second(world.options.dark_aether_damage.value),
        dark_suit_damage=dark_damage_per_second(world.options.dark_suit_damage.value),
        progressive_suit=bool(world.options.progressive_suit),
        progressive_grapple=bool(world.options.progressive_grapple),
        missile_expansions_unlock_launcher=bool(world.options.missile_expansions_unlock_launcher),
    )
    compiler = RequirementCompiler(db, ctx)

    # -- Step 2: one Region per node (except the dangling Credits copy). --
    regions: dict[NodeId, Region] = {}
    for node in db.all_nodes():
        if node.id == CREDITS_EVENT_NODE:
            continue
        region = Region(node.id.ap_name, player, multiworld)
        regions[node.id] = region
    multiworld.regions.extend(regions.values())

    origin_region = regions[world.starting_location]
    assert origin_region.name == world.origin_region_name, (
        f"origin_region_name {world.origin_region_name!r} disagrees with "
        f"starting_location {world.starting_location.ap_name!r}"
    )

    location_by_index = {loc.pickup_index: loc for loc in LOCATION_TABLE}

    # -- Steps 6/7: locations (pickups + non-pregranted events). --
    for node in db.all_nodes():
        if node.id == CREDITS_EVENT_NODE:
            continue
        region = regions[node.id]

        if node.node_type == "pickup":
            loc_data = location_by_index[node.pickup_index]
            location = MetroidPrime2Location(player, loc_data.name, loc_data.code, region)
            region.locations.append(location)

        elif node.node_type == "event" and node.event_name not in constants.PREGRANTED_EVENTS:
            item_name = event_item_name(db, node.event_name)
            location = MetroidPrime2Location(player, node.ap_name, None, region)
            location.show_in_spoiler = False
            region.locations.append(location)
            location.place_locked_item(
                MetroidPrime2Item(item_name, ItemClassification.progression, None, player)
            )

    # -- Lock-broken events: one per dock node with a lock whose target is
    # itself a dock node (the paired, two-sided case -- see the front-
    # blast-back-free-unlock comment in the Step 5 loop below). Each event
    # item is placed on an event location in the *target's* region (region
    # B), rule None, so it becomes available the instant B is reached by
    # any route, and the Step 5 loop below can OR it into A's lock rule.
    lock_broken_dock_count = 0
    for node in db.all_nodes():
        if node.id == CREDITS_EVENT_NODE or node.node_type != "dock":
            continue
        weakness = dock_weakness_for(world, db, node)
        if weakness.lock_requirement is None:
            continue
        target_id = dock_target(world, node)
        if target_id is None or target_id == CREDITS_EVENT_NODE:
            continue
        target_node = db.node(target_id)
        if target_node.node_type != "dock":
            continue

        target_region = regions[target_id]
        item_name = _lock_broken_event_item(node)
        location = MetroidPrime2Location(player, item_name, None, target_region)
        location.show_in_spoiler = False
        target_region.locations.append(location)
        location.place_locked_item(
            MetroidPrime2Item(item_name, ItemClassification.progression, None, player)
        )
        lock_broken_dock_count += 1

    logger.info(
        "metroidprime2: created %d dock lock-broken event(s)", lock_broken_dock_count
    )

    # -- Steps 3/4/5: entrances. --
    #
    # Echoes dock locks are all "front-blast-back-free-unlock" (see
    # randovania/graph/world_graph_factory.py::_create_dock_connection):
    # for a dock A (front, has a lock) whose target is B, crossing A -> B
    # requires open(A) AND lock_broken(A), where lock_broken(A) is
    # satisfied either by A's own lock requirement (blasting it from the
    # front) or by having already reached B at all (the lock falls open
    # for free from the back, permanently). Crossing B -> A only ever
    # requires open(B) plus B's *own* front lock, if any -- never A's lock
    # requirement. Each direction is a separate node in this per-node-
    # region model, so that asymmetry falls out naturally: ``_dock_edge``
    # only ever looks at its own node's weakness, never the target's. See
    # ``_intra_area_edges``/``_dock_edge`` above (Step 4/5 edge
    # compilation, shared verbatim with ``logic/dock_rando.py``'s
    # reachability probe).
    for node in db.all_nodes():
        if node.id == CREDITS_EVENT_NODE:
            continue
        region = regions[node.id]

        for target_id, rule, name in _intra_area_edges(world, db, compiler, node):
            dst_region = regions[target_id]
            region.connect(dst_region, name=name, rule=rule)

        edge = _dock_edge(world, db, compiler, node)
        if edge is not None:
            target_id, rule, name = edge
            dst_region = regions[target_id]
            region.connect(dst_region, name=name, rule=rule)

    # -- Warp to start. --
    #
    # client/warp_patch.py's decline-a-save+L+R feature already retargets
    # every one of the 18 save-station rooms' WorldTeleporter at
    # configuration.starting_area (== origin_region_name) unconditionally
    # in the patched ISO, whenever warp_to_start is enabled -- model that
    # same shortcut as a real graph edge so logic sees it too, gated on the
    # same option. This always uses the fixed 18-room save-station set
    # (can_warp_to_start's own candidates), never options.starting_room's
    # actual pool: the warp only physically exists in those 18 rooms, even
    # when starting_room is "anywhere" and origin_region_name is some other
    # room entirely (a boss arena, say) with no save station of its own.
    #
    # Provably a no-op for reachability regardless of pool: origin_region is
    # AP's BFS root (CollectionState.update_reachable_regions seeds it
    # unconditionally, with no rule check at all), so it is already always
    # reachable before this loop ever runs, and an edge whose *target* is
    # already unconditionally reachable can never add anything. Wired in
    # anyway, exactly as specified, rather than skipped as dead code -- see
    # can_warp_to_start's docstring for the one case (starting_room ==
    # "anywhere") where the Rule itself is genuinely state-dependent, even
    # though these particular edges can't exploit that.
    if world.options.warp_to_start:
        warp_rule = can_warp_to_start(db, player)
        for node_id in db.starting_location_candidates("save_stations"):
            source_region = regions[node_id]
            if source_region is origin_region:
                continue
            source_region.connect(origin_region, name=f"{source_region.name} -> Warp to Start", rule=warp_rule)

    # -- Dead event nodes. --
    #
    # A region can end up with zero incoming entrances at all -- e.g. its
    # sole would-be entrance's rule folded to Impossible and was skipped
    # entirely above (see test/bases.py's MP2TestBase.run_default_tests
    # docstring for a concrete example: the "Gate Removal" event behind
    # `not VanillaGreatTempleEmeraldGate`, which this world's fixed static
    # context always forces False). Such a region is structurally
    # unreachable no matter what items the player holds. Any event
    # *location* placed there (a DB event, or one of the synthetic
    # "Lock Broken" events above) can therefore never be reached and would
    # otherwise trip AP's prefill/accessibility checks -- so find every
    # such region (a fixed point: alive = origin, plus anything reachable
    # from an already-alive region) and strip just their event locations,
    # keeping the (now locationless) regions themselves.
    alive_regions: set[Region] = {origin_region}
    frontier = [origin_region]
    while frontier:
        current = frontier.pop()
        for exit_ in current.exits:
            target = exit_.connected_region
            if target is not None and target not in alive_regions:
                alive_regions.add(target)
                frontier.append(target)

    dead_regions = [r for r in regions.values() if r not in alive_regions]
    removed_event_location_count = 0
    for dead_region in dead_regions:
        kept_locations = [loc for loc in dead_region.locations if loc.address is not None]
        removed_event_location_count += len(dead_region.locations) - len(kept_locations)
        dead_region.locations = kept_locations

    logger.info(
        "metroidprime2: pruned %d unreachable event location(s) across %d "
        "structurally-unreachable region(s) (%d/%d regions reachable)",
        removed_event_location_count,
        len(dead_regions),
        len(alive_regions),
        len(regions),
    )

    # -- Step 8: completion condition. --
    multiworld.completion_condition[player] = lambda state: state.has(VICTORY_EVENT_ITEM, player)

    # -- Cheap asserts. --
    pickup_location_count = sum(
        1
        for region in regions.values()
        for location in region.locations
        if location.address is not None
    )
    assert pickup_location_count == 119, f"expected 119 pickup locations, got {pickup_location_count}"

    total_entrances = sum(len(region.exits) for region in regions.values())
    assert total_entrances > 2000, f"expected >2000 entrances, got {total_entrances}"

    assert world.origin_region_name in {region.name for region in regions.values()}, (
        f"origin_region_name {world.origin_region_name!r} is not a region"
    )
