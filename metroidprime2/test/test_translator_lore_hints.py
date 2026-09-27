"""Integration-level coverage for translator lore hints (PLAN.md section
R): real generation (``Fill.distribute_items_restrictive``, not just the
gen_steps ``MP2TestBase`` stops short at) is needed to get enough real
progression-item placements to meaningfully exercise
``translator_lore_hint_locations``'s selection logic end to end, and (for
the "any" mode) a real second player whose items can land in player 1's
world. Mirrors ``test_fill.py``'s approach (building ``MultiWorld``
instances directly, since ``MP2TestBase``/``WorldTestBase.world_setup``
doesn't expose a stable way to pin a seed), generalized to more than one
player.

Pure-logic/edge-case coverage of the selection algorithm itself (STK
exclusion, padding when there are fewer candidates than holograms, RNG
determinism/independence from ``world.random``, dedup) lives in
``test_hint_scans.py`` against a lightweight duck-typed stand-in for
``World`` -- this module only covers what that stand-in can't: real item
placement, a real second player, and the full ``patch_data.py``/
``fill_slot_data`` wiring.
"""

from __future__ import annotations

import random
import unittest
from argparse import Namespace

import ModuleUpdate

ModuleUpdate.update_ran = True

from BaseClasses import CollectionState, MultiWorld  # noqa: E402 -- must follow ModuleUpdate.update_ran = True above
from Fill import distribute_items_restrictive  # noqa: E402
from Generate import get_seed_name  # noqa: E402
from NetUtils import HintStatus  # noqa: E402
from worlds import AutoWorld  # noqa: E402
from worlds.AutoWorld import call_all  # noqa: E402

from .. import patch_data  # noqa: E402
from ..hint_scans import TRANSLATOR_LORE_HINT_SCANS, translator_lore_hint_locations  # noqa: E402

try:
    from test.general import gen_steps
except ImportError:  # pragma: no cover - only relevant if test/general ever moves
    gen_steps = ("generate_early", "create_regions", "create_items", "set_rules", "generate_basic")

GAME = "Metroid Prime 2: Echoes"


def _build(options_by_player: list[dict], seed: int) -> MultiWorld:
    """Builds and fully generates (through ``pre_output``) a real
    ``MultiWorld`` with one Echoes player per entry of ``options_by_player``
    -- ``test_fill.py``'s single-player ``_build``, generalized to more
    than one player so the "any" mode's foreign-item candidates can be
    exercised against a real second world instead of a hand-built fake."""
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


class TestOffMode(unittest.TestCase):
    def test_no_lore_string_changes_and_no_lore_slot_data_entries(self) -> None:
        multiworld = _build([{"translator_lore_hints": "off"}], seed=1)
        world = multiworld.worlds[1]

        self.assertEqual([], patch_data._translator_lore_string_changes(world))

        lore_scan_ids = {scan.scan_id for scan in TRANSLATOR_LORE_HINT_SCANS}
        hint_scans = world.fill_slot_data()["hint_scans"]
        self.assertEqual(set(), lore_scan_ids & {int(scan_id) for scan_id in hint_scans})


class TestMyItemsMode(unittest.TestCase):
    def test_twenty_two_distinct_own_progression_locations_agree_with_slot_data(self) -> None:
        multiworld = _build([{"translator_lore_hints": "my_items"}], seed=1)
        world = multiworld.worlds[1]

        locations = translator_lore_hint_locations(world)
        self.assertEqual(22, len(locations))
        non_none = [loc for loc in locations if loc is not None]
        # Default options place ~119 almost-entirely-progression items for
        # a single player, so 22 distinct real candidates should always be
        # available (this is not a tight/flaky bound: a below-22 count
        # would mean the default item pool stopped being mostly
        # progression, worth knowing either way).
        self.assertEqual(22, len(non_none))
        self.assertEqual(22, len({(loc.player, loc.address) for loc in non_none}))
        for location in non_none:
            self.assertEqual(1, location.item.player)
            self.assertTrue(location.item.advancement)

        hint_scans = world.fill_slot_data()["hint_scans"]
        for hint_scan, location in zip(TRANSLATOR_LORE_HINT_SCANS, locations, strict=True):
            assert location is not None
            self.assertEqual(
                [location.player, location.address, HintStatus.HINT_PRIORITY],
                hint_scans[str(hint_scan.scan_id)],
            )

    def test_string_changes_and_slot_data_name_the_same_locations(self) -> None:
        multiworld = _build([{"translator_lore_hints": "my_items"}], seed=2)
        world = multiworld.worlds[1]

        locations = translator_lore_hint_locations(world)
        changes = patch_data._translator_lore_string_changes(world)
        hint_scans = world.fill_slot_data()["hint_scans"]

        for hint_scan, location, change in zip(TRANSLATOR_LORE_HINT_SCANS, locations, changes, strict=True):
            self.assertEqual(hint_scan.strg_id, change["strg_id"])
            if location is None:
                self.assertEqual("The Luminoth have nothing more to tell you.", change["strings"][0])
                self.assertNotIn(str(hint_scan.scan_id), hint_scans)
            else:
                self.assertIn(location.item.name, change["strings"][0])
                self.assertIn(location.name, change["strings"][0])
                self.assertEqual(
                    [location.player, location.address, HintStatus.HINT_PRIORITY],
                    hint_scans[str(hint_scan.scan_id)],
                )


class TestAnyModeTwoPlayers(unittest.TestCase):
    def test_candidates_include_foreign_progression_items_with_unspecified_status(self) -> None:
        multiworld = _build(
            [{"translator_lore_hints": "any"}, {"translator_lore_hints": "off"}], seed=1
        )
        world = multiworld.worlds[1]

        locations = translator_lore_hint_locations(world)
        non_none = [loc for loc in locations if loc is not None]
        self.assertEqual(22, len(non_none))
        # Every candidate is either this player's own item (anywhere) or a
        # foreign item placed in this player's own world -- never a
        # foreign item sitting in someone else's world.
        for location in non_none:
            if location.item.player != world.player:
                self.assertEqual(world.player, location.player)

        foreign = [loc for loc in non_none if loc.item.player != world.player]
        hint_scans = world.fill_slot_data()["hint_scans"]
        for hint_scan, location in zip(TRANSLATOR_LORE_HINT_SCANS, locations, strict=True):
            if location is not None and location.item.player != world.player:
                self.assertEqual(
                    [location.player, location.address, HintStatus.HINT_UNSPECIFIED],
                    hint_scans[str(hint_scan.scan_id)],
                )
        # Not a strict requirement of correctness on any single seed, but
        # exercising the actual cross-player branch is the point of this
        # test -- if this ever comes back empty, bump/change the seed
        # rather than deleting the assertion.
        self.assertGreater(len(foreign), 0)


class TestDeterminism(unittest.TestCase):
    def test_same_seed_and_options_choose_the_same_locations(self) -> None:
        options = [{"translator_lore_hints": "my_items"}]
        world_a = _build(options, seed=5).worlds[1]
        world_b = _build(options, seed=5).worlds[1]

        addresses_a = [loc.address if loc else None for loc in translator_lore_hint_locations(world_a)]
        addresses_b = [loc.address if loc else None for loc in translator_lore_hint_locations(world_b)]
        self.assertEqual(addresses_a, addresses_b)


if __name__ == "__main__":
    unittest.main()
