"""Unit tests for logic/requirements.py and logic/item_mapping.py.

Plain ``unittest`` against a fake state object; no MultiWorldGG imports,
except ``TestDefaultDarkDamageOptionsMatchRandovania`` below, which needs
``options.py``'s ``DarkAetherDamage``/``DarkSuitDamage`` defaults and
``dark_damage_per_second()`` conversion helper (``options.py`` only pulls in
MultiWorldGG's lightweight ``Options`` module, not ``CommonClient``/
``AutoWorld``).
"""

from __future__ import annotations

import unittest

from ..logic.db_reader import load_game_database
from ..logic.requirements import (
    Impossible,
    RequirementCompiler,
    build_static_context,
)
from ..options import DarkAetherDamage, DarkSuitDamage, dark_damage_per_second

PLAYER = 1


class FakeState:
    """Minimal stand-in for AP's CollectionState: ``has``/``count`` backed
    by a plain dict of item-name -> quantity owned."""

    def __init__(self, counts: dict[str, int] | None = None):
        self._counts = dict(counts or {})

    def has(self, name: str, player: int) -> bool:
        assert player == PLAYER
        return self._counts.get(name, 0) > 0

    def count(self, name: str, player: int) -> int:
        assert player == PLAYER
        return self._counts.get(name, 0)


def _resource(rtype: str, name: str, amount: int = 1, negate: bool = False) -> dict:
    return {
        "type": "resource",
        "data": {"type": rtype, "name": name, "amount": amount, "negate": negate},
    }


def _and(*items: dict) -> dict:
    return {"type": "and", "data": {"comment": None, "items": list(items)}}


def _or(*items: dict) -> dict:
    return {"type": "or", "data": {"comment": None, "items": list(items)}}


class RequirementsTestBase(unittest.TestCase):
    def setUp(self) -> None:
        self.db = load_game_database()
        # dark_aether_damage=6, dark_suit_damage=1.2 reproduce randovania's
        # own default preset values (dark_world_base == 1.0,
        # dark_suit_multiplier == 0.2) so the damage tests below have clean
        # expected numbers.
        self.ctx = build_static_context(
            player=PLAYER,
            trick_levels={},
            damage_strictness=1.5,
            energy_per_tank=100,
            dark_aether_damage=6.0,
            dark_suit_damage=1.2,
            progressive_suit=False,
            progressive_grapple=False,
        )
        self.compiler = RequirementCompiler(self.db, self.ctx)


class TestAllTemplatesCompile(RequirementsTestBase):
    def test_every_template_compiles(self) -> None:
        for name, req in self.db.requirement_templates.items():
            with self.subTest(template=name):
                # Must not raise (Impossible included): result may be None
                # (constant True) or a closure.
                result = self.compiler.compile(req)
                self.assertTrue(result is None or callable(result))


class TestOpenNormalDoor(RequirementsTestBase):
    def test_passes_with_power_beam_only(self) -> None:
        req = self.db.requirement_templates["Open Normal Door"]
        rule = self.compiler.compile(req)
        assert rule is not None
        state = FakeState({"Power Beam": 1})
        self.assertTrue(rule(state))


class TestShootDarkburst(RequirementsTestBase):
    def _rule(self):
        req = self.db.requirement_templates["Shoot Darkburst"]
        rule = self.compiler.compile(req)
        assert rule is not None
        return rule

    def test_fails_without_missile_launcher(self) -> None:
        rule = self._rule()
        state = FakeState(
            {
                "Darkburst": 1,
                "Dark Beam": 1,
                "Charge Beam": 1,
            }
        )
        self.assertFalse(rule(state))

    def test_passes_with_missile_launcher(self) -> None:
        rule = self._rule()
        state = FakeState(
            {
                "Darkburst": 1,
                "Dark Beam": 1,
                "Charge Beam": 1,
                "Missile Launcher": 1,
            }
        )
        self.assertTrue(rule(state))


