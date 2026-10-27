"""Tests for item scan hints (PLAN.md section AA): scanning a pickup hints
its item through the generic ``hint_scans`` path.

Pure-logic coverage (asset ids, entry selection) uses a duck-typed stand-in
for ``World`` like ``test_hint_scans.py``; the slot_data / options.json
wiring uses a real two-player generation like ``test_translator_lore_hints.py``.
"""

from __future__ import annotations

import importlib.util
import random
import unittest
from argparse import Namespace
from typing import Any

import ModuleUpdate

ModuleUpdate.update_ran = True

from BaseClasses import CollectionState, MultiWorld  # noqa: E402 -- must follow update_ran
from Fill import distribute_items_restrictive  # noqa: E402
from Generate import get_seed_name  # noqa: E402
from NetUtils import HintStatus  # noqa: E402
from worlds import AutoWorld  # noqa: E402
from worlds.AutoWorld import call_all  # noqa: E402

from .. import constants  # noqa: E402
from ..client import item_scan_patch  # noqa: E402
from ..hint_scans import (  # noqa: E402
    LORE_HINT_SCAN_IDS,
    SKY_TEMPLE_KEY_HINT_SCANS,
    item_scan_asset_name,
    item_scan_hint_entries,
    item_scan_id,
)
from ..items import TRAP_ITEM_NAMES  # noqa: E402
from ..locations import LOCATION_TABLE  # noqa: E402
from ..options import ItemScanHints  # noqa: E402
from ..pickup_encoding import counter_and_amount, pickup_index_for  # noqa: E402

try:
    from test.general import gen_steps
except ImportError:  # pragma: no cover - only relevant if test/general ever moves
    gen_steps = ("generate_early", "create_regions", "create_items", "set_rules", "generate_basic")

GAME = "Metroid Prime 2: Echoes"
_RDS_AVAILABLE = importlib.util.find_spec("retro_data_structures") is not None
_OPR_AVAILABLE = importlib.util.find_spec("open_prime_rando") is not None


class TestItemScanIds(unittest.TestCase):
    @unittest.skipUnless(_RDS_AVAILABLE, "retro_data_structures is not installed")
    def test_matches_retro_crc32_of_the_asset_name(self) -> None:
        from retro_data_structures.game_check import Game

        for loc in LOCATION_TABLE:
            self.assertEqual(
                Game.ECHOES.hash_asset_id(item_scan_asset_name(loc.pickup_index)),
                item_scan_id(loc.pickup_index),
            )

    def test_one_distinct_id_per_pickup(self) -> None:
        ids = {item_scan_id(loc.pickup_index) for loc in LOCATION_TABLE}
        self.assertEqual(len(LOCATION_TABLE), len(ids))

    def test_disjoint_from_the_other_hint_scans(self) -> None:
        ids = {item_scan_id(loc.pickup_index) for loc in LOCATION_TABLE}
        self.assertEqual(set(), ids & {scan.scan_id for scan in SKY_TEMPLE_KEY_HINT_SCANS})
        self.assertEqual(set(), ids & set(LORE_HINT_SCAN_IDS.values()))


class TestPickupIndexFor(unittest.TestCase):
    def test_inverts_counter_and_amount_for_every_pickup(self) -> None:
        for loc in LOCATION_TABLE:
            self.assertEqual(loc.pickup_index, pickup_index_for(*counter_and_amount(loc.pickup_index)))

    def test_rejects_anything_that_is_not_one_pickups_bit(self) -> None:
        counter = constants.PICKUP_COUNTER_ITEMS[0]
        self.assertIsNone(pickup_index_for(counter, 0))
        self.assertIsNone(pickup_index_for(counter, 3))
        self.assertIsNone(pickup_index_for(counter, 1 << constants.BITS_PER_COUNTER))
        self.assertIsNone(pickup_index_for(-1, 1))


class _FakeItem:
    def __init__(self, name: str, player: int) -> None:
        self.name = name
        self.player = player


class _FakeLocation:
    def __init__(self, pickup_index: int, item: _FakeItem | None, player: int = 1) -> None:
        self.address = constants.LOCATION_ID_BASE + pickup_index
        self.item = item
        self.player = player


class _FakeOption:
    def __init__(self, value: int) -> None:
        self.value = value

    def __bool__(self) -> bool:
        return bool(self.value)


