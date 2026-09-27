"""Tests for ``hint_scans.py`` (PLAN.md sections Q, R): the Sky Temple Key
pillar and translator lore hologram STRG/SCAN tables, the lore-hint SCAN id
table they're guarded against, the pure slot_data encode/decode +
completion-detection functions the client and generation side share, and
``translator_lore_hint_locations``'s selection logic.
"""

from __future__ import annotations

import random
import unittest

from BaseClasses import ItemClassification
from NetUtils import HintStatus

from ..data import load_json
from ..hint_scans import (
    LORE_HINT_SCAN_IDS,
    SCAN_COMPLETE,
    SKY_TEMPLE_KEY_HINT_SCANS,
    TRANSLATOR_LORE_HINT_SCANS,
    decode_hint_scans,
    encode_hint_scans,
    newly_completed_hints,
    translator_lore_hint_locations,
)
from ..options import SkyTempleKeyHints, TranslatorLoreHints


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


def _vendored_translator_lore_nodes() -> dict[int, str]:
    """``{string_asset_id: "Region - Area"}`` for every ``node_type:
    "hint"`` node with an ``extra.translator`` field (the 22 lore
    holograms; NOT translator gates, NOT the 9 Keybearer corpses)."""
    header = load_json("logic_database/header.json")
    result: dict[int, str] = {}
    for region_file in header["regions"]:
        region = load_json(f"logic_database/{region_file}")
        region_name = region["name"]
        for area_name, area in region.get("areas", {}).items():
            for node in area.get("nodes", {}).values():
                if node.get("node_type") != "hint":
                    continue
                extra = node.get("extra", {})
                if "translator" not in extra:
                    continue
                result[extra["string_asset_id"]] = f"{region_name} - {area_name}"
    return result


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


class TestTranslatorLoreHintScans(unittest.TestCase):
    def test_twenty_two_entries(self) -> None:
        self.assertEqual(22, len(TRANSLATOR_LORE_HINT_SCANS))

    def test_strg_set_matches_vendored_translator_hint_nodes(self) -> None:
        vendored = _vendored_translator_lore_nodes()
        strg_ids = {scan.strg_id for scan in TRANSLATOR_LORE_HINT_SCANS}
        self.assertEqual(set(vendored), strg_ids)

    def test_scan_and_room_match_the_vendored_db(self) -> None:
        vendored = _vendored_translator_lore_nodes()
        for scan in TRANSLATOR_LORE_HINT_SCANS:
            self.assertEqual(LORE_HINT_SCAN_IDS[scan.strg_id], scan.scan_id)
            self.assertEqual(vendored[scan.strg_id], scan.room)

    def test_disjoint_from_sky_temple_key_table(self) -> None:
        stk_strg_ids = {scan.strg_id for scan in SKY_TEMPLE_KEY_HINT_SCANS}
        stk_scan_ids = {scan.scan_id for scan in SKY_TEMPLE_KEY_HINT_SCANS}
        lore_strg_ids = {scan.strg_id for scan in TRANSLATOR_LORE_HINT_SCANS}
        lore_scan_ids = {scan.scan_id for scan in TRANSLATOR_LORE_HINT_SCANS}
        self.assertEqual(set(), stk_strg_ids & lore_strg_ids)
        self.assertEqual(set(), stk_scan_ids & lore_scan_ids)


class TestEncodeDecodeHintScans(unittest.TestCase):
    def test_round_trips(self) -> None:
        entries = {
            0x856AD9A4: (1, 5033201, HintStatus.HINT_PRIORITY),
            0x6E5D62A7: (2, 5033255, HintStatus.HINT_UNSPECIFIED),
        }
        encoded = encode_hint_scans(entries)
        self.assertEqual(
            {
                "2238372260": [1, 5033201, HintStatus.HINT_PRIORITY],
                "1851613863": [2, 5033255, HintStatus.HINT_UNSPECIFIED],
            },
            encoded,
        )
        self.assertEqual(entries, decode_hint_scans(encoded))

    def test_decode_none_is_empty(self) -> None:
        self.assertEqual({}, decode_hint_scans(None))

    def test_decode_missing_key_is_empty(self) -> None:
        self.assertEqual({}, decode_hint_scans({}))

    def test_decode_tolerates_older_two_element_entries(self) -> None:
        # Section R added the third (status) element; an older slot_data
        # (Q only) never wrote one, and always meant HINT_PRIORITY (hinting
        # your own item -- the only kind Q's Sky Temple Key pillars ever
        # sent).
        raw = {"100": [1, 5033201]}
        self.assertEqual({100: (1, 5033201, HintStatus.HINT_PRIORITY)}, decode_hint_scans(raw))