class TestDamageDarkWorld1(RequirementsTestBase):
    def test_amount_60_passes_with_zero_tanks(self) -> None:
        # int(60 * 1.5) == 90; energy with 0 tanks == 99; 90 < 99.
        req = _resource("damage", "DarkWorld1", amount=60)
        rule = self.compiler.compile(req)
        assert rule is not None
        self.assertTrue(rule(FakeState()))

    def test_amount_70_fails_with_zero_tanks(self) -> None:
        # int(70 * 1.5) == 105; energy with 0 tanks == 99; 105 < 99 is False.
        req = _resource("damage", "DarkWorld1", amount=70)
        rule = self.compiler.compile(req)
        assert rule is not None
        self.assertFalse(rule(FakeState()))

    def test_amount_70_passes_with_one_energy_tank(self) -> None:
        # energy with 1 tank == 199; 105 < 199.
        req = _resource("damage", "DarkWorld1", amount=70)
        rule = self.compiler.compile(req)
        assert rule is not None
        self.assertTrue(rule(FakeState({"Energy Tank": 1})))

    def test_amount_70_passes_with_dark_suit_and_zero_tanks(self) -> None:
        # reduction == 0.2 (dark_suit_multiplier); ceil(105 * 0.2) == 21 < 99.
        req = _resource("damage", "DarkWorld1", amount=70)
        rule = self.compiler.compile(req)
        assert rule is not None
        self.assertTrue(rule(FakeState({"Dark Suit": 1})))

    def test_amount_70_always_passes_with_light_suit(self) -> None:
        req = _resource("damage", "DarkWorld1", amount=70)
        rule = self.compiler.compile(req)
        assert rule is not None
        self.assertTrue(rule(FakeState({"Light Suit": 1})))


class TestMissileExpansionsUnlockLauncher(unittest.TestCase):
    """A ``Missile`` resource requirement of amount 5 is unsatisfied by 2
    Missile Expansions alone with the option off (matching Randovania: no
    Missile Launcher means 0 missile capacity), and satisfied with it on
    (PLAN.md section M) -- item_mapping.expression's Missile branch counts
    expansions toward capacity without the launcher when the flag is set."""

    def _compiler(self, missile_expansions_unlock_launcher: bool) -> RequirementCompiler:
        db = load_game_database()
        ctx = build_static_context(
            player=PLAYER,
            trick_levels={},
            damage_strictness=1.5,
            energy_per_tank=100,
            dark_aether_damage=6.0,
            dark_suit_damage=1.2,
            progressive_suit=False,
            progressive_grapple=False,
            missile_expansions_unlock_launcher=missile_expansions_unlock_launcher,
        )
        return RequirementCompiler(db, ctx)

    def test_unsatisfied_by_two_expansions_when_flag_off(self) -> None:
        compiler = self._compiler(False)
        req = _resource("items", "Missile", amount=5)
        rule = compiler.compile(req)
        assert rule is not None
        self.assertFalse(rule(FakeState({"Missile Expansion": 2})))

    def test_satisfied_by_two_expansions_when_flag_on(self) -> None:
        compiler = self._compiler(True)
        req = _resource("items", "Missile", amount=5)
        rule = compiler.compile(req)
        assert rule is not None
        self.assertTrue(rule(FakeState({"Missile Expansion": 2})))

    def test_missile_launcher_item_requirement_honors_the_flag(self) -> None:
        # The DB gates 15 requirement sites on the `MissileLauncher` *item*
        # rather than on Missile capacity (the `Destroy Seeker Locks` and
        # `Destroy Underwater Seeker Locks` templates in header.json), so
        # that expression has to widen with the option too -- otherwise
        # logic stays stricter than the patched game, which really does set
        # the launcher flag for an expansion holder.
        req = _resource("items", "MissileLauncher", amount=1)
        state = FakeState({"Missile Expansion": 1})

        rule_off = self._compiler(False).compile(req)
        assert rule_off is not None
        self.assertFalse(rule_off(state))

        rule_on = self._compiler(True).compile(req)
        assert rule_on is not None
        self.assertTrue(rule_on(state))

    def test_real_seeker_lock_template_honors_the_flag(self) -> None:
        # End-to-end through the actual vendored template, not a
        # hand-written stand-in: Seeker Launcher + one expansion is enough
        # to break a Seeker Lock in the patched game once the option is on.
        req = {"type": "template", "data": "Destroy Seeker Locks"}
        state = FakeState(
            {"Missile Expansion": 1, "Seeker Launcher": 1, "Combat Visor": 1}
        )

        rule_off = self._compiler(False).compile(req)
        assert rule_off is not None
        self.assertFalse(rule_off(state))

        rule_on = self._compiler(True).compile(req)
        assert rule_on is not None
        self.assertTrue(rule_on(state))

    def test_real_seeker_lock_template_still_needs_seekers(self) -> None:
        # The option widens only the launcher half; a Seeker Lock still
        # needs the Seeker Launcher.
        req = {"type": "template", "data": "Destroy Seeker Locks"}
        rule = self._compiler(True).compile(req)
        assert rule is not None
        self.assertFalse(rule(FakeState({"Missile Expansion": 4, "Combat Visor": 1})))


