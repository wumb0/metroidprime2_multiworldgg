"""Tests for ``logic/dock_rando.py`` (door-lock/elevator/teleporter
randomization): pure-logic unit tests against a lightweight stand-in for
``world`` for the option-off/short-circuit paths (mirrors
``test_client_receive.py``'s approach), and against a fully generated
``MP2TestBase`` world (needed for the item-aware ``_meets_progression_bar``
probe, which reads ``world.trick_levels``/``world.options``/
``world.translator_gate_assignment``) for the "on" paths, plus
integration-level reachability checks through a fully generated world
(mirrors ``test_regions.py``'s ``TestVanillaPlacement``).
"""

from __future__ import annotations

import random
import unittest

from ..logic.db_reader import load_game_database
from ..logic.dock_rando import (
    DOOR_CAN_CHANGE_FROM,
    DOOR_CAN_CHANGE_TO,
    ELEVATOR_EXCLUDED_AP_NAMES,
    _reciprocal_pairs,
    build_door_lock_assignment,
    build_elevator_and_teleporter_assignment,
)
from .bases import MP2TestBase


class _FakeOptions:
    def __init__(self, **values: bool) -> None:
        self._values = values

    def __getattr__(self, name: str) -> bool:
        return self._values.get(name, False)


class _FakeWorld:
    """Only good for the option-off short-circuit paths, which return
    before touching anything beyond ``world.options``/``world.random``."""

    def __init__(self, seed: int = 0, **option_values: bool) -> None:
        self.options = _FakeOptions(**option_values)
        self.random = random.Random(seed)


class TestBuildDoorLockAssignmentOff(unittest.TestCase):
    def test_off_returns_empty(self) -> None:
        db = load_game_database()
        world = _FakeWorld(door_lock_rando=False)
        self.assertEqual({}, build_door_lock_assignment(world, db))


class TestBuildElevatorAndTeleporterAssignmentOff(unittest.TestCase):
    def test_both_off_returns_empty(self) -> None:
        db = load_game_database()
        world = _FakeWorld(elevator_rando=False, teleporter_rando=False)
        elevator, teleporter = build_elevator_and_teleporter_assignment(world, db, {})
        self.assertEqual({}, elevator)
        self.assertEqual({}, teleporter)


class TestBuildDoorLockAssignment(MP2TestBase):
    """Needs a fully generated world (not the bare ``_FakeWorld`` stand-in
    above): the reject-and-retry probe (``_meets_progression_bar``) reads
    ``world.trick_levels``, the real ``world.options`` Choice/Range
    objects, and ``world.translator_gate_assignment``."""

    options = {"door_lock_rando": True}

    def test_on_only_reassigns_eligible_doors_to_eligible_targets(self) -> None:
        db = load_game_database()
        assignment = build_door_lock_assignment(self.world, db)

        self.assertGreater(len(assignment), 0)
        for node_id, new_name in assignment.items():
            node = db.node(node_id)
            self.assertEqual("door", node.dock_type)
            self.assertIn(node.default_dock_weakness, DOOR_CAN_CHANGE_FROM)
            self.assertIn(new_name, DOOR_CAN_CHANGE_TO)

        # Every door whose vanilla weakness is eligible got reassigned --
        # none are silently skipped.
        eligible_ids = {
            node.id
            for node in db.all_nodes()
            if node.node_type == "dock"
            and node.dock_type == "door"
            and node.default_dock_weakness in DOOR_CAN_CHANGE_FROM
        }
        self.assertEqual(eligible_ids, set(assignment))

    def test_ineligible_doors_never_reassigned(self) -> None:
        db = load_game_database()
        assignment = build_door_lock_assignment(self.world, db)
        for node in db.all_nodes():
            if node.node_type != "dock" or node.dock_type != "door":
                continue
            if node.default_dock_weakness not in DOOR_CAN_CHANGE_FROM:
                self.assertNotIn(node.id, assignment)

    def test_paired_doors_share_the_same_new_weakness(self) -> None:
        from ..logic.dock_rando import _door_pairs

        db = load_game_database()
        assignment = build_door_lock_assignment(self.world, db)
        pairs = _door_pairs(db)
        for node_id, new_name in assignment.items():
            partner_id = pairs.get(node_id)
            if partner_id is not None and partner_id in assignment:
                self.assertEqual(
                    new_name,
                    assignment[partner_id],
                    f"{node_id.ap_name} and its physical pair partner {partner_id.ap_name} "
                    "got different weaknesses",
                )


