"""Tests for ``hint_scans.py`` (PLAN.md section Q): the Sky Temple Key
pillar STRG/SCAN table, the lore-hint SCAN id table it's guarded against,
and the pure slot_data encode/decode + completion-detection functions the
client and generation side share.
"""

from __future__ import annotations

import unittest

from ..data import load_json
from ..hint_scans import (
    LORE_HINT_SCAN_IDS,
    SCAN_COMPLETE,
    SKY_TEMPLE_KEY_HINT_SCANS,
    decode_hint_scans,
    encode_hint_scans,
    newly_completed_hints,
)


def _vendored_hint_string_asset_ids() -> set[int]:
    """Every ``extra.string_asset_id`` on a ``node_type: "hint"`` node in
    the vendored logic database (the 31 keybearer-corpse/lore-scan nodes),
    read straight from the raw JSON the same way ``db_reader.py`` itself
    discovers region files -- ``Node`` doesn't expose ``extra`` generically,
    only the handful of ``extra`` keys some other node type actually needs
    (see ``db_reader._parse_node``), so this can't go through
    ``load_game_database()``.
    """
    header = load_json("logic_database/header.json")
    ids: set[int] = set()
    for region_file in header["regions"]:
        region = load_json(f"logic_database/{region_file}")
        for area in region.get("areas", {}).values():
            for node in area.get("nodes", {}).values():
                if node.get("node_type") != "hint":
                    continue
                string_asset_id = node.get("extra", {}).get("string_asset_id")
                if string_asset_id is not None:
                    ids.add(string_asset_id)
    return ids


class TestSkyTempleKeyHintScans(unittest.TestCase):
    def test_nine_entries_in_key_order(self) -> None:
        self.assertEqual(9, len(SKY_TEMPLE_KEY_HINT_SCANS))

    def test_strg_ids_are_distinct(self) -> None:
        strg_ids = [scan.strg_id for scan in SKY_TEMPLE_KEY_HINT_SCANS]
        self.assertEqual(len(strg_ids), len(set(strg_ids)))

    def test_scan_ids_are_distinct(self) -> None:
        scan_ids = [scan.scan_id for scan in SKY_TEMPLE_KEY_HINT_SCANS]
        self.assertEqual(len(scan_ids), len(set(scan_ids)))


class TestLoreHintScanIds(unittest.TestCase):
    def test_covers_every_vendored_hint_node(self) -> None:
        # Guards against a future DB resync silently adding a new
        # lore/keybearer hint node this table doesn't know about yet.
        self.assertEqual(_vendored_hint_string_asset_ids(), set(LORE_HINT_SCAN_IDS))

    def test_disjoint_from_sky_temple_key_table(self) -> None:
        stk_strg_ids = {scan.strg_id for scan in SKY_TEMPLE_KEY_HINT_SCANS}
        stk_scan_ids = {scan.scan_id for scan in SKY_TEMPLE_KEY_HINT_SCANS}
        self.assertEqual(set(), stk_strg_ids & set(LORE_HINT_SCAN_IDS))
        self.assertEqual(set(), stk_scan_ids & set(LORE_HINT_SCAN_IDS.values()))


class TestEncodeDecodeHintScans(unittest.TestCase):
    def test_round_trips(self) -> None:
        entries = {0x856AD9A4: (1, 5033201), 0x6E5D62A7: (2, 5033255)}
        encoded = encode_hint_scans(entries)
        self.assertEqual({"2238372260": [1, 5033201], "1851613863": [2, 5033255]}, encoded)
        self.assertEqual(entries, decode_hint_scans(encoded))

    def test_decode_none_is_empty(self) -> None:
        self.assertEqual({}, decode_hint_scans(None))

    def test_decode_missing_key_is_empty(self) -> None:
        self.assertEqual({}, decode_hint_scans({}))


class TestNewlyCompletedHints(unittest.TestCase):
    def setUp(self) -> None:
        self.hint_scans = {
            0x111: (1, 100),
            0x222: (1, 101),
            0x333: (2, 200),
        }

    def test_only_complete_scans_count(self) -> None:
        scan_progress = {0x111: SCAN_COMPLETE, 0x222: SCAN_COMPLETE - 1}
        newly_completed, by_player = newly_completed_hints(scan_progress, self.hint_scans, set())
        self.assertEqual({0x111}, newly_completed)
        self.assertEqual({1: [100]}, by_player)

    def test_unknown_scan_ids_are_ignored(self) -> None:
        scan_progress = {0x999: SCAN_COMPLETE}
        newly_completed, by_player = newly_completed_hints(scan_progress, self.hint_scans, set())
        self.assertEqual(set(), newly_completed)
        self.assertEqual({}, by_player)

    def test_already_sent_ids_are_skipped(self) -> None:
        scan_progress = {0x111: SCAN_COMPLETE, 0x222: SCAN_COMPLETE}
        newly_completed, by_player = newly_completed_hints(scan_progress, self.hint_scans, {0x111})
        self.assertEqual({0x222}, newly_completed)
        self.assertEqual({1: [101]}, by_player)

    def test_groups_by_location_player_and_sorts_locations(self) -> None:
        scan_progress = {0x111: SCAN_COMPLETE, 0x222: SCAN_COMPLETE, 0x333: SCAN_COMPLETE}
        newly_completed, by_player = newly_completed_hints(scan_progress, self.hint_scans, set())
        self.assertEqual({0x111, 0x222, 0x333}, newly_completed)
        self.assertEqual({1: [100, 101], 2: [200]}, by_player)

    def test_nothing_complete_yields_empty_result(self) -> None:
        newly_completed, by_player = newly_completed_hints({}, self.hint_scans, set())
        self.assertEqual(set(), newly_completed)
        self.assertEqual({}, by_player)


if __name__ == "__main__":
    unittest.main()