class TestNewlyCompletedHints(unittest.TestCase):
    def setUp(self) -> None:
        self.hint_scans = {
            0x111: (1, 100, HintStatus.HINT_PRIORITY),
            0x222: (1, 101, HintStatus.HINT_PRIORITY),
            0x333: (2, 200, HintStatus.HINT_PRIORITY),
        }

    def test_only_complete_scans_count(self) -> None:
        scan_progress = {0x111: SCAN_COMPLETE, 0x222: SCAN_COMPLETE - 1}
        newly_completed, by_group = newly_completed_hints(scan_progress, self.hint_scans, set())
        self.assertEqual({0x111}, newly_completed)
        self.assertEqual({(1, HintStatus.HINT_PRIORITY): [100]}, by_group)

    def test_unknown_scan_ids_are_ignored(self) -> None:
        scan_progress = {0x999: SCAN_COMPLETE}
        newly_completed, by_group = newly_completed_hints(scan_progress, self.hint_scans, set())
        self.assertEqual(set(), newly_completed)
        self.assertEqual({}, by_group)

    def test_already_sent_ids_are_skipped(self) -> None:
        scan_progress = {0x111: SCAN_COMPLETE, 0x222: SCAN_COMPLETE}
        newly_completed, by_group = newly_completed_hints(scan_progress, self.hint_scans, {0x111})
        self.assertEqual({0x222}, newly_completed)
        self.assertEqual({(1, HintStatus.HINT_PRIORITY): [101]}, by_group)

    def test_groups_by_location_player_and_sorts_locations(self) -> None:
        scan_progress = {0x111: SCAN_COMPLETE, 0x222: SCAN_COMPLETE, 0x333: SCAN_COMPLETE}
        newly_completed, by_group = newly_completed_hints(scan_progress, self.hint_scans, set())
        self.assertEqual({0x111, 0x222, 0x333}, newly_completed)
        self.assertEqual(
            {(1, HintStatus.HINT_PRIORITY): [100, 101], (2, HintStatus.HINT_PRIORITY): [200]}, by_group
        )

    def test_nothing_complete_yields_empty_result(self) -> None:
        newly_completed, by_group = newly_completed_hints({}, self.hint_scans, set())
        self.assertEqual(set(), newly_completed)
        self.assertEqual({}, by_group)

    def test_mixed_statuses_for_the_same_player_are_kept_separate(self) -> None:
        # A player can have both a Sky Temple Key hint (HINT_PRIORITY) and
        # a translator lore hint naming someone else's item
        # (HINT_UNSPECIFIED) complete on the same tick -- these must stay
        # in separate groups, since CreateHints needs one call per status.
        hint_scans = {
            0x111: (1, 100, HintStatus.HINT_PRIORITY),
            0x222: (1, 101, HintStatus.HINT_UNSPECIFIED),
        }
        scan_progress = {0x111: SCAN_COMPLETE, 0x222: SCAN_COMPLETE}
        newly_completed, by_group = newly_completed_hints(scan_progress, hint_scans, set())
        self.assertEqual({0x111, 0x222}, newly_completed)
        self.assertEqual(
            {(1, HintStatus.HINT_PRIORITY): [100], (1, HintStatus.HINT_UNSPECIFIED): [101]}, by_group
        )


# --------------------------------------------------------------------------
# translator_lore_hint_locations: pure-logic tests against a duck-typed
# stand-in for World/MultiWorld (mirrors test_translator_gate_rando.py's
# _FakeWorld approach), since the function itself only ever touches
# world.options/.player/.multiworld.get_filled_locations()/.multiworld.seed
# and world._translator_lore_hints.
# --------------------------------------------------------------------------


class _FakeItem:
    def __init__(
        self,
        name: str,
        player: int,
        advancement: bool = True,
        classification: ItemClassification | None = None,
    ) -> None:
        self.name = name
        self.player = player
        if classification is None:
            classification = ItemClassification.progression if advancement else ItemClassification.filler
        self.classification = classification
        self.advancement = ItemClassification.progression in classification


class _FakeLocation:
    def __init__(self, player: int, address: int, item: _FakeItem | None) -> None:
        self.player = player
        self.address = address
        self.item = item
        self.name = f"Location {player}:{address}"


class _FakeMultiworld:
    def __init__(self, locations: list[_FakeLocation], seed: int = 12345) -> None:
        self._locations = locations
        self.seed = seed

    def get_filled_locations(self) -> list[_FakeLocation]:
        return self._locations