class _FakeWorld:
    def __init__(self, locations: list[_FakeLocation], mode: int, trap_disguise: bool = False) -> None:
        self.player = 1
        self.multiworld = self
        self._locations = locations
        self.options = Namespace(item_scan_hints=_FakeOption(mode), trap_disguise=_FakeOption(trap_disguise))

    def get_locations(self, player: int) -> list[_FakeLocation]:
        assert player == self.player
        return self._locations


class TestItemScanHintEntries(unittest.TestCase):
    def setUp(self) -> None:
        self.trap = sorted(TRAP_ITEM_NAMES)[0]
        self.locations = [
            _FakeLocation(0, _FakeItem("Missile Expansion", 1)),
            _FakeLocation(1, _FakeItem("Great Sword", 2)),
            _FakeLocation(2, _FakeItem(self.trap, 1)),
            _FakeLocation(3, None),
            _FakeLocation(4, _FakeItem("Great Sword", 2)),
        ]
        self.locations[4].address = None

    def _entries(self, mode: int, trap_disguise: bool = False) -> dict[int, tuple[Any, int]]:
        return item_scan_hint_entries(_FakeWorld(self.locations, mode, trap_disguise))  # type: ignore[arg-type]

    def test_off_hints_nothing(self) -> None:
        self.assertEqual({}, self._entries(ItemScanHints.option_off))

    def test_other_players_only_hints_foreign_items_as_unspecified(self) -> None:
        entries = self._entries(ItemScanHints.option_other_players)
        self.assertEqual({1}, set(entries))
        self.assertEqual(HintStatus.HINT_UNSPECIFIED, entries[1][1])

    def test_all_adds_own_items_as_priority(self) -> None:
        entries = self._entries(ItemScanHints.option_all)
        self.assertEqual({0, 1, 2}, set(entries))
        self.assertEqual(HintStatus.HINT_PRIORITY, entries[0][1])
        self.assertEqual(HintStatus.HINT_UNSPECIFIED, entries[1][1])

    def test_disguised_own_trap_is_never_hinted(self) -> None:
        self.assertEqual({0, 1}, set(self._entries(ItemScanHints.option_all, trap_disguise=True)))

    def test_unfilled_and_addressless_locations_are_skipped(self) -> None:
        entries = self._entries(ItemScanHints.option_all)
        self.assertNotIn(3, entries)
        self.assertNotIn(4, entries)


class _FakeEditor:
    def __init__(self) -> None:
        self.created: list[tuple[int, str, int]] = []

    def create_simple_scan(self, box1: str, box2: str | None = None, model: int = 0) -> int:
        raise AssertionError("the pooled implementation must not be used for a wanted pickup")


class _Resource:
    def __init__(self, item: int, amount: int) -> None:
        self.item = item
        self.amount = amount


class _Stage:
    def __init__(self, resources: list[_Resource]) -> None:
        self.resources = resources


class _Modification:
    def __init__(self, pickup_index: int) -> None:
        item, amount = counter_and_amount(pickup_index)
        self.primary_stage = _Stage([_Resource(item, amount)])


@unittest.skipUnless(_OPR_AVAILABLE and _RDS_AVAILABLE, "open-prime-rando is not installed")
class TestInstalled(unittest.TestCase):
    def setUp(self) -> None:
        from open_prime_rando.echoes.pickups import pickup_editing

        self.pickup_editing = pickup_editing
        self.real = pickup_editing.patch_simple_pickup
        self.seen: list[Any] = []

        def _recorder(modification: Any, editor: Any, *args: Any, **kwargs: Any) -> None:
            self.seen.append(editor.create_simple_scan("text", model=7))

        pickup_editing.patch_simple_pickup = _recorder
        self.recorder = _recorder
        self.addCleanup(setattr, pickup_editing, "patch_simple_pickup", self.real)

    def test_wanted_pickup_gets_a_unique_scan_and_the_editor_is_restored(self) -> None:
        calls: list[tuple[int, str, int]] = []
        original_create = item_scan_patch.create_unique_scan
        item_scan_patch.create_unique_scan = lambda editor, index, text, model: calls.append((index, text, model)) or 99  # type: ignore[assignment]
        self.addCleanup(setattr, item_scan_patch, "create_unique_scan", original_create)

        editor = _FakeEditor()
        with item_scan_patch.installed([5]):
            self.pickup_editing.patch_simple_pickup(_Modification(5), editor)
        self.assertEqual([99], self.seen)
        self.assertEqual([(5, "text", 7)], calls)
        self.assertNotIn("create_simple_scan", vars(editor))
        self.assertIs(self.recorder, self.pickup_editing.patch_simple_pickup)

    def test_other_pickups_keep_the_pooled_scan(self) -> None:
        class _PooledEditor(_FakeEditor):
            def create_simple_scan(self, box1: str, box2: str | None = None, model: int = 0) -> int:
                return 42

        with item_scan_patch.installed([5]):
            self.pickup_editing.patch_simple_pickup(_Modification(6), _PooledEditor())
        self.assertEqual([42], self.seen)

    def test_scan_is_restored_even_if_the_patch_raises(self) -> None:
        def _boom(modification: Any, editor: Any, *args: Any, **kwargs: Any) -> None:
            raise RuntimeError("boom")

        self.pickup_editing.patch_simple_pickup = _boom
        editor = _FakeEditor()
        with item_scan_patch.installed([5]), self.assertRaises(RuntimeError):
            self.pickup_editing.patch_simple_pickup(_Modification(5), editor)
        self.assertNotIn("create_simple_scan", vars(editor))


