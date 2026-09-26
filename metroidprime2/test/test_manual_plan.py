"""Keeps the manual test book honest without ever launching a game
(MANUAL_TEST_PLAN.md section 3.6):

* every ``mt*.py`` module loads and defines a ``TEST``;
* slugs and seeds are unique;
* every referenced location/item/room name exists in the DB (and, for
  companion slots, in that game's item table);
* the checked-in ``test/manual/README.md`` equals ``build_readme.py``'s
  output;
* any pinned ``config_sha256`` is a well-formed digest.
"""

from __future__ import annotations

import os
import re
import unittest

os.environ.setdefault("SKIP_REQUIREMENTS_UPDATE", "1")

import worlds

if "network_data_package" not in worlds.__dict__:
    worlds.network_data_package = {"games": {}}
    worlds.network_data_package_single_game = {}

from worlds import AutoWorldRegister

from ..items import ITEM_TABLE
from ..locations import location_name_to_id
from ..logic.db_reader import load_game_database
from .manual import build_readme, catalog

_HEX64 = re.compile(r"^[0-9a-f]{64}$")


def _all_specs():
    return catalog.load_tests()


def _known_games() -> frozenset[str]:
    worlds.ensure_worlds_loaded()
    return frozenset(AutoWorldRegister.world_types)


class TestManualModules(unittest.TestCase):
    def test_every_module_loads_and_defines_a_test(self) -> None:
        modules = _all_specs()
        self.assertTrue(modules, "no mt*.py manual test modules found")
        for name, test in modules:
            self.assertTrue(test.slug.startswith("mt"), f"{name}: slug {test.slug!r} should start with 'mt'")

    def test_slugs_are_unique(self) -> None:
        slugs = [test.slug for _name, test in _all_specs()]
        self.assertEqual(len(slugs), len(set(slugs)), f"duplicate slugs: {slugs}")

    def test_seeds_are_unique(self) -> None:
        seeds = [test.seed for _name, test in _all_specs()]
        self.assertEqual(len(seeds), len(set(seeds)), f"duplicate seeds: {seeds}")

    def test_priorities_are_valid(self) -> None:
        for _name, test in _all_specs():
            self.assertIn(test.priority, {"P0", "P1", "P2"}, test.slug)


class TestReferencedNames(unittest.TestCase):
    def test_starting_rooms_are_legal(self) -> None:
        db = load_game_database()
        candidates = set(db.starting_location_candidates("anywhere"))
        by_name = {node.ap_name: node.id for node in db.all_nodes()}
        for name, test in _all_specs():
            rooms = [test.starting_room]
            rooms.extend(variant.starting_room for variant in test.variants.values())
            for room in rooms:
                if room is None:
                    continue
                with self.subTest(module=name, room=room):
                    self.assertIn(room, by_name)
                    self.assertIn(by_name[room], candidates)

    def test_primary_locations_and_items_exist(self) -> None:
        for name, test in _all_specs():
            entries = list(test.plando)
            for variant in test.variants.values():
                if variant.plando is not None:
                    entries.extend(variant.plando)
            for entry in entries:
                item = entry.get("item") or entry.get("items")
                location = entry.get("location") or entry.get("locations")
                if location:
                    locations = [location] if isinstance(location, str) else location
                    for loc in locations:
                        with self.subTest(module=name, location=loc):
                            self.assertIn(loc, location_name_to_id, f"{name}: unknown location {loc!r}")
                if item and "world" not in entry:
                    items = [item] if isinstance(item, str) else list(item)
                    for it in items:
                        with self.subTest(module=name, item=it):
                            self.assertIn(it, ITEM_TABLE, f"{name}: unknown MP2 item {it!r}")

    def test_start_inventory_items_exist(self) -> None:
        for name, test in _all_specs():
            inventories = [test.start_inventory]
            inventories.extend(v.start_inventory for v in test.variants.values())
            for inventory in inventories:
                for item in inventory:
                    with self.subTest(module=name, item=item):
                        self.assertIn(item, ITEM_TABLE, f"{name}: unknown MP2 start item {item!r}")

    def test_companion_games_and_items_exist(self) -> None:
        known_games = _known_games()
        for name, test in _all_specs():
            companions = [*test.companions]
            for variant in test.variants.values():
                if variant.companions is not None:
                    companions.extend(variant.companions)
            for companion in companions:
                with self.subTest(module=name, companion=companion.name):
                    self.assertIn(companion.game, known_games, f"{name}: unknown game {companion.game!r}")
                    item_names = AutoWorldRegister.world_types[companion.game].item_names
                    for entry in companion.plando:
                        item = entry.get("item") or entry.get("items")
                        if isinstance(item, str):
                            self.assertIn(item, item_names, f"{name}: {item!r} is not a {companion.game} item")

    def test_companion_slot_names_are_unique(self) -> None:
        for name, test in _all_specs():
            names = [c.name for c in test.companions]
            self.assertEqual(len(names), len(set(names)), f"{name}: duplicate companion names {names}")


class TestPinnedHashes(unittest.TestCase):
    def test_config_hashes_are_well_formed(self) -> None:
        for name, test in _all_specs():
            hashes = [test.config_sha256]
            hashes.extend(v.config_sha256 for v in test.variants.values())
            for digest in hashes:
                if digest is None:
                    continue
                with self.subTest(module=name):
                    self.assertRegex(digest, _HEX64, f"{name}: malformed config_sha256")

    def test_pinned_hashes_are_not_stale_duplicates(self) -> None:
        seen: dict[str, str] = {}
        for name, test in _all_specs():
            if test.config_sha256:
                self.assertNotIn(
                    test.config_sha256, seen, f"{name} and {seen.get(test.config_sha256)} share a config hash"
                )
                seen[test.config_sha256] = name


class TestReadmeMatchesScripts(unittest.TestCase):
    def test_readme_is_current(self) -> None:
        expected = build_readme.generate_readme()
        actual = build_readme.README_PATH.read_text(encoding="utf-8")
        self.assertEqual(expected, actual, "test/manual/README.md is stale; run build_readme")


if __name__ == "__main__":
    unittest.main()