class _FakeOption:
    def __init__(self, value: int) -> None:
        self.value = value


class _FakeOptions:
    def __init__(self, translator_lore_hints: int, sky_temple_key_hints: int) -> None:
        self.translator_lore_hints = _FakeOption(translator_lore_hints)
        self.sky_temple_key_hints = _FakeOption(sky_temple_key_hints)


class _FakeWorld:
    def __init__(
        self,
        locations: list[_FakeLocation],
        translator_lore_hints: int = TranslatorLoreHints.option_my_items,
        sky_temple_key_hints: int = SkyTempleKeyHints.option_scanned,
        player: int = 1,
        seed: int = 12345,
    ) -> None:
        self.multiworld = _FakeMultiworld(locations, seed)
        self.options = _FakeOptions(translator_lore_hints, sky_temple_key_hints)
        self.player = player
        self._translator_lore_hints: list[_FakeLocation | None] | None = None


def _progression_locations(
    count: int, player: int = 1, item_player: int | None = None, start: int = 5000
) -> list[_FakeLocation]:
    owner = player if item_player is None else item_player
    return [_FakeLocation(player, start + i, _FakeItem(f"Item {i}", owner)) for i in range(count)]


class TestTranslatorLoreHintLocations(unittest.TestCase):
    def test_off_returns_twenty_two_nones_without_rng(self) -> None:
        world = _FakeWorld(_progression_locations(30), translator_lore_hints=TranslatorLoreHints.option_off)
        result = translator_lore_hint_locations(world)  # type: ignore[arg-type]
        self.assertEqual([None] * 22, result)

    def test_my_items_picks_twenty_two_of_this_players_progression_items(self) -> None:
        locations = _progression_locations(30)
        world = _FakeWorld(locations, translator_lore_hints=TranslatorLoreHints.option_my_items)
        result = translator_lore_hint_locations(world)  # type: ignore[arg-type]
        self.assertEqual(22, len(result))
        self.assertEqual(22, len({loc.address for loc in result if loc is not None}))
        for loc in result:
            assert loc is not None
            self.assertEqual(1, loc.item.player)

    def test_fewer_candidates_than_holograms_is_padded_with_none(self) -> None:
        locations = _progression_locations(5)
        world = _FakeWorld(locations, translator_lore_hints=TranslatorLoreHints.option_my_items)
        result = translator_lore_hint_locations(world)  # type: ignore[arg-type]
        self.assertEqual(22, len(result))
        non_none = [loc for loc in result if loc is not None]
        self.assertEqual(5, len(non_none))
        self.assertEqual({loc.address for loc in locations}, {loc.address for loc in non_none})

    def test_non_progression_items_are_never_candidates(self) -> None:
        locations = [_FakeLocation(1, 5000, _FakeItem("Filler", 1, advancement=False))]
        world = _FakeWorld(locations, translator_lore_hints=TranslatorLoreHints.option_my_items)
        result = translator_lore_hint_locations(world)  # type: ignore[arg-type]
        self.assertEqual([None] * 22, result)

    def test_skip_balancing_progression_is_never_a_candidate(self) -> None:
        item = _FakeItem("Missile Expansion", 1, classification=ItemClassification.progression_skip_balancing)
        world = _FakeWorld([_FakeLocation(1, 5000, item)], translator_lore_hints=TranslatorLoreHints.option_my_items)
        result = translator_lore_hint_locations(world)  # type: ignore[arg-type]
        self.assertEqual([None] * 22, result)

    def test_each_item_name_is_hinted_at_most_once(self) -> None:
        locations = [_FakeLocation(1, 5000 + i, _FakeItem("Energy Tank", 1)) for i in range(14)]
        locations.append(_FakeLocation(1, 6000, _FakeItem("Energy Tank", 2)))
        world = _FakeWorld(locations, translator_lore_hints=TranslatorLoreHints.option_any)
        result = translator_lore_hint_locations(world)  # type: ignore[arg-type]
        chosen = [loc for loc in result if loc is not None]
        # One of player 1's 14 tanks, plus player 2's own tank in our world.
        self.assertEqual(2, len(chosen))
        self.assertEqual({1, 2}, {loc.item.player for loc in chosen})

    def test_unfilled_locations_are_never_candidates(self) -> None:
        locations = [_FakeLocation(1, 5000, None)]
        world = _FakeWorld(locations, translator_lore_hints=TranslatorLoreHints.option_my_items)
        result = translator_lore_hint_locations(world)  # type: ignore[arg-type]
        self.assertEqual([None] * 22, result)

    def test_own_sky_temple_keys_excluded_unless_hints_disabled(self) -> None:
        locations = _progression_locations(21)
        locations.append(_FakeLocation(1, 6000, _FakeItem("Sky Temple Key 3", 1)))

        excluded = _FakeWorld(
            locations,
            translator_lore_hints=TranslatorLoreHints.option_my_items,
            sky_temple_key_hints=SkyTempleKeyHints.option_scanned,
        )
        result = translator_lore_hint_locations(excluded)  # type: ignore[arg-type]
        self.assertNotIn(6000, {loc.address for loc in result if loc is not None})

        included = _FakeWorld(
            locations,
            translator_lore_hints=TranslatorLoreHints.option_my_items,
            sky_temple_key_hints=SkyTempleKeyHints.option_disabled,
        )
        result = translator_lore_hint_locations(included)  # type: ignore[arg-type]
        self.assertIn(6000, {loc.address for loc in result if loc is not None})

    def test_my_items_excludes_foreign_items_in_own_world(self) -> None:
        locations = _progression_locations(10) + _progression_locations(5, player=1, item_player=2, start=6000)
        world = _FakeWorld(locations, translator_lore_hints=TranslatorLoreHints.option_my_items)
        result = translator_lore_hint_locations(world)  # type: ignore[arg-type]
        for loc in result:
            if loc is not None:
                self.assertEqual(1, loc.item.player)

    def test_any_includes_foreign_items_placed_in_own_world(self) -> None:
        own = _progression_locations(10)
        foreign_in_own_world = _progression_locations(5, player=1, item_player=2, start=6000)
        world = _FakeWorld(own + foreign_in_own_world, translator_lore_hints=TranslatorLoreHints.option_any)
        result = translator_lore_hint_locations(world)  # type: ignore[arg-type]
        item_players = {loc.item.player for loc in result if loc is not None}
        self.assertIn(2, item_players)

    def test_any_excludes_foreign_items_placed_in_someone_elses_world(self) -> None:
        # A foreign item placed in a THIRD player's world is never a
        # candidate, even under "any" -- only items in this player's own
        # world (location.player == world.player) qualify as "someone
        # else's item you can hint at".
        foreign_elsewhere = _progression_locations(5, player=3, item_player=2)
        world = _FakeWorld(foreign_elsewhere, translator_lore_hints=TranslatorLoreHints.option_any)
        result = translator_lore_hint_locations(world)  # type: ignore[arg-type]
        self.assertEqual([None] * 22, result)

    def test_dedupes_by_player_and_address(self) -> None:
        item = _FakeItem("Duplicate", 1)
        locations = [_FakeLocation(1, 5000, item), _FakeLocation(1, 5000, item)]
        world = _FakeWorld(locations, translator_lore_hints=TranslatorLoreHints.option_my_items)
        result = translator_lore_hint_locations(world)  # type: ignore[arg-type]
        self.assertEqual(1, len([loc for loc in result if loc is not None]))

    def test_result_is_cached_on_the_world(self) -> None:
        world = _FakeWorld(_progression_locations(30), translator_lore_hints=TranslatorLoreHints.option_my_items)
        first = translator_lore_hint_locations(world)  # type: ignore[arg-type]
        second = translator_lore_hint_locations(world)  # type: ignore[arg-type]
        self.assertIs(first, second)

    def test_deterministic_given_the_same_seed_and_player(self) -> None:
        locations = _progression_locations(30)
        world_a = _FakeWorld(locations, translator_lore_hints=TranslatorLoreHints.option_my_items, seed=999)
        world_b = _FakeWorld(locations, translator_lore_hints=TranslatorLoreHints.option_my_items, seed=999)
        result_a = translator_lore_hint_locations(world_a)  # type: ignore[arg-type]
        result_b = translator_lore_hint_locations(world_b)  # type: ignore[arg-type]
        addresses_a = [loc.address if loc else None for loc in result_a]
        addresses_b = [loc.address if loc else None for loc in result_b]
        self.assertEqual(addresses_a, addresses_b)

    def test_toggling_this_option_does_not_touch_world_random(self) -> None:
        # The RNG is seeded from world.multiworld.seed/world.player, NOT
        # world.random -- a real random.Random instance, untouched here,
        # proves this function never calls it.
        untouched = random.Random(42)
        state_before = untouched.getstate()
        world = _FakeWorld(_progression_locations(30), translator_lore_hints=TranslatorLoreHints.option_my_items)
        world.random = untouched  # type: ignore[attr-defined]
        translator_lore_hint_locations(world)  # type: ignore[arg-type]
        self.assertEqual(state_before, untouched.getstate())


if __name__ == "__main__":
    unittest.main()
