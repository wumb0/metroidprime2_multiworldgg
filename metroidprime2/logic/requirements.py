"""Compiles randovania ``prime2`` logic-database requirement JSON into
Archipelago rule closures.

See ``PLAN.md`` section D for the full specification this module
implements (algorithm, negation policy, damage model). Nothing here imports
randovania or MultiWorldGG framework modules; a "state" is any object with
``has(name, player) -> bool`` and ``count(name, player) -> int``.
"""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import cast

from .. import constants
from . import item_mapping
from .db_reader import GameDatabase

Rule = Callable[[object], bool]


def combine_and(rules: list[Rule | None]) -> Rule | None:
    """AND together already-compiled ``Rule`` closures (as opposed to
    ``RequirementCompiler.compile_all``, which ANDs raw requirement JSON).
    ``None`` entries (statically True) are dropped; an empty/all-None list
    returns ``None``."""
    fs = [r for r in rules if r is not None]
    if not fs:
        return None
    if len(fs) == 1:
        return fs[0]

    def rule(s, _fs=tuple(fs)) -> bool:
        return all(f(s) for f in _fs)

    return rule


class Impossible(Exception):
    """Raised when a requirement subtree folds to the constant False.

    Constant True subtrees are instead represented as ``None`` ("no rule
    needed"); see module docstring / PLAN.md section D.
    """


# Events considered always-true by the new (patch_iso) OPR patcher; treated
# as pre-collected instead of requiring the player to reach the event node.
# (Kept as a module-level alias so callers can read it from one place.)
PREGRANTED_EVENTS = constants.PREGRANTED_EVENTS

# Negation policy hook for negated *event* requirements (~60 edges such as
# "not Event40" for the Grapple Guardian, or "not Event26" for the rotated
# Dark Forgotten Bridge). AP state is monotonic, so folding a negated event
# to False would delete the only pre-fight route into several boss arenas;
# folding to True is over-permissive only *after* the event has fired, which
# cannot make a seed unbeatable. Default: every negated event folds to True.
# Populate this dict (short_name -> desired constant) to override specific
# events found to need tighter logic.
NEGATED_EVENT_OVERRIDES: dict[str, bool] = {}

# DB items excluded from the v1 item pool; any positive requirement on one
# of these folds to Impossible regardless of the item's normal expression.
DEFAULT_ABSENT_ITEMS: frozenset[str] = frozenset(
    {"DoubleDamage", "UnlimitedMissiles", "UnlimitedBeamAmmo", "CannonBall"}
)

# Sentinel stored in the template memo to remember "this template raises
# Impossible" without re-raising-and-catching on every cache hit.
_TEMPLATE_IMPOSSIBLE = object()


@dataclass(frozen=True)
class StaticContext:
    player: int
    trick_levels: dict[str, int]
    misc: dict[str, int]
    versions: dict[str, int]
    pregranted_events: frozenset[str]
    damage_strictness: float
    energy_per_tank: int
    dark_world_base: float  # dark_aether_damage / 6.0
    dark_suit_multiplier: float  # dark_suit_damage / 6.0
    progressive_suit: bool
    progressive_grapple: bool
    absent_items: frozenset[str] = field(default_factory=frozenset)
    missile_expansions_unlock_launcher: bool = False


def build_static_context(
    player: int,
    trick_levels: dict[str, int],
    damage_strictness: float,
    energy_per_tank: int,
    dark_aether_damage: float,
    dark_suit_damage: float,
    progressive_suit: bool,
    progressive_grapple: bool,
    absent_items: frozenset[str] = DEFAULT_ABSENT_ITEMS,
    missile_expansions_unlock_launcher: bool = False,
) -> StaticContext:
    """Build a ``StaticContext`` from resolved option values.

    ``misc``, ``versions`` and ``pregranted_events`` are always filled from
    the frozen constants in ``constants.py`` (v1 has no room/door/gate
    rando, so these never vary per-seed).
    """
    return StaticContext(
        player=player,
        trick_levels=dict(trick_levels),
        misc=dict(constants.STATIC_MISC),
        versions=dict(constants.STATIC_VERSIONS),
        pregranted_events=frozenset(constants.PREGRANTED_EVENTS),
        damage_strictness=damage_strictness,
        energy_per_tank=energy_per_tank,
        dark_world_base=dark_aether_damage / 6.0,
        dark_suit_multiplier=dark_suit_damage / 6.0,
        progressive_suit=progressive_suit,
        progressive_grapple=progressive_grapple,
        absent_items=frozenset(absent_items),
        missile_expansions_unlock_launcher=missile_expansions_unlock_launcher,
    )


