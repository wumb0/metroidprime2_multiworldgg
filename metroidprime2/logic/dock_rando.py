"""Door-lock, elevator, and teleporter randomization for Metroid Prime 2:
Echoes: builds the per-seed assignments consulted by ``logic/regions.py``'s
``dock_target``/``dock_weakness_for`` override points and by
``patch_data.py``'s ``_world_changes`` (the same assignment drives both the
logic graph and the in-ISO patch, since both read ``world.dock_rando``).

**Door locks**: randovania's own prime2 door lock randomizer does NOT
independently reassign each door side a uniform-random weakness -- despite
what an earlier version of this docstring claimed. It builds one global
``old_weakness -> new_weakness`` substitution (``_distribute_mode_weakness``
in ``randovania/generator/dock_weakness_distributor.py``, mode
``WEAKNESS_TO_WEAKNESS``) and applies it per node keyed by that node's
*vanilla* weakness, then (``force_change_two_way``) copies the result onto
the node's physical pair-partner so both faces of one physical door end up
with the same new weakness -- never two independent locks on one door. This
module now does the same (``_global_weakness_mapping`` / ``_door_pairs`` /
``_sample_door_lock_candidate``).

Randovania's OTHER real safety net -- and the one actually load-bearing for
solvability, not the distribution shape -- is that ``distribute_pre_fill_
weaknesses`` runs as part of the SAME generation attempt its own resolver
later validates, and the whole attempt (patches + filler) is wrapped in a
reject-and-retry loop (``generator.generate_and_validate_expected_layout``,
``tenacity.AsyncRetrying`` over ``UnableToGenerate``, several attempts):
a weakness distribution its resolver can't solve just means that whole
generation attempt is discarded and restarted from scratch, dock weaknesses
included. Archipelago's ``Fill`` has no equivalent backstop: a
``FillError`` just aborts generation, and (measured) neither the corrected
distribution NOR the old one is sufficient on its own -- a straight port of
randovania's global-mapping distribution alone still failed 10/10 test
seeds. What actually matters is ``_meets_progression_bar`` below: a coarse
but *item-aware* forward sweep (unlike ``_reachable_nodes``, which is
deliberately item-blind) that rejects any candidate leaving the start state
unable to reach a minimum handful of pickups, or leaving any pickup
unreachable with every item collected, and retries (bounded, like the
elevator/teleporter pool below) until one passes or the budget is
exhausted.

**Elevators and teleporters**: both are reciprocal two-way pools (shuffling
one dock node's target also repoints its partner, so the graph stays a set
of two-way connections, like vanilla). Losing an entire *region* to a bad
shuffle is a real risk (most elevators/teleporters are the only path
between top-level regions), so both pools first use a cheap, item-blind
reject-and-retry loop (``_reachable_nodes``) purely to reject topology
mistakes -- and then, like door locks, an additional ``_meets_progression_bar``
check, applied for the same reason: a topologically-connected shuffle can
still leave the start state (or the all-items state) unable to make
progress.

Measured (37 identical seeds, 1000-1036, before/after this module's fix):
``door_lock_rando`` went from 37/37 generation failures to 1/37.
``elevator_rando`` was unchanged at 6/37 both before and after. That's not
a bug in the check -- it's a different failure class than door locks had.
Every one of door lock rando's failures was a pure sphere-0 lockout (0/119
pickups reachable from the start state), exactly what
``_meets_progression_bar``'s first check targets, so fixing it fixed
nearly all of them. The elevator_rando failures diagnosed (seeds 2000,
2003, 2004 with a wider sweep) all had sphere-0 >= 1 *and* all-items
reachability = 119/119 -- both bars this module checks -- yet ``Fill``
still failed to place 110+ items. That means the deadlock is a genuine
*mid-game* ordering problem: some item is only obtainable by first passing
through a lock that itself needs that item (or one gated the same way),
several spheres deep, which a two-snapshot coarse check structurally
cannot see (see PLAN.md / the task notes this module was written against).
Catching it for real needs something closer to an assumed-fill solver
(incrementally decide *which* item unlocks each newly-reachable batch of
locations, the way ``Fill.py``'s own restrictive fill does) rather than a
static reachability snapshot; that's out of scope for what this coarse,
cheap-per-attempt check can practically do, and out of scope for this
change (see PLAN.md's task notes: "if not, say so with measurements rather
than churning"). Raising ``_MIN_SPHERE_ZERO_PICKUPS`` well above 1 was
tried empirically and rejected: it makes attempts fail their first,
already-mostly-connected candidate far more often, and each retry's
``_meets_progression_bar`` call (rebuilding + double-sweeping the ~2000-
edge probe graph) is expensive enough that a handful of extra retries
already cost multiple seconds -- with no evidence it actually converges on
solvable shuffles for this failure class rather than just spinning.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from .. import constants
from ..options import dark_damage_per_second, damage_strictness_multiplier
from .db_reader import GameDatabase, Node, NodeId, load_game_database
from .item_mapping import event_item_name
from .regions import CREDITS_EVENT_NODE, _dock_edge, _intra_area_edges, _lock_broken_event_item, dock_weakness_for
from .requirements import Rule, RequirementCompiler, build_static_context

if TYPE_CHECKING:
    from .. import MetroidPrime2World

# --------------------------------------------------------------------------
# Door locks
# --------------------------------------------------------------------------

# Randovania's prime2 door lock randomizer's vetted type pool (verified
# against randovania/games/prime2/presets/starter_preset.rdvpreset's
# `configuration.dock_rando`): every other vanilla weakness type
# (Darkburst/Sunburst/SonicBoom/Bomb/Boost/ScrewAttack/DarkVisor/EchoVisor
# blast shields, "Disabled", "Normal Door (Forced)") is left untouched,
# whether as a source or a target.
DOOR_CAN_CHANGE_FROM: frozenset[str] = frozenset(
    {
        "Annihilator Door",
        "Dark Door",
        "Light Door",
        "Missile Blast Shield",
        "Normal Door",
        "Power Bomb Blast Shield",
        "Seeker Launcher Blast Shield",
        "Super Missile Blast Shield",
    }
)

# Same 8 types minus "Seeker Launcher Blast Shield" (only ever a *source*;
# the door-open animation leaves behind a shell that must be patched back
# to the distinct "(patched)" variant, never the original), plus that
# "(patched)" variant.
#
# Deliberately NOT included: randovania's own preset also allows
# "Permanently Locked" (compiles to Impossible) as a shuffle target,
# relying on its own dedicated resolver to reject-and-retry any seed that
# makes a location unreachable. This world has no equivalent resolver --
# ``_meets_progression_bar`` below is a much coarser stand-in -- and a
# single-entrance room (e.g. Temple Grounds/Hive Chamber A's Missile
# pickup) landing on "Permanently Locked" reproducibly stranded a pickup
# in testing. Every remaining type always has a real (if sometimes
# item-gated) requirement, so no door can ever become structurally
# impassable.
DOOR_CAN_CHANGE_TO: tuple[str, ...] = (
    "Annihilator Door",
    "Dark Door",
    "Light Door",
    "Missile Blast Shield",
    "Normal Door",
    "Power Bomb Blast Shield",
    "Seeker Launcher Blast Shield (patched)",
    "Super Missile Blast Shield",
)


def _door_pairs(db: GameDatabase) -> dict[NodeId, NodeId]:
    """``{node_id: target_id}`` for every door dock node whose vanilla
    target is itself a door dock node -- the physically-paired case
    randovania's own ``all_docks`` dict in ``dock_weakness_distributor.py``
    keys its ``force_change_two_way`` sync off. Not necessarily symmetric
    as a dict (a handful of doors dead-end into something that isn't a
    door), but every entry that does have a reverse entry is a true
    physical pair."""
    pairs: dict[NodeId, NodeId] = {}
    for node in db.all_nodes():
        if node.node_type != "dock" or node.dock_type != "door":
            continue
        if node.default_connection is None:
            continue
        target = db.node(node.default_connection)
        if target.node_type == "dock" and target.dock_type == "door":
            pairs[node.id] = target.id
    return pairs


def _global_weakness_mapping(world: "MetroidPrime2World") -> dict[str, str]:
    """A random bijection-shaped ``old_weakness_name -> new_weakness_name``
    substitution over ``DOOR_CAN_CHANGE_FROM``/``DOOR_CAN_CHANGE_TO``,
    mirroring randovania's ``_distribute_mode_weakness``: shuffle both
    lists independently and zip them (extending the target list if it were
    ever shorter than the source list -- today both are length 8, so this
    is a plain random pairing, not literally a permutation).

    ``sorted(...)`` rather than ``list(...)`` on ``DOOR_CAN_CHANGE_FROM``
    is deliberate: it's a ``frozenset``, whose iteration order depends on
    Python's per-process string hash randomization (``PYTHONHASHSEED``),
    not on ``world.random`` at all. Shuffling a set-derived list starting
    from a hash-randomized order means the exact same seed produces a
    DIFFERENT weakness assignment in a different process/run -- breaking
    the reproducibility every other part of this world (and AP generation
    in general) relies on. Sorting first fixes the starting order so
    ``world.random.shuffle`` is the only source of randomness, as
    intended (caught empirically: the same seed passed/failed
    generation depending on which process ran it, before this fix)."""
    sources = sorted(DOOR_CAN_CHANGE_FROM)
    targets = list(DOOR_CAN_CHANGE_TO)
    world.random.shuffle(sources)
    world.random.shuffle(targets)
    while len(targets) < len(sources):
        targets.extend(DOOR_CAN_CHANGE_TO)
    return dict(zip(sources, targets))


def _sample_door_lock_candidate(
    world: "MetroidPrime2World", db: GameDatabase, pairs: dict[NodeId, NodeId]
) -> dict[NodeId, str]:
    """One candidate ``{door_node_id: new_weakness_name}`` assignment:
    every eligible door gets ``mapping[its vanilla weakness]``, and when
    both faces of a physical door (``_door_pairs``) are eligible, the
    second face mirrors the first's *resulting* weakness rather than
    independently mapping its own (usually different) vanilla weakness --
    otherwise a single physical door could end up with two unrelated
    locks, one per face, which randovania's own ``force_change_two_way``
    exists specifically to prevent."""
    mapping = _global_weakness_mapping(world)
    assignment: dict[NodeId, str] = {}
    handled: set[NodeId] = set()
    for node in db.all_nodes():
        if node.node_type != "dock" or node.dock_type != "door":
            continue
        if node.id in handled or node.default_dock_weakness not in DOOR_CAN_CHANGE_FROM:
            continue
        new_weakness = mapping[node.default_dock_weakness]
        assignment[node.id] = new_weakness
        handled.add(node.id)

        partner_id = pairs.get(node.id)
        if partner_id is None or partner_id in handled:
            continue
        partner = db.node(partner_id)
        if partner.default_dock_weakness in DOOR_CAN_CHANGE_FROM:
            assignment[partner_id] = new_weakness
            handled.add(partner_id)
    return assignment


# --------------------------------------------------------------------------
# Elevators / teleporters (shared two-way shuffle machinery)
# --------------------------------------------------------------------------

# Intra-region pair excluded from elevator shuffling (verified against
# randovania's starter_preset.rdvpreset's always-excluded teleporter list):
# unlike every other elevator pair, both ends of this one are in the same
# region (Sanctuary Fortress), and randovania's own tested preset pins it
# vanilla. The other always-excluded pair in that preset (Sky Temple
# Grounds/Sky Temple Gateway <-> Sky Temple/Sky Temple Energy Controller,
# the one-way ending trip) doesn't need listing here: its two dock nodes
# each target a plain spawn point rather than each other, so
# ``_reciprocal_pairs``'s own reciprocity check already excludes it.
ELEVATOR_EXCLUDED_AP_NAMES: frozenset[str] = frozenset(
    {
        "Sanctuary Fortress/Aerie/Elevator to Aerie Transport Station",
        "Sanctuary Fortress/Aerie Transport Station/Elevator to Aerie",
    }
)

# Item-blind topology check (_reachable_nodes) is cheap and mostly used to
# fail fast on a structurally-disconnected shuffle; _meets_progression_bar
# is the expensive, item-aware check and dominates attempt cost, so this
# budget is far smaller than it would need to be for the topology check
# alone (see PLAN.md / task notes for measured attempts-to-converge).
_MAX_SHUFFLE_ATTEMPTS = 2_000

# Door lock candidates are cheaper to reject (no separate topology
# pre-filter is meaningful -- door lock rando never changes *where* a door
# leads, only whether it's locked, so plain graph connectivity is
# unaffected by the choice of weakness) but still dominated by
# _meets_progression_bar cost per attempt.
_MAX_DOOR_LOCK_ATTEMPTS = 2_000

# "a handful of pickups" (task wording): the start state must be able to
# make SOME initial progress. Tuned empirically against measured sphere-0
# counts (see PLAN.md / task notes: vanilla topology already reaches only
# 1 pickup at default options) -- set low enough that legitimate shuffles
# routinely clear it, high enough to reject the total-lockout case (0
# reachable pickups) this task was filed over.
_MIN_SPHERE_ZERO_PICKUPS = 1


@dataclass(frozen=True)
class DockRandoAssignment:
    door_lock: dict[NodeId, str] = field(default_factory=dict)
    elevator: dict[NodeId, NodeId] = field(default_factory=dict)
    teleporter: dict[NodeId, NodeId] = field(default_factory=dict)


def _reciprocal_pairs(
    db: GameDatabase, dock_type_name: str, excluded_ap_names: frozenset[str]
) -> list[tuple[Node, Node]]:
    """Every (A, B) pair of ``dock_type_name`` dock nodes where A's vanilla
    target is B and B's vanilla target is A, excluding anything in
    ``excluded_ap_names`` and any node whose vanilla target isn't a
    reciprocal same-type dock node (e.g. a one-way trip into a plain spawn
    point)."""
    seen: set[NodeId] = set()
    pairs: list[tuple[Node, Node]] = []
    for node in db.all_nodes():
        if node.node_type != "dock" or node.dock_type != dock_type_name:
            continue
        if node.id in seen or node.ap_name in excluded_ap_names:
            continue
        target_id = node.default_connection
        if target_id is None:
            continue
        target = db.node(target_id)
        if target.node_type != "dock" or target.dock_type != dock_type_name:
            continue
        if target.ap_name in excluded_ap_names:
            continue
        if target.default_connection != node.id:
            continue
        seen.add(node.id)
        seen.add(target.id)
        pairs.append((node, target))
    return pairs


def _shuffle_pairs(world: "MetroidPrime2World", pairs: list[tuple[Node, Node]]) -> dict[NodeId, NodeId]:
    """A random reciprocal re-pairing of ``pairs``' endpoints: a random
    perfect matching over the 2N nodes, independent of every other pool."""
    endpoints = [node for pair in pairs for node in pair]
    world.random.shuffle(endpoints)
    assignment: dict[NodeId, NodeId] = {}
    for i in range(0, len(endpoints), 2):
        a, b = endpoints[i], endpoints[i + 1]
        assignment[a.id] = b.id
        assignment[b.id] = a.id
    return assignment


def _event_gated_satisfied(req: dict | None, templates: dict[str, dict], unlocked_events: set[str]) -> bool:
    """Coarse, optimistic evaluator for one ``node.connections`` edge
    requirement: every requirement kind except an ``events`` resource
    check is treated as satisfied -- this check exists to catch
    structural, order-of-discovery topology breaks (a one-way switch that
    must be reached from one side before the shortcut opens from the
    other -- see ``_reachable_nodes``), not item/trick/damage difficulty,
    which ``_meets_progression_bar`` below covers instead. An ``events``
    check requires the referenced event to already be in
    ``unlocked_events``."""
    if req is None:
        return True
    req_type = req["type"]
    if req_type == "and":
        return all(_event_gated_satisfied(item, templates, unlocked_events) for item in req["data"]["items"])
    if req_type == "or":
        items = req["data"]["items"]
        if not items:
            return False  # Empty "or" is Impossible, same as the real compiler.
        return any(_event_gated_satisfied(item, templates, unlocked_events) for item in items)
    if req_type == "template":
        return _event_gated_satisfied(templates[req["data"]], templates, unlocked_events)
    if req_type == "resource":
        data = req["data"]
        if data["type"] == "events":
            satisfied = data["name"] in unlocked_events
            return not satisfied if data.get("negate", False) else satisfied
        return True  # items/tricks/misc/versions/damage: optimistic, not this check's concern.
    raise ValueError(f"unknown requirement type: {req_type!r}")


def _reachable_nodes(
    db: GameDatabase,
    elevator_targets: dict[NodeId, NodeId],
    teleporter_targets: dict[NodeId, NodeId],
) -> set[NodeId]:
    """Fixed-point sweep over a coarse graph -- every intra-area
    ``connections`` edge (gated only on ``events`` resources, via
    ``_event_gated_satisfied``; every other requirement kind is treated
    as optimistically satisfied) plus every dock node's resolved target
    (the candidate elevator/teleporter assignment being tested, vanilla
    ``default_connection`` for every other dock, including doors -- door
    lock rando never changes *where* a door leads, only whether it's
    locked, so this check doesn't need to know about it at all). Returns
    every node id reachable from the starting location.

    This is deliberately item-blind (see ``_meets_progression_bar`` for
    the item-aware check that actually catches the door-lock bootstrap
    deadlock this module's tests are named after). It exists purely to
    reject-fast on elevator/teleporter shuffles that break graph topology
    outright, and to guard against a subtlety: some connections are
    one-way switches (e.g. Great Temple's "Transport C Access Light
    Block": reachable freely from the Temple Sanctuary side, but the
    *reverse* direction requires that same event already triggered) --
    treating every ``connections`` edge as unconditionally traversable
    would let a shuffle that relies on walking through one of those
    backwards pass this check while actually being unreachable in the
    real, fully-compiled region graph (this was caught by the
    reachability tests in test/test_dock_rando.py, not derived
    analytically).

    Deliberately node-level, not region-level: a region can have several
    independent elevator/teleporter entry points whose *sub-areas* aren't
    otherwise interconnected (e.g. Great Temple's three "Temple Transport
    X Access" branches each hang off their own, otherwise-unrelated
    elevator) -- checking "is some node in this region reachable" would
    miss a shuffle that strands one such branch while leaving the rest of
    the region reachable through a different elevator. Checking that
    every original pool endpoint node is still reachable (see
    ``build_elevator_and_teleporter_assignment``) catches that case
    because reaching any one node lets this sweep cascade through its own
    ``connections`` edges into everything hanging off it."""

    def resolve_dock_target(node: Node) -> NodeId | None:
        if node.dock_type == "elevator":
            return elevator_targets.get(node.id, node.default_connection)
        if node.dock_type == "teleporter":
            return teleporter_targets.get(node.id, node.default_connection)
        return node.default_connection

    visited: set[NodeId] = {db.starting_location}
    unlocked_events: set[str] = set()

    changed = True
    while changed:
        changed = False
        for node_id in list(visited):
            node = db.node(node_id)

            if node.node_type == "event" and node.event_name is not None and node.event_name not in unlocked_events:
                unlocked_events.add(node.event_name)
                changed = True

            for target_name, req in node.connections.items():
                target_id = NodeId(node_id.region, node_id.area, target_name)
                if target_id in visited:
                    continue
                if _event_gated_satisfied(req, db.requirement_templates, unlocked_events):
                    visited.add(target_id)
                    changed = True

            if node.node_type == "dock":
                target_id = resolve_dock_target(node)
                if target_id is not None and target_id not in visited:
                    visited.add(target_id)
                    changed = True

    return visited


# --------------------------------------------------------------------------
# Item-aware progression probe.
#
# ``_reachable_nodes`` above is optimistic about every requirement except
# ``events``, so it happily accepts a shuffle that leaves the start state
# unable to obtain a single item -- exactly the door-lock-rando bug this
# module exists to fix (measured: 27/27 seeds with door_lock_rando on
# failed generation with a FillError, because ZERO of 119 pickups were
# reachable from the start state; the item-blind check above saw nothing
# wrong since it doesn't look at *any* item/weakness requirement).
#
# This probe builds the real (target, Rule) edge graph for a *candidate*
# assignment using the exact same ``_intra_area_edges``/``_dock_edge``
# helpers ``logic/regions.py``'s ``create_regions`` uses to build the real
# BaseClasses Region graph (imported from there, not reimplemented, so the
# two can never silently diverge -- see those functions' docstrings), then
# runs a small state-aware fixed-point sweep against a synthetic
# ``_ProbeState`` standing in for a real ``CollectionState``: "start"
# mode has only the vanilla starting inventory, "all" mode has everything.
# Real per-item/per-count logic still runs through the actual compiled
# ``Rule`` closures (``RequirementCompiler``), so trick/damage/misc/version
# requirements are evaluated exactly as they would be for real generation
# -- only the *set of items held* is synthetic, not the rule evaluation
# itself. Event/"Lock Broken" resources (see ``_dock_edge``'s docstring)
# are modelled as flags granted the instant their trigger node is visited,
# mirroring how ``create_regions`` places them as locked, rule-less event
# Locations.
# --------------------------------------------------------------------------


class _ProbeWorld:
    """Adapts a real ``world`` so ``regions.py``'s ``dock_target`` /
    ``dock_weakness_for`` / ``_leave_requirement`` override points see a
    *candidate* ``DockRandoAssignment`` instead of ``world.dock_rando``
    (which may not be finalized yet -- this is exactly what's being
    decided), without mutating the real world. Everything else
    (``world.options``, ``world.translator_gate_assignment``, ``player``,
    ``random``, ...) passes through untouched."""

    def __init__(self, world: "MetroidPrime2World", dock_rando: DockRandoAssignment) -> None:
        self._world = world
        self.dock_rando = dock_rando

    def __getattr__(self, name: str):
        return getattr(self._world, name)


@dataclass
class _ProbeState:
    """A minimal stand-in for ``CollectionState`` (``has``/``count``) used
    only by ``_meets_progression_bar``'s sweep. ``event_names`` is every
    pseudo-item name (DB events, "Lock Broken - ..." flags) this candidate
    graph's compiled rules might reference; anything else is a real AP
    item name, resolved from ``mode`` instead of a real inventory."""

    mode: str  # "start" (only constants.DEFAULT_STARTING_ITEMS) or "all" (everything)
    event_names: frozenset[str]
    starting_names: frozenset[str]
    flags: set[str] = field(default_factory=set)

    def has(self, name: str, player: int) -> bool:
        if name in self.event_names:
            return name in self.flags
        if self.mode == "all":
            return True
        return name in self.starting_names

    def count(self, name: str, player: int) -> int:
        if name in self.event_names:
            return 1 if name in self.flags else 0
        if self.mode == "all":
            return 9_999  # large enough to satisfy any real count threshold
        return 1 if name in self.starting_names else 0


def _build_probe_graph(
    probe_world: "MetroidPrime2World", db: GameDatabase, compiler: RequirementCompiler
) -> tuple[dict[NodeId, list[tuple[NodeId, Rule | None]]], dict[NodeId, list[str]], frozenset[str]]:
    """``(edges, flag_triggers, event_names)`` for the candidate assignment
    on ``probe_world.dock_rando``, built with ``regions.py``'s own Step
    4/5 edge helpers. ``flag_triggers[node_id]`` is every pseudo-item name
    that becomes true the instant ``node_id`` is visited (real DB events,
    non-pregranted; "Lock Broken - X" the moment X's *target* is
    reached -- see ``_dock_edge``'s docstring)."""
    edges: dict[NodeId, list[tuple[NodeId, Rule | None]]] = {}
    flag_triggers: dict[NodeId, list[str]] = {}
    event_names: set[str] = set()

    for node in db.all_nodes():
        if node.id == CREDITS_EVENT_NODE:
            continue

        if node.node_type == "event" and node.event_name not in constants.PREGRANTED_EVENTS:
            name = event_item_name(db, node.event_name)
            event_names.add(name)
            flag_triggers.setdefault(node.id, []).append(name)

        for target_id, rule, _name in _intra_area_edges(probe_world, db, compiler, node):
            edges.setdefault(node.id, []).append((target_id, rule))

        edge = _dock_edge(probe_world, db, compiler, node)
        if edge is not None:
            target_id, rule, _name = edge
            edges.setdefault(node.id, []).append((target_id, rule))

            weakness = dock_weakness_for(probe_world, db, node)
            if weakness.lock_requirement is not None and db.node(target_id).node_type == "dock":
                flag_name = _lock_broken_event_item(node)
                event_names.add(flag_name)
                flag_triggers.setdefault(target_id, []).append(flag_name)

    return edges, flag_triggers, frozenset(event_names)


def _probe_reachable(
    edges: dict[NodeId, list[tuple[NodeId, Rule | None]]],
    flag_triggers: dict[NodeId, list[str]],
    starting_location: NodeId,
    state: _ProbeState,
) -> set[NodeId]:
    """Fixed-point sweep, mirroring ``_reachable_nodes``'s shape but
    evaluating real compiled ``Rule`` closures against ``state`` (mutating
    ``state.flags`` in place as newly-visited nodes grant events/"Lock
    Broken" flags) instead of the coarse events-only check."""
    visited: set[NodeId] = {starting_location}
    changed = True
    while changed:
        changed = False
        for node_id in list(visited):
            for flag in flag_triggers.get(node_id, ()):
                if flag not in state.flags:
                    state.flags.add(flag)
                    changed = True
            for target_id, rule in edges.get(node_id, ()):
                if target_id in visited:
                    continue
                if rule is None or rule(state):
                    visited.add(target_id)
                    changed = True
    return visited


def _meets_progression_bar(
    world: "MetroidPrime2World",
    db: GameDatabase,
    compiler: RequirementCompiler,
    pickup_ids: frozenset[NodeId],
    starting_names: frozenset[str],
    candidate: DockRandoAssignment,
) -> bool:
    """``True`` iff ``candidate`` clears both coarse solvability bars: (1)
    the start state (only ``constants.DEFAULT_STARTING_ITEMS``) can reach
    at least ``_MIN_SPHERE_ZERO_PICKUPS`` pickups -- the check that would
    have caught 27/27 door-lock-rando seeds' total sphere-0 lockout -- and
    (2) every one of the 119 pickups remains reachable once every item is
    collected. Neither replaces the generator's own fill-time
    accessibility sweep over the real, fully item-gated region graph
    (which enforces the actual placement order, not just these two
    snapshots) -- this is a coarse, cheap-ish reject filter, same spirit
    as ``_reachable_nodes`` for elevators/teleporters, just item-aware."""
    probe_world = _ProbeWorld(world, candidate)
    edges, flag_triggers, event_names = _build_probe_graph(probe_world, db, compiler)

    start_state = _ProbeState(mode="start", event_names=event_names, starting_names=starting_names)
    start_reached = _probe_reachable(edges, flag_triggers, db.starting_location, start_state)
    if len(start_reached & pickup_ids) < _MIN_SPHERE_ZERO_PICKUPS:
        return False

    all_state = _ProbeState(mode="all", event_names=event_names, starting_names=starting_names)
    all_reached = _probe_reachable(edges, flag_triggers, db.starting_location, all_state)
    return pickup_ids <= all_reached


def _build_compiler(world: "MetroidPrime2World", db: GameDatabase) -> RequirementCompiler:
    ctx = build_static_context(
        player=world.player,
        trick_levels=world.trick_levels,
        damage_strictness=damage_strictness_multiplier(world.options),
        energy_per_tank=world.options.energy_per_tank.value,
        dark_aether_damage=dark_damage_per_second(world.options.dark_aether_damage.value),
        dark_suit_damage=dark_damage_per_second(world.options.dark_suit_damage.value),
        progressive_suit=bool(world.options.progressive_suit),
        progressive_grapple=bool(world.options.progressive_grapple),
    )
    return RequirementCompiler(db, ctx)


def build_door_lock_assignment(world: "MetroidPrime2World", db: GameDatabase) -> dict[NodeId, str]:
    """``{door_node_id: new_weakness_name}`` for every eligible door,
    empty when ``door_lock_rando`` is off. Reject-and-retries candidates
    (``_sample_door_lock_candidate``) against ``_meets_progression_bar``
    until one clears the bar or the attempt budget is exhausted -- see the
    module docstring for why the distribution shape alone isn't enough."""
    if not world.options.door_lock_rando:
        return {}

    pairs = _door_pairs(db)
    compiler = _build_compiler(world, db)
    pickup_ids = frozenset(node.id for node in db.all_nodes() if node.node_type == "pickup")
    starting_names = frozenset(constants.DEFAULT_STARTING_ITEMS)

    # Elevator/teleporter assignment hasn't been decided yet at this point
    # in build_dock_rando_assignment (door locks are built first) -- probe
    # against vanilla elevator/teleporter topology (DockRandoAssignment's
    # empty elevator/teleporter dicts, below). That pool gets its own
    # _meets_progression_bar check once it's built (see
    # build_elevator_and_teleporter_assignment), including this door lock
    # assignment once it's final, so the joint case is still covered.
    for _attempt in range(_MAX_DOOR_LOCK_ATTEMPTS):
        candidate_doors = _sample_door_lock_candidate(world, db, pairs)
        candidate = DockRandoAssignment(door_lock=candidate_doors)
        if _meets_progression_bar(world, db, compiler, pickup_ids, starting_names, candidate):
            return candidate_doors

    raise RuntimeError(
        "metroidprime2: could not find a solvable door lock assignment after "
        f"{_MAX_DOOR_LOCK_ATTEMPTS} attempts"
    )


def build_elevator_and_teleporter_assignment(
    world: "MetroidPrime2World", db: GameDatabase, door_lock: dict[NodeId, str]
) -> tuple[dict[NodeId, NodeId], dict[NodeId, NodeId]]:
    """Computes the elevator and teleporter target assignments together
    (a joint connectivity check is needed: whichever pool is off still
    contributes its *vanilla* connections to the graph the other pool is
    checked against). ``door_lock`` is this seed's already-finalized door
    lock assignment (empty if ``door_lock_rando`` is off), included in the
    ``_meets_progression_bar`` probe so this pool's check reflects the
    real combined graph. Returns ``(elevator_assignment,
    teleporter_assignment)``, each empty when its own option is off."""
    elevator_on = bool(world.options.elevator_rando)
    teleporter_on = bool(world.options.teleporter_rando)
    if not elevator_on and not teleporter_on:
        return {}, {}

    elevator_pairs = _reciprocal_pairs(db, "elevator", ELEVATOR_EXCLUDED_AP_NAMES) if elevator_on else []
    teleporter_pairs = _reciprocal_pairs(db, "teleporter", frozenset()) if teleporter_on else []

    # Every node that's part of either pool must stay reachable -- not
    # just "its region is reachable somehow" (see _reachable_nodes's
    # docstring for why that weaker check isn't enough).
    pool_endpoints = {node.id for pair in elevator_pairs for node in pair} | {
        node.id for pair in teleporter_pairs for node in pair
    }

    compiler = _build_compiler(world, db)
    pickup_ids = frozenset(node.id for node in db.all_nodes() if node.node_type == "pickup")
    starting_names = frozenset(constants.DEFAULT_STARTING_ITEMS)

    for _attempt in range(_MAX_SHUFFLE_ATTEMPTS):
        elevator_assignment = _shuffle_pairs(world, elevator_pairs) if elevator_pairs else {}
        teleporter_assignment = _shuffle_pairs(world, teleporter_pairs) if teleporter_pairs else {}

        # Cheap item-blind topology filter first -- rejects most bad
        # shuffles before paying for the expensive item-aware check below.
        reached = _reachable_nodes(db, elevator_assignment, teleporter_assignment)
        if not (pool_endpoints <= reached):
            continue

        candidate = DockRandoAssignment(
            door_lock=door_lock, elevator=elevator_assignment, teleporter=teleporter_assignment
        )
        if _meets_progression_bar(world, db, compiler, pickup_ids, starting_names, candidate):
            return elevator_assignment, teleporter_assignment

    raise RuntimeError(
        "metroidprime2: could not find a fully-connected, solvable elevator/teleporter "
        f"shuffle after {_MAX_SHUFFLE_ATTEMPTS} attempts"
    )


def build_dock_rando_assignment(world: "MetroidPrime2World") -> DockRandoAssignment:
    db = load_game_database()
    door_lock = build_door_lock_assignment(world, db)
    elevator, teleporter = build_elevator_and_teleporter_assignment(world, db, door_lock)
    return DockRandoAssignment(door_lock=door_lock, elevator=elevator, teleporter=teleporter)