class TestPowerBombExpansionsUnlockPowerBombs(unittest.TestCase):
    """A ``PowerBomb`` resource requirement of amount 1 is unsatisfied by 2
    Power Bomb Expansions alone with the option off (matching Randovania:
    no Power Bomb main pickup means 0 power bomb capacity), and satisfied
    with it on (PLAN.md section M) -- item_mapping.expression's PowerBomb
    branch counts expansions toward capacity without the main pickup when
    the flag is set. Unlike missiles, there is no second gated resource to
    check here: the logic database has no main-item resource for power
    bombs at all, so the entire gate lives in this one branch."""

    def _compiler(self, power_bomb_expansions_unlock_power_bombs: bool) -> RequirementCompiler:
        db = load_game_database()
        ctx = build_static_context(
            player=PLAYER,
            trick_levels={},
            damage_strictness=1.5,
            energy_per_tank=100,
            dark_aether_damage=6.0,
            dark_suit_damage=1.2,
            progressive_suit=False,
            progressive_grapple=False,
            power_bomb_expansions_unlock_power_bombs=power_bomb_expansions_unlock_power_bombs,
        )
        return RequirementCompiler(db, ctx)

    def test_unsatisfied_by_two_expansions_when_flag_off(self) -> None:
        compiler = self._compiler(False)
        req = _resource("items", "PowerBomb", amount=1)
        rule = compiler.compile(req)
        assert rule is not None
        self.assertFalse(rule(FakeState({"Power Bomb Expansion": 2})))

    def test_satisfied_by_two_expansions_when_flag_on(self) -> None:
        compiler = self._compiler(True)
        req = _resource("items", "PowerBomb", amount=1)
        rule = compiler.compile(req)
        assert rule is not None
        self.assertTrue(rule(FakeState({"Power Bomb Expansion": 2})))

    def test_amount_four_needs_four_expansions_when_flag_on(self) -> None:
        compiler = self._compiler(True)
        req = _resource("items", "PowerBomb", amount=4)
        rule = compiler.compile(req)
        assert rule is not None
        self.assertFalse(rule(FakeState({"Power Bomb Expansion": 3})))
        self.assertTrue(rule(FakeState({"Power Bomb Expansion": 4})))


class TestNegationPolicy(RequirementsTestBase):
    def test_negated_event_compiles_to_none(self) -> None:
        # Event1 ("Industrial Site Gate") is not pre-granted; the default
        # negation policy folds a negated, non-pregranted event to True.
        req = _resource("events", "Event1", negate=True)
        self.assertIsNone(self.compiler.compile(req))

    def test_negated_item_raises_impossible(self) -> None:
        req = _resource("items", "Dark", negate=True)
        with self.assertRaises(Impossible):
            self.compiler.compile(req)

    def test_negated_misc_room_rando_compiles_to_none(self) -> None:
        req = {
            "type": "resource",
            "data": {"type": "misc", "name": "RoomRando", "amount": 1, "negate": True},
        }
        self.assertIsNone(self.compiler.compile(req))


