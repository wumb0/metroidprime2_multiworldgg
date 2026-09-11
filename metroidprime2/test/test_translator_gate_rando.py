"""Tests for ``logic/translator_gate_rando.py`` (translator gate color
randomization): pure-logic unit tests against a lightweight stand-in for
``world`` (mirrors ``test_dock_rando.py``'s approach), plus integration-level
checks through a fully generated world (mirrors
``test_dock_rando.py``'s ``TestDoorLockRandoStillGenerates``) and the patch
data it produces (mirrors ``test_patch_data.py``).
"""

from __future__ import annotations

import random
import unittest

from .. import patch_data
from ..logic.db_reader import load_game_database
from ..logic.translator_gate_rando import (
    TRANSLATOR_COLORS,
    build_translator_gate_assignment,
    randomizable_gate_ids,
)
from ..options import TranslatorGateRando
from .bases import MP2TestBase
from .test_patch_data import _all_translator_gates


class _FakeOption:
    def __init__(self, value: int) -> None:
        self.value = value


class _FakeOptions:
    def __init__(self, translator_gate_rando: int) -> None:
        self.translator_gate_rando = _FakeOption(translator_gate_rando)


class _FakeWorld:
    def __init__(self, translator_gate_rando: int, seed: int = 0) -> None:
        self.options = _FakeOptions(translator_gate_rando)
        self.random = random.Random(seed)


class TestBuildTranslatorGateAssignment(unittest.TestCase):
    def test_vanilla_returns_empty(self) -> None:
        world = _FakeWorld(TranslatorGateRando.option_vanilla)
        self.assertEqual({}, build_translator_gate_assignment(world))  # type: ignore[arg-type]

    def test_full_random_assigns_every_randomizable_gate_a_color_never_unlocked(self) -> None:
        world = _FakeWorld(TranslatorGateRando.option_full_random, seed=1)
        assignment = build_translator_gate_assignment(world)  # type: ignore[arg-type]

        db = load_game_database()
        gate_ids = {node.id for node in db.all_nodes() if node.node_type == "configurable_node"}
        self.assertEqual(17, len(gate_ids))
        # 15 of the 17: the two gates randovania's prime2_opr starter preset
        # ships "removed" stay removed, because re-gating either one makes
        # the start unescapable (see logic/translator_gate_rando.py's
        # randomizable_gate_ids).
        self.assertEqual(set(randomizable_gate_ids(db)), set(assignment))
        self.assertEqual(15, len(assignment))
        self.assertEqual(
            {gate_id for gate_id in gate_ids if db.vanilla_translator_gates[gate_id] is None},
            gate_ids - set(assignment),
        )
        for color in assignment.values():
            self.assertIn(color, TRANSLATOR_COLORS)

    def test_full_random_unlocked_can_produce_none(self) -> None:
        # Deterministic seed search: confirm "Unlocked" (None) is actually a
        # reachable outcome of the 5-way choice, not merely permitted by the
        # type -- across enough seeds, with 17 independent 1-in-5 draws per
        # seed, at least one seed must produce a None somewhere.
        db = load_game_database()
        gate_count = sum(1 for node in db.all_nodes() if node.node_type == "configurable_node")
        self.assertEqual(17, gate_count)

        saw_none = False
        saw_color = False
        for seed in range(20):
            world = _FakeWorld(TranslatorGateRando.option_full_random_unlocked, seed=seed)
            assignment = build_translator_gate_assignment(world)  # type: ignore[arg-type]
            self.assertEqual(15, len(assignment))
            for color in assignment.values():
                self.assertTrue(color is None or color in TRANSLATOR_COLORS)
                if color is None:
                    saw_none = True
                else:
                    saw_color = True

        self.assertTrue(saw_none, "expected at least one Unlocked gate across 20 seeds * 17 gates")
        self.assertTrue(saw_color, "expected at least one colored gate across 20 seeds * 17 gates")


class TestTranslatorGateRandoStillGenerates(MP2TestBase):
    """No custom test methods needed beyond the explicit reachability check
    below -- MP2TestBase disables WorldTestBase's blanket auto-tests (see
    bases.py), so this mirrors test_dock_rando.py's
    TestDoorLockRandoStillGenerates pattern."""

    options = {"translator_gate_rando": "full_random_unlocked"}

    def test_all_pickups_reachable(self) -> None:
        state = self.multiworld.get_all_state()
        for location in self.multiworld.get_locations():
            self.assertTrue(location.can_reach(state), f"{location.name} unreachable")

    def test_patch_data_translator_gates_match_assignment(self) -> None:
        config = patch_data.make_rando_configuration(self.world)
        gates_by_translator: dict[str, int] = {}
        for gate in _all_translator_gates(config):
            gates_by_translator[gate["translator"]] = gates_by_translator.get(gate["translator"], 0) + 1

        self.assertEqual(17, sum(gates_by_translator.values()))
        # The 2 gates left out of the assignment fall back to their vanilla
        # "removed" -> "unlocked", so the patch data can carry "unlocked"
        # even when no assigned gate rolled it.
        assigned_colors = {
            (color.lower() if color is not None else "unlocked")
            for color in self.world.translator_gate_assignment.values()
        }
        self.assertEqual(assigned_colors | {"unlocked"}, set(gates_by_translator) | {"unlocked"})


if __name__ == "__main__":
    unittest.main()
