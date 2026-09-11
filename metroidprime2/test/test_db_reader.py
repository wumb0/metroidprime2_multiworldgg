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
        self.assertEqual(1104, sum(1 for _ in self.db.all_nodes()))

    def test_pickup_indices_contiguous(self) -> None:
        pickups = self.db.pickup_nodes()
        self.assertEqual(119, len(pickups))
        self.assertEqual(list(range(119)), [n.pickup_index for n in pickups])

    def test_event_names(self) -> None:
        self.assertEqual(111, len(self.db.events))

        event_nodes = [n for n in self.db.all_nodes() if n.node_type == "event"]
        self.assertEqual(115, len(event_nodes))
        distinct_event_names = {n.event_name for n in event_nodes}
        self.assertEqual(110, len(distinct_event_names))
        # every event node's event_name is a known event resource
        self.assertTrue(distinct_event_names.issubset(self.db.events.keys()))

    def test_trick_count(self) -> None:
        self.assertEqual(25, len(self.db.tricks))

    def test_requirement_template_count(self) -> None:
        self.assertEqual(20, len(self.db.requirement_templates))

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

    def test_light_dark_regions(self) -> None:
        light, dark = self.db.light_dark_regions()
        self.assertEqual(
            {"Dark Agon Wastes", "Dark Torvus Bog", "Ing Hive", "Sky Temple", "Sky Temple Grounds"},
            set(dark),
        )
        self.assertEqual(
            {"Agon Wastes", "Great Temple", "Sanctuary Fortress", "Temple Grounds", "Torvus Bog"},
            set(light),
        )
        self.assertEqual(set(self.db.regions), light | dark)

    def test_save_station_starting_location_candidates(self) -> None:
        # The 18 save-station rooms verified against a real ISO
        # (options.py's StartingRoom docstring / PLAN.md): one or two per
        # region, including every dark region -- 9 light, 9 dark.
        expected = {
            ("Agon Wastes", "Save Station A"),
            ("Agon Wastes", "Save Station C"),
            ("Dark Agon Wastes", "Save Station 1"),
            ("Dark Agon Wastes", "Save Station 2"),
            ("Dark Agon Wastes", "Save Station 3"),
            ("Dark Torvus Bog", "Dark Falls"),
            ("Dark Torvus Bog", "Save Station 1"),
            ("Dark Torvus Bog", "Save Station 2"),
            ("Great Temple", "Transport A Access"),
            ("Ing Hive", "Hive Save Station 1"),
            ("Ing Hive", "Hive Save Station 2"),
            ("Sanctuary Fortress", "Save Station A"),
            ("Sanctuary Fortress", "Save Station B"),
            ("Sky Temple", "Sky Temple Energy Controller"),
            ("Temple Grounds", "Hive Save Station"),
            ("Temple Grounds", "Landing Site"),
            ("Torvus Bog", "Save Station A"),
            ("Torvus Bog", "Save Station B"),
        }
        candidates = self.db.starting_location_candidates("save_stations")
        self.assertEqual(18, len(candidates))
        self.assertEqual(expected, {(c.region, c.area) for c in candidates})
        for node_id in candidates:
            self.assertEqual("Save Station", node_id.node)
            node = self.db.node(node_id)
            self.assertEqual("generic", node.node_type)
            self.assertTrue(node.valid_starting_location)

            # every candidate resolves to a real mlvl/mrea, exactly like
            # patch_data.py's _area_asset_ids needs for "starting_area".
            mlvl_id = self.db.mlvl_for_region(node_id.region)
            area = self.db.regions[node_id.region].areas[node_id.area]
            self.assertIsInstance(mlvl_id, int)
            self.assertIsNotNone(area.asset_id, msg=f"{node_id.ap_name} area has no MREA asset_id")

        _light_regions, dark_regions = self.db.light_dark_regions()
        light_count = sum(1 for c in candidates if c.region not in dark_regions)
        dark_count = sum(1 for c in candidates if c.region in dark_regions)
        self.assertEqual(9, light_count)
        self.assertEqual(9, dark_count)

    def test_anywhere_starting_location_candidates(self) -> None:
        # Every randovania valid_starting_location node, 272 total -- 162
        # light / 110 dark (user-verified pool sizes; see options.py's
        # StartingRoom docstring).
        candidates = self.db.starting_location_candidates("anywhere")
        self.assertEqual(272, len(candidates))

        # one node per area -- no ambiguity collapsing node -> area for the
        # patcher's AreaReference.
        areas = [(c.region, c.area) for c in candidates]
        self.assertEqual(len(areas), len(set(areas)))

        _light_regions, dark_regions = self.db.light_dark_regions()
        light_count = sum(1 for c in candidates if c.region not in dark_regions)
        dark_count = sum(1 for c in candidates if c.region in dark_regions)
        self.assertEqual(162, light_count)
        self.assertEqual(110, dark_count)

        per_region = {
            "Temple Grounds": 39,
            "Agon Wastes": 39,
            "Torvus Bog": 39,
            "Sanctuary Fortress": 36,
            "Great Temple": 9,
            "Dark Agon Wastes": 32,
            "Dark Torvus Bog": 29,
            "Ing Hive": 29,
            "Sky Temple Grounds": 17,
            "Sky Temple": 3,
        }
        counts: dict[str, int] = {}
        for region, _area in areas:
            counts[region] = counts.get(region, 0) + 1
        self.assertEqual(per_region, counts)

        # every candidate resolves to a real mlvl/mrea.
        for node_id in candidates:
            mlvl_id = self.db.mlvl_for_region(node_id.region)
            area = self.db.regions[node_id.region].areas[node_id.area]
            self.assertIsInstance(mlvl_id, int)
            self.assertIsNotNone(area.asset_id, msg=f"{node_id.ap_name} area has no MREA asset_id")

    def test_light_world_only_drops_dark_regions(self) -> None:
        _light_regions, dark_regions = self.db.light_dark_regions()
        for pool, expected_count in (("save_stations", 9), ("anywhere", 162)):
            with self.subTest(pool=pool):
                candidates = self.db.starting_location_candidates(pool, light_world_only=True)
                self.assertEqual(expected_count, len(candidates))
                for node_id in candidates:
                    self.assertNotIn(node_id.region, dark_regions)

    def test_vanilla_starting_location_is_a_save_station_candidate(self) -> None:
        self.assertIn(self.db.starting_location, self.db.starting_location_candidates("save_stations"))
        self.assertIn(self.db.starting_location, self.db.starting_location_candidates("anywhere"))

    def test_unknown_pool_rejected(self) -> None:
        with self.assertRaises(ValueError):
            self.db.starting_location_candidates("everywhere")

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