class RequirementCompiler:
    """Compiles randovania requirement JSON trees into ``Rule`` closures.

    No DNF expansion. Templates are memoised (with a recursion guard) since
    they nest and are referenced from many call sites.
    """

    def __init__(self, db: GameDatabase, ctx: StaticContext) -> None:
        self.db = db
        self.ctx = ctx
        self._template_cache: dict[str, Rule | object | None] = {}
        self._template_stack: set[str] = set()

    # -- public API --------------------------------------------------------

    def compile(self, req: dict | None) -> Rule | None:
        return self._compile(req)

    def compile_all(self, reqs: list[dict | None]) -> Rule | None:
        """AND of several requirements (e.g. a connection requirement plus
        a node's "leave" requirement). Propagates ``Impossible``."""
        return self._compile_and([r for r in reqs if r is not None])

    def compile_with_alternative(self, req: dict | None, item_name: str) -> Rule | None:
        """Compile ``req`` OR'd with ``state.has(item_name, player)``, where
        ``item_name`` is an AP-only item not present anywhere in the DB
        (used for dock lock-broken events; see ``regions.py``). Unlike a
        normal ``or`` node this alternative can never make the whole
        expression ``Impossible`` -- if ``req`` itself folds to False, the
        result is simply ``state.has(item_name, player)``."""
        try:
            compiled = self._compile(req)
        except Impossible:
            player = self.ctx.player

            def has_alternative(s, _n=item_name, _p=player) -> bool:
                return s.has(_n, _p)

            return has_alternative

        if compiled is None:
            return None  # req already statically True -> OR is True.

        player = self.ctx.player

        def combined(s, _r=compiled, _n=item_name, _p=player) -> bool:
            return _r(s) or s.has(_n, _p)

        return combined

    def compile_to_string(self, req: dict | None) -> str:
        """Debug pretty-printer: folds constant subtrees to True/False,
        leaves state-dependent subtrees as their JSON structure."""
        try:
            rule = self._compile(req)
        except Impossible:
            return "False"
        if rule is None:
            return "True"
        # rule is not None => _compile's own `if req is None: return None`
        # branch wasn't taken, so req can't be None here either.
        assert req is not None
        return self._describe(req)

    # -- core algorithm ------------------------------------------------------

    def _compile(self, req: dict | None) -> Rule | None:
        if req is None:
            return None
        req_type = req["type"]
        if req_type == "and":
            return self._compile_and(req["data"]["items"])
        if req_type == "or":
            return self._compile_or(req["data"]["items"])
        if req_type == "template":
            return self._compile_template(req["data"])
        if req_type == "resource":
            return self._compile_resource(req["data"])
        raise ValueError(f"unknown requirement type: {req_type!r}")

    def _compile_and(self, items: list[dict]) -> Rule | None:
        rules: list[Rule] = []
        for item in items:
            compiled = self._compile(item)  # Impossible propagates.
            if compiled is not None:
                rules.append(compiled)
        if not rules:
            return None
        if len(rules) == 1:
            return rules[0]

        def rule(s, _fs=tuple(rules)) -> bool:
            return all(f(s) for f in _fs)

        return rule

    def _compile_or(self, items: list[dict]) -> Rule | None:
        rules: list[Rule] = []
        for item in items:
            try:
                compiled = self._compile(item)
            except Impossible:
                continue
            if compiled is None:
                return None
            rules.append(compiled)
        if not rules:
            raise Impossible
        if len(rules) == 1:
            return rules[0]

        def rule(s, _fs=tuple(rules)) -> bool:
            return any(f(s) for f in _fs)

        return rule

    def _compile_template(self, name: str) -> Rule | None:
        if name in self._template_cache:
            cached = self._template_cache[name]
            if cached is _TEMPLATE_IMPOSSIBLE:
                raise Impossible
            return cached  # type: ignore[return-value]

        if name in self._template_stack:
            raise RuntimeError(f"requirement template recursion detected: {name!r}")

        self._template_stack.add(name)
        try:
            req = self.db.requirement_templates[name]
            try:
                compiled = self._compile(req)
            except Impossible:
                self._template_cache[name] = _TEMPLATE_IMPOSSIBLE
                raise
            self._template_cache[name] = compiled
            return compiled
        finally:
            self._template_stack.discard(name)

    def _compile_resource(self, data: dict) -> Rule | None:
        rtype = data["type"]
        name = data["name"]
        amount = data["amount"]
        negate = bool(data.get("negate", False))

        if rtype in ("tricks", "misc", "versions"):
            ctx_map = {
                "tricks": self.ctx.trick_levels,
                "misc": self.ctx.misc,
                "versions": self.ctx.versions,
            }[rtype]
            value = ctx_map.get(name, 0)
            satisfied = value >= amount
            if negate:
                satisfied = not satisfied
            if satisfied:
                return None
            raise Impossible

        if rtype == "events":
            return self._compile_event(name, negate)

        if rtype == "items":
            return self._compile_item(name, amount, negate)

        if rtype == "damage":
            assert not negate, f"damage requirement {name!r} must not be negated"
            return self._compile_damage(name, amount)

        raise ValueError(f"unknown resource type: {rtype!r}")

    def _compile_event(self, name: str, negate: bool) -> Rule | None:
        # Negation policy applies uniformly regardless of pregrant status:
        # fold "not EventX" to True unless explicitly overridden. This
        # matters even for pregranted events -- e.g. Event73 ("Dynamo
        # Chamber Gates", pregranted under the new patcher) is the *target*
        # event of its own node's incoming requirement, which includes a
        # self-referential "not Event73" branch meaning "this is free to
        # reach the first time, before it has been triggered" (a randovania
        # idiom, not a real dependency on Event73's own eventual truth
        # value). Treating a pregranted event's negation as constant False
        # (the naive reading: pregranted -> always true -> negated -> always
        # false) makes that node's sole incoming edge permanently
        # Impossible, stranding it and everything only reachable through it
        # -- confirmed against randovania's own resolver semantics (see
        # test/test_regions.py's vanilla-placement test) and consistent
        # with the general "AP state is monotonic" reasoning already
        # documented above for the ~60 non-pregranted negated-event edges.
        if negate:
            if NEGATED_EVENT_OVERRIDES.get(name, True):
                return None
            raise Impossible

        if name in self.ctx.pregranted_events:
            return None  # pregranted -> always satisfied.

        item_name = item_mapping.event_item_name(self.db, name)
        player = self.ctx.player

        def rule(s, _n=item_name, _p=player) -> bool:
            return s.has(_n, _p)

        return rule

    def _compile_item(self, name: str, amount: int, negate: bool) -> Rule | None:
        # Negation policy: negated items fold to False (each observed
        # negated-item edge guards a trick alternative inside an `or` that
        # has item-positive alternatives; see PLAN.md section D).
        if negate:
            raise Impossible

        if name in self.ctx.absent_items:
            raise Impossible

        kind, fn = item_mapping.expression(
            name, self.ctx.player, self.ctx.missile_expansions_unlock_launcher
        )

        if kind == "bool":
            if amount <= 0:
                return None
            if amount > 1:
                # A boolean item can never satisfy amount > 1.
                raise Impossible
            # item_mapping.expression's return type is deliberately kind-erased
            # (Callable[[object], object]); "bool" is its contract for a
            # bool-returning callable (see that module's Kind/Expression docs).
            return cast(Rule, fn)

        if kind == "count":
            if amount <= 0:
                return None

            def rule(s, _fn=fn, _amt=amount) -> bool:
                return cast(int, _fn(s)) >= _amt

            return rule

        if kind == "const":
            value = cast(int, fn(None))
            if value >= amount:
                return None
            raise Impossible

        raise ValueError(f"unknown item expression kind: {kind!r}")

    def _compile_damage(self, name: str, amount: int) -> Rule | None:
        amt = int(amount * self.ctx.damage_strictness)
        if amt <= 0:
            return None

        reductions = self._reductions_for(name)
        player = self.ctx.player
        energy_per_tank = self.ctx.energy_per_tank

        def rule(
            s,
            _amt=amt,
            _e=energy_per_tank,
            _p=player,
            _reductions=reductions,
        ) -> bool:
            mults = [
                mult
                for (count_fn, quantity, mult) in _reductions
                if count_fn is None or count_fn(s) >= quantity
            ]
            reduction = min(mults) if mults else 1.0
            energy = (_e - 1) + _e * s.count("Energy Tank", _p)
            return math.ceil(reduction * _amt) < energy

        return rule

    def _reductions_for(self, name: str) -> list[tuple[Callable[[object], int] | None, int, float]]:
        player = self.ctx.player

        if name == "DarkWorld1":
            raw: list[tuple[str | None, int, float]] = [
                (None, 1, self.ctx.dark_world_base),
                ("DarkSuit", 1, self.ctx.dark_suit_multiplier),
                ("LightSuit", 1, 0.0),
            ]
        else:
            raw = [
                (r.item_short_name, r.quantity, r.multiplier)
                for r in self.db.damage_reductions.get(name, [])
            ]

        result: list[tuple[Callable[[object], int] | None, int, float]] = []
        for item_short_name, quantity, multiplier in raw:
            if item_short_name is None:
                result.append((None, quantity, multiplier))
                continue
            kind, fn = item_mapping.expression(
                item_short_name, player, self.ctx.missile_expansions_unlock_launcher
            )
            count_fn: Callable[[object], int]
            if kind == "bool":
                def count_fn(s, _fn=fn):
                    return 1 if _fn(s) else 0
            elif kind == "count":
                count_fn = cast(Callable[[object], int], fn)
            else:  # "const"
                const_value = cast(int, fn(None))
                def count_fn(s, _v=const_value):
                    return _v
            result.append((count_fn, quantity, multiplier))
        return result

    # -- debug pretty-printing ------------------------------------------------

    def _describe(self, req: dict) -> str:
        req_type = req["type"]
        if req_type == "and":
            return "(" + " and ".join(self._describe_fold(i) for i in req["data"]["items"]) + ")"
        if req_type == "or":
            return "(" + " or ".join(self._describe_fold(i) for i in req["data"]["items"]) + ")"
        if req_type == "template":
            return f"[{req['data']}]"
        if req_type == "resource":
            data = req["data"]
            prefix = "not " if data.get("negate") else ""
            return f"{prefix}{data['type']}:{data['name']}>={data['amount']}"
        return repr(req)

    def _describe_fold(self, item: dict) -> str:
        try:
            rule = self._compile(item)
        except Impossible:
            return "False"
        if rule is None:
            return "True"
        return self._describe(item)