class TestBuildElevatorAndTeleporterAssignment(MP2TestBase):
    options = {"elevator_rando": True}

    def test_elevator_on_shuffles_every_eligible_node_reciprocally(self) -> None:
        db = load_game_database()
        elevator, teleporter = build_elevator_and_teleporter_assignment(self.world, db, {})

        self.assertEqual({}, teleporter)
        # The Sky Temple one-way pair is excluded by the reciprocity check
        # itself, not the explicit exclusion list -- confirm both kinds of
        # exclusion actually took effect (22 total elevator nodes - 2
        # Sky Temple - 2 Aerie = 18 eligible, i.e. 9 pairs).
        expected_pairs = _reciprocal_pairs(db, "elevator", ELEVATOR_EXCLUDED_AP_NAMES)
        self.assertEqual(9, len(expected_pairs))
        eligible_ids = {node.id for pair in expected_pairs for node in pair}
        self.assertEqual(18, len(eligible_ids))
        self.assertEqual(eligible_ids, set(elevator))

        for node_id, target_id in elevator.items():
            self.assertEqual(node_id, elevator[target_id])  # reciprocal
            self.assertNotIn(node_id.ap_name, ELEVATOR_EXCLUDED_AP_NAMES)


class TestBuildTeleporterAssignment(MP2TestBase):
    options = {"teleporter_rando": True}

    def test_teleporter_on_shuffles_all_12_reciprocally(self) -> None:
        db = load_game_database()
        elevator, teleporter = build_elevator_and_teleporter_assignment(self.world, db, {})

        self.assertEqual({}, elevator)
        self.assertEqual(12, len(teleporter))
        for node_id, target_id in teleporter.items():
            self.assertEqual(node_id, teleporter[target_id])  # reciprocal


class TestCombinedElevatorTeleporterAssignment(MP2TestBase):
    options = {"elevator_rando": True, "teleporter_rando": True}

    def test_combined_shuffle_keeps_every_pool_endpoint_reachable(self) -> None:
        from ..logic.dock_rando import _reachable_nodes

        db = load_game_database()
        elevator, teleporter = build_elevator_and_teleporter_assignment(self.world, db, {})

        pool_endpoints = set(elevator) | set(elevator.values()) | set(teleporter) | set(teleporter.values())
        shuffled = _reachable_nodes(db, elevator, teleporter)
        self.assertTrue(pool_endpoints <= shuffled)


class TestDoorLockRandoStillGenerates(MP2TestBase):
    """No custom test methods needed beyond the explicit reachability
    check below -- MP2TestBase disables WorldTestBase's blanket auto-tests
    (see bases.py), so this mirrors TestVanillaPlacement's pattern instead
    of relying on them."""

    options = {"door_lock_rando": True}

    def test_all_pickups_reachable(self) -> None:
        state = self.multiworld.get_all_state()
        for location in self.multiworld.get_locations():
            self.assertTrue(location.can_reach(state), f"{location.name} unreachable")


class TestElevatorRandoStillGenerates(MP2TestBase):
    options = {"elevator_rando": True}

    def test_all_pickups_reachable(self) -> None:
        state = self.multiworld.get_all_state()
        for location in self.multiworld.get_locations():
            self.assertTrue(location.can_reach(state), f"{location.name} unreachable")


class TestTeleporterRandoStillGenerates(MP2TestBase):
    options = {"teleporter_rando": True}

    def test_all_pickups_reachable(self) -> None:
        state = self.multiworld.get_all_state()
        for location in self.multiworld.get_locations():
            self.assertTrue(location.can_reach(state), f"{location.name} unreachable")


class TestAllEntranceRandoTogetherStillGenerates(MP2TestBase):
    options = {"door_lock_rando": True, "elevator_rando": True, "teleporter_rando": True}

    def test_all_pickups_reachable(self) -> None:
        state = self.multiworld.get_all_state()
        for location in self.multiworld.get_locations():
            self.assertTrue(location.can_reach(state), f"{location.name} unreachable")


if __name__ == "__main__":
    unittest.main()