class TestTrickResource(RequirementsTestBase):
    def test_amount_2_none_when_level_2(self) -> None:
        compiler = RequirementCompiler(
            self.db,
            build_static_context(
                player=PLAYER,
                trick_levels={"Dash": 2},
                damage_strictness=1.5,
                energy_per_tank=100,
                dark_aether_damage=6.0,
                dark_suit_damage=1.2,
                progressive_suit=False,
                progressive_grapple=False,
            ),
        )
        req = _resource("tricks", "Dash", amount=2)
        self.assertIsNone(compiler.compile(req))

    def test_amount_2_impossible_when_level_1(self) -> None:
        compiler = RequirementCompiler(
            self.db,
            build_static_context(
                player=PLAYER,
                trick_levels={"Dash": 1},
                damage_strictness=1.5,
                energy_per_tank=100,
                dark_aether_damage=6.0,
                dark_suit_damage=1.2,
                progressive_suit=False,
                progressive_grapple=False,
            ),
        )
        req = _resource("tricks", "Dash", amount=2)
        with self.assertRaises(Impossible):
            compiler.compile(req)


class TestAndOrFolding(RequirementsTestBase):
    def test_or_all_impossible_raises_impossible(self) -> None:
        req = _or(
            _resource("items", "Dark", negate=True),
            _resource("items", "Light", negate=True),
        )
        with self.assertRaises(Impossible):
            self.compiler.compile(req)

    def test_and_with_none_child_and_closure_returns_closure(self) -> None:
        # RoomRando negated -> None (constant True); "Dark" positive -> a
        # real closure. The AND of the two should behave exactly like the
        # single closure, without needing both children evaluated as an
        # all()-wrapped tuple.
        none_leaf = {
            "type": "resource",
            "data": {"type": "misc", "name": "RoomRando", "amount": 1, "negate": True},
        }
        item_leaf = _resource("items", "Dark", amount=1)
        req = _and(none_leaf, item_leaf)
        rule = self.compiler.compile(req)
        self.assertTrue(callable(rule))
        assert rule is not None  # narrows for mypy; assertTrue above is the real check
        self.assertTrue(rule(FakeState({"Dark Beam": 1})))
        self.assertFalse(rule(FakeState()))


class TestCompileToString(RequirementsTestBase):
    def test_runs_without_error(self) -> None:
        req = self.db.requirement_templates["Open Normal Door"]
        text = self.compiler.compile_to_string(req)
        self.assertIsInstance(text, str)


class TestDefaultDarkDamageOptionsMatchRandovania(unittest.TestCase):
    """``DarkAetherDamage``/``DarkSuitDamage`` (options.py) are stored in
    tenths of a point/second so the integer-only ``Range`` option can
    express randovania's fractional Dark Suit default (1.2) exactly. This
    runs the two option *defaults* through ``dark_damage_per_second()`` and
    then ``build_static_context()`` exactly as ``logic/regions.py`` and
    ``logic/dock_rando.py`` do, and checks the result reproduces
    randovania's starter-preset behaviour (``dark_world_base == 1.0``,
    ``dark_suit_multiplier == 0.2``) -- i.e. the shipped default is never
    more permissive than randovania's, unlike the old integer-only
    ``dark_suit_damage=1`` default this replaces."""

    def test_defaults_reproduce_randovania_starter_preset(self) -> None:
        dark_aether_damage = dark_damage_per_second(DarkAetherDamage.default)
        dark_suit_damage = dark_damage_per_second(DarkSuitDamage.default)
        self.assertEqual(6.0, dark_aether_damage)
        self.assertEqual(1.2, dark_suit_damage)

        ctx = build_static_context(
            player=PLAYER,
            trick_levels={},
            damage_strictness=1.5,
            energy_per_tank=100,
            dark_aether_damage=dark_aether_damage,
            dark_suit_damage=dark_suit_damage,
            progressive_suit=False,
            progressive_grapple=False,
        )
        self.assertAlmostEqual(1.0, ctx.dark_world_base)
        self.assertAlmostEqual(0.2, ctx.dark_suit_multiplier)


if __name__ == "__main__":
    unittest.main()
