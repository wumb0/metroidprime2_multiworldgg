"""M0 tests: verify the vendored logic database parses correctly and matches
the facts recorded in PLAN.md (Context / section K, milestone M0).

Plain unittest.TestCase -- no WorldTestBase / AutoWorld dependency yet,
since this world does not register a World subclass until M1.
"""

from __future__ import annotations

import unittest

from ..constants import LANDING_SITE_MREA, REGION_MLVL_IDS
from ..logic.db_reader import GameDatabase, _iter_template_names, load_game_database


class TestDbReader(unittest.TestCase):
    db: GameDatabase

    @classmethod
    def setUpClass(cls) -> None:
        cls.db = load_game_database()

    def test_node_count(self) -> None:
        self.assertEqual(1109, sum(1 for _ in self.db.all_nodes()))

    def test_pickup_indices_contiguous(self) -> None:
        pickups = self.db.pickup_nodes()
        self.assertEqual(119, len(pickups))
        self.assertEqual(list(range(119)), [n.pickup_index for n in pickups])

    def test_event_names(self) -> None:
        self.assertEqual(111, len(self.db.events))

        event_nodes = [n for n in self.db.all_nodes() if n.node_type == "event"]
        self.assertEqual(116, len(event_nodes))
        distinct_event_names = {n.event_name for n in event_nodes}
        self.assertEqual(111, len(distinct_event_names))
        # every event node's event_name is a known event resource
        self.assertTrue(distinct_event_names.issubset(self.db.events.keys()))

    def test_trick_count(self) -> None:
        self.assertEqual(25, len(self.db.tricks))

    def test_requirement_template_count(self) -> None:
        self.assertEqual(19, len(self.db.requirement_templates))

    def test_every_dock_default_connection_resolves(self) -> None:
        dock_nodes = [n for n in self.db.all_nodes() if n.node_type == "dock"]
        self.assertGreater(len(dock_nodes), 0)
        for node in dock_nodes:
            self.assertIsNotNone(node.default_connection, msg=f"{node.ap_name} has no default_connection")
            target = node.default_connection
            self.assertIn(target.region, self.db.regions)
            region = self.db.regions[target.region]
            self.assertIn(target.area, region.areas, msg=f"{node.ap_name} -> {target.ap_name}")
            area = region.areas[target.area]
            self.assertIn(target.node, area.nodes, msg=f"{node.ap_name} -> {target.ap_name}")

            # every dock also has a resolvable default_dock_weakness
            key = (node.dock_type, node.default_dock_weakness)
            self.assertIn(key, self.db.dock_weaknesses, msg=f"{node.ap_name}: unknown weakness {key}")

    def test_mlvl_ids(self) -> None:
        mlvl_ids = {self.db.mlvl_for_region(name) for name in self.db.regions}
        self.assertEqual(5, len(mlvl_ids))
        self.assertEqual(REGION_MLVL_IDS, set(mlvl_ids))

        # dark regions resolve to their light counterpart's MLVL
        dark_to_light = {
            "Sky Temple Grounds": "Temple Grounds",
            "Dark Agon Wastes": "Agon Wastes",
            "Dark Torvus Bog": "Torvus Bog",
            "Ing Hive": "Sanctuary Fortress",
            "Sky Temple": "Great Temple",
        }
        for dark, light in dark_to_light.items():
            self.assertIsNone(self.db.regions[dark].asset_id, msg=f"{dark} unexpectedly has its own asset_id")
            self.assertEqual(
                self.db.mlvl_for_region(light),
                self.db.mlvl_for_region(dark),
                msg=f"{dark} does not resolve to {light}'s MLVL",
            )

    def test_landing_site_mrea(self) -> None:
        landing_site = self.db.regions["Temple Grounds"].areas["Landing Site"]
        self.assertEqual(LANDING_SITE_MREA, landing_site.asset_id)
        self.assertEqual(1655756413, landing_site.asset_id)

    def test_every_referenced_template_exists(self) -> None:
        referenced: set[str] = set()
        for node in self.db.all_nodes():
            for req in node.connections.values():
                referenced.update(_iter_template_names(req))
            referenced.update(_iter_template_names(node.override_default_open_requirement))
            referenced.update(_iter_template_names(node.override_default_lock_requirement))
            referenced.update(_iter_template_names(node.requirement_to_collect))
        for template_req in self.db.requirement_templates.values():
            referenced.update(_iter_template_names(template_req))
        for weakness in self.db.dock_weaknesses.values():
            referenced.update(_iter_template_names(weakness.requirement))
            referenced.update(_iter_template_names(weakness.lock_requirement))
        referenced.update(_iter_template_names(self.db.victory_condition))

        self.assertTrue(len(referenced) > 0)
        self.assertTrue(referenced.issubset(self.db.requirement_templates.keys()))


if __name__ == "__main__":
    unittest.main()
