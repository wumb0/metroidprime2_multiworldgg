"""Tests for ``logic/dock_rando.py`` (door-lock/elevator/portal randomization):
pure-logic unit tests against a lightweight stand-in for
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
    _door_pairs,
    _portal_region_pairs,
    _reciprocal_pairs,
    build_door_lock_assignment,
    build_elevator_assignment,
    build_portal_assignment,
    save_station_door_faces,
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
        self.assertEqual({}, build_door_lock_assignment(world, db))  # type: ignore[arg-type]

    def test_off_returns_empty_regardless_of_save_station_protection(self) -> None:
        # door_lock_rando's short-circuit must come first regardless of
        # normal_save_station_doors's value -- the protection only ever
        # narrows a door-lock-rando assignment that door_lock_rando off
        # never produces in the first place.
        db = load_game_database()
        world = _FakeWorld(door_lock_rando=False, normal_save_station_doors=True)
        self.assertEqual({}, build_door_lock_assignment(world, db))  # type: ignore[arg-type]


class TestBuildElevatorAssignmentOff(unittest.TestCase):
    def test_off_returns_empty(self) -> None:
        db = load_game_database()
        world = _FakeWorld(elevator_rando=False)
        elevator = build_elevator_assignment(world, db, {})  # type: ignore[arg-type]
        self.assertEqual({}, elevator)


class TestBuildPortalAssignmentOff(unittest.TestCase):
    def test_off_returns_empty(self) -> None:
        db = load_game_database()
        world = _FakeWorld(portal_rando=False)
        portal, portal_weakness = build_portal_assignment(world, db, {}, {})  # type: ignore[arg-type]
        self.assertEqual({}, portal)
        self.assertEqual({}, portal_weakness)


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


class TestSaveStationDoorFaces(unittest.TestCase):
    """``save_station_door_faces`` is a pure function of the (static)
    vendored DB, so these don't need a generated world -- ``load_game_database``
    and ``_door_pairs`` are enough, same as the module-level constants
    above."""

    def test_returns_50_faces_from_18_areas(self) -> None:
        db = load_game_database()
        pairs = _door_pairs(db)
        faces = save_station_door_faces(db, pairs)

        # Exact numbers per PLAN.md / dock_rando.py's docstring: 18
        # save-station areas, 25 door nodes inside them, 25 distinct
        # _door_pairs partners, 50 faces total. Asserted exactly so a DB
        # resync that shrinks (or grows) this set fails loudly.
        save_station_areas = {
            (node_id.region, node_id.area) for node_id in db.starting_location_candidates("save_stations")
        }
        self.assertEqual(18, len(save_station_areas))

        inside = {node_id for node_id in faces if (node_id.region, node_id.area) in save_station_areas}
        self.assertEqual(25, len(inside))
        self.assertEqual(50, len(faces))

        for node_id in faces:
            node = db.node(node_id)
            self.assertEqual("dock", node.node_type)
            self.assertEqual("door", node.dock_type)


class TestBuildDoorLockAssignmentSaveStationProtection(MP2TestBase):
    """``normal_save_station_doors`` defaults on (``DefaultOnToggle``), so
    just turning on ``door_lock_rando`` is enough to exercise it."""

    options = {"door_lock_rando": True}

    def test_protected_faces_forced_to_normal_door(self) -> None:
        db = load_game_database()
        pairs = _door_pairs(db)
        protected = save_station_door_faces(db, pairs)
        assignment = build_door_lock_assignment(self.world, db)

        for node_id in protected:
            self.assertEqual(
                "Normal Door",
                assignment[node_id],
                f"{node_id.ap_name} is a protected save-station face but got a non-Normal lock",
            )

    def test_protected_pairs_still_agree(self) -> None:
        db = load_game_database()
        pairs = _door_pairs(db)
        protected = save_station_door_faces(db, pairs)
        assignment = build_door_lock_assignment(self.world, db)

        for node_id in protected:
            partner_id = pairs.get(node_id)
            if partner_id is not None and partner_id in assignment:
                self.assertEqual(
                    assignment[node_id],
                    assignment[partner_id],
                    f"{node_id.ap_name} and its physical pair partner {partner_id.ap_name} disagree",
                )


class TestBuildDoorLockAssignmentSaveStationProtectionOff(MP2TestBase):
    """With the option off, protected faces go back through the ordinary
    global weakness mapping like any other door -- this must NOT be
    vacuously true, so it draws several independent assignments (each
    call to ``build_door_lock_assignment`` advances ``self.world.random``,
    giving a fresh global mapping every time -- effectively a fresh seed
    per draw without needing WorldTestBase's seed-pinning, which
    test_fill.py's docstring notes isn't reliably available from a test
    method) and asserts over their union that at least one protected face
    ends up with something other than "Normal Door". In practice this
    passes on the very first draw: _global_weakness_mapping is a bijection
    (see its docstring), so at most one of the several vanilla weakness
    types among the protected faces ("Normal Door", "Missile Blast
    Shield", "Dark Door") can map to "Normal Door" in any given draw --
    the others are then guaranteed to be something else. The loop is kept
    anyway per the task's instruction to iterate rather than rely on a
    single seed."""

    options = {"door_lock_rando": True, "normal_save_station_doors": False}

    def test_option_off_does_not_force_every_protected_face_normal(self) -> None:
        db = load_game_database()
        pairs = _door_pairs(db)
        protected = save_station_door_faces(db, pairs)

        non_normal_faces: set = set()
        for _ in range(10):
            assignment = build_door_lock_assignment(self.world, db)
            non_normal_faces |= {
                node_id for node_id in protected if assignment.get(node_id) != "Normal Door"
            }
            if non_normal_faces:
                break

        self.assertTrue(
            non_normal_faces,
            "expected at least one protected save-station face to get a non-Normal lock "
            "across several draws with normal_save_station_doors off",
        )


class TestBuildElevatorAssignment(MP2TestBase):
    options = {"elevator_rando": True}

    def test_elevator_on_shuffles_every_eligible_node_reciprocally(self) -> None:
        db = load_game_database()
        elevator = build_elevator_assignment(self.world, db, {})

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

    def test_shuffle_keeps_every_pool_endpoint_reachable(self) -> None:
        from ..logic.dock_rando import _reachable_nodes

        db = load_game_database()
        elevator = build_elevator_assignment(self.world, db, {})

        pool_endpoints = set(elevator) | set(elevator.values())
        shuffled = _reachable_nodes(db, elevator)
        self.assertTrue(pool_endpoints <= shuffled)


class TestBuildPortalAssignment(MP2TestBase):
    options = {"portal_rando": True}

    def test_portal_on_shuffles_every_node_reciprocally_within_its_region_pair(self) -> None:
        db = load_game_database()
        portal, _portal_weakness = build_portal_assignment(self.world, db, {}, {})

        region_pairs = _portal_region_pairs(db)
        eligible_ids = {
            node.id for _name, light_nodes, dark_nodes in region_pairs for node in (*light_nodes, *dark_nodes)
        }
        self.assertEqual(66, len(eligible_ids))
        self.assertEqual(eligible_ids, set(portal))

        light_ids_by_pair = {name: {n.id for n in light_nodes} for name, light_nodes, _dark in region_pairs}
        dark_ids_by_pair = {name: {n.id for n in dark_nodes} for name, _light, dark_nodes in region_pairs}
        for node_id, target_id in portal.items():
            self.assertEqual(node_id, portal[target_id])  # reciprocal
            # Never crosses into a different region pair's nodes.
            for name, light_ids in light_ids_by_pair.items():
                if node_id in light_ids:
                    self.assertIn(target_id, dark_ids_by_pair[name])
                    break
            else:
                for name, dark_ids in dark_ids_by_pair.items():
                    if node_id in dark_ids:
                        self.assertIn(target_id, light_ids_by_pair[name])
                        break

    def test_no_return_portal_nodes_get_a_colored_weakness_override(self) -> None:
        db = load_game_database()
        _portal, portal_weakness = build_portal_assignment(self.world, db, {}, {})

        no_return_ids = {
            node.id
            for node in db.all_nodes()
            if node.node_type == "dock"
            and node.dock_type == "portal"
            and node.default_dock_weakness == "No Return Portal"
        }
        self.assertEqual(13, len(no_return_ids))
        self.assertEqual(no_return_ids, set(portal_weakness))
        for node_id, new_name in portal_weakness.items():
            region = db.regions[node_id.region]
            expected = "Dark Portal" if region.asset_id is not None else "Light Portal"
            self.assertEqual(expected, new_name)

    def test_other_portal_weaknesses_are_never_overridden(self) -> None:
        db = load_game_database()
        _portal, portal_weakness = build_portal_assignment(self.world, db, {}, {})
        for node in db.all_nodes():
            if node.node_type != "dock" or node.dock_type != "portal":
                continue
            if node.default_dock_weakness != "No Return Portal":
                self.assertNotIn(node.id, portal_weakness)

    def test_shuffle_keeps_every_pool_endpoint_reachable(self) -> None:
        from ..logic.dock_rando import _reachable_nodes

        db = load_game_database()
        portal, _portal_weakness = build_portal_assignment(self.world, db, {}, {})

        pool_endpoints = set(portal) | set(portal.values())
        reached = _reachable_nodes(db, {}, portal)
        self.assertTrue(pool_endpoints <= reached)


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


class TestPortalRandoStillGenerates(MP2TestBase):
    options = {"portal_rando": True}

    def test_all_pickups_reachable(self) -> None:
        state = self.multiworld.get_all_state()
        for location in self.multiworld.get_locations():
            self.assertTrue(location.can_reach(state), f"{location.name} unreachable")


class TestAllEntranceRandoTogetherStillGenerates(MP2TestBase):
    options = {"door_lock_rando": True, "elevator_rando": True, "portal_rando": True}

    def test_all_pickups_reachable(self) -> None:
        state = self.multiworld.get_all_state()
        for location in self.multiworld.get_locations():
            self.assertTrue(location.can_reach(state), f"{location.name} unreachable")


if __name__ == "__main__":
    unittest.main()