def _build(options_by_player: list[dict[str, Any]], seed: int) -> MultiWorld:
    """``test_translator_lore_hints.py``'s ``_build``: a real generation
    through ``pre_output`` with one Echoes player per entry."""
    players = len(options_by_player)
    multiworld = MultiWorld(players)
    for player in range(1, players + 1):
        multiworld.game[player] = GAME
    multiworld.player_name = {player: f"Tester{player}" for player in range(1, players + 1)}
    multiworld.set_seed(seed)
    random.seed(multiworld.seed)
    multiworld.seed_name = get_seed_name(random)

    args = Namespace()
    for name, option in AutoWorld.AutoWorldRegister.world_types[GAME].options_dataclass.type_hints.items():
        setattr(
            args,
            name,
            {
                player: option.from_any(options_by_player[player - 1].get(name, option.default))
                for player in range(1, players + 1)
            },
        )
    multiworld.set_options(args)
    multiworld.state = CollectionState(multiworld)

    for step in gen_steps:
        call_all(multiworld, step)

    distribute_items_restrictive(multiworld)
    call_all(multiworld, "post_fill")
    call_all(multiworld, "pre_output")
    return multiworld


class TestGeneration(unittest.TestCase):
    def test_off_adds_no_scans(self) -> None:
        multiworld = _build([{"item_scan_hints": "off"}, {}], seed=3)
        world = multiworld.worlds[1]
        self.assertEqual({}, item_scan_hint_entries(world))
        scan_ids = {str(item_scan_id(loc.pickup_index)) for loc in LOCATION_TABLE}
        self.assertEqual(set(), scan_ids & set(world.fill_slot_data()["hint_scans"]))

    def test_other_players_slot_data_names_every_foreign_item_in_this_world(self) -> None:
        multiworld = _build([{"item_scan_hints": "other_players"}, {}], seed=3)
        world = multiworld.worlds[1]

        foreign = {
            loc.address - constants.LOCATION_ID_BASE: loc
            for loc in multiworld.get_locations(1)
            if loc.item is not None and loc.item.player != 1 and loc.address is not None
        }
        self.assertTrue(foreign, "seed placed no foreign items in player 1's world")

        hint_scans = world.fill_slot_data()["hint_scans"]
        for pickup_index, loc in foreign.items():
            self.assertEqual(
                [1, loc.address, HintStatus.HINT_UNSPECIFIED], hint_scans[str(item_scan_id(pickup_index))]
            )
        own = [
            loc
            for loc in multiworld.get_locations(1)
            if loc.item is not None and loc.item.player == 1 and loc.address is not None
        ]
        for loc in own:
            self.assertNotIn(str(item_scan_id(loc.address - constants.LOCATION_ID_BASE)), hint_scans)

        self.assertEqual(sorted(foreign), sorted(item_scan_hint_entries(world)))

    def test_all_hints_own_items_with_priority(self) -> None:
        multiworld = _build([{"item_scan_hints": "all", "trap_disguise": False}, {}], seed=3)
        world = multiworld.worlds[1]
        hint_scans = world.fill_slot_data()["hint_scans"]
        own = [
            loc
            for loc in multiworld.get_locations(1)
            if loc.item is not None and loc.item.player == 1 and loc.address is not None
        ]
        self.assertTrue(own)
        for loc in own:
            self.assertEqual(
                [1, loc.address, HintStatus.HINT_PRIORITY],
                hint_scans[str(item_scan_id(loc.address - constants.LOCATION_ID_BASE))],
            )


if __name__ == "__main__":
    unittest.main()
