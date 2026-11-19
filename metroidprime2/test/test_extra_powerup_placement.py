"""``extra_powerup_placement``: Double Damage, Unlimited Missiles and
Unlimited Beam Ammo are moved to the late locations of the multiworld after
the fill (``placement.py``).

Real fills on fixed seeds, the way ``test_fill.py`` does them, then the sphere
order of the finished multiworld is measured independently of the code under
test (a plain ``MultiWorld.get_spheres`` walk).
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
from worlds import AutoWorld  # noqa: E402
from worlds.AutoWorld import call_all  # noqa: E402

from .. import placement  # noqa: E402
from ..options import ExtraPowerupPlacement  # noqa: E402

try:
    from test.general import gen_steps
except ImportError:  # pragma: no cover
    gen_steps = ("generate_early", "create_regions", "create_items", "set_rules", "generate_basic")

GAME = "Metroid Prime 2: Echoes"

_EXTRAS_ON = {
    "enable_unlimited_missiles_pickup": True,
    "enable_double_damage_pickup": True,
    "enable_unlimited_beam_ammo_pickup": True,
}


def _build(per_player_options: list[dict], seed: int) -> MultiWorld:
    players = len(per_player_options)
    multiworld = MultiWorld(players)
    multiworld.player_name = {}
    for player in range(1, players + 1):
        multiworld.game[player] = GAME
        multiworld.player_name[player] = f"Tester{player}"
    multiworld.set_seed(seed)
    random.seed(multiworld.seed)
    multiworld.seed_name = get_seed_name(random)

    args = Namespace()
    for name, option in AutoWorld.AutoWorldRegister.world_types[GAME].options_dataclass.type_hints.items():
        setattr(
            args,
            name,
            {
                player: option.from_any(per_player_options[player - 1].get(name, option.default))
                for player in range(1, players + 1)
            },
        )
    multiworld.set_options(args)
    multiworld.state = CollectionState(multiworld)
    for step in gen_steps:
        call_all(multiworld, step)
    return multiworld


def _spheres(multiworld: MultiWorld) -> dict:
    """Location -> sphere index, with the playthrough's unreachable
    locations last, computed straight from ``get_spheres``."""
    order = {}
    reachable_done = False
    index = 0
    for sphere in multiworld.get_spheres():
        if not sphere:
            reachable_done = True
            continue
        for location in sphere:
            order[location] = index
        index += 1
    del reachable_done
    return order


def _own_extras(multiworld: MultiWorld, player: int) -> list:
    return [
        location
        for location in multiworld.get_filled_locations()
        if location.item
        and location.item.player == player
        and location.item.name in placement.EXTRA_POWERUP_NAMES
        and location.address is not None
    ]


class _PlacementCase(unittest.TestCase):
    mode = "late"
    fraction = 0.5
    seeds: tuple[int, ...] = (1, 2, 3, 4)
    extra_options: dict = {}

    def test_every_extra_ends_up_late_and_the_game_is_still_beatable(self) -> None:
        if type(self) is _PlacementCase:
            return
        for seed in self.seeds:
            with self.subTest(seed=seed):
                options = {**_EXTRAS_ON, "extra_powerup_placement": self.mode, **self.extra_options}
                multiworld = _build([options], seed)
                distribute_items_restrictive(multiworld)
                call_all(multiworld, "post_fill")
                self.assertTrue(multiworld.can_beat_game())

                order = _spheres(multiworld)
                ranked = sorted(
                    (loc for loc in order if loc.address is not None), key=lambda loc: order[loc]
                )
                cut = order[ranked[int(len(ranked) * self.fraction)]]
                extras = _own_extras(multiworld, 1)
                self.assertEqual(3, len(extras))
                for location in extras:
                    self.assertGreaterEqual(
                        order[location], cut, f"{location.item.name} at {location.name} is before sphere {cut}"
                    )


class TestLate(_PlacementCase):
    mode = "late"
    fraction = 0.5


class TestVeryLate(_PlacementCase):
    mode = "very_late"
    fraction = 0.75


class TestLateWithTrapsAndSlots(_PlacementCase):
    mode = "late"
    extra_options = {"trap_percentage": 30}
    seeds = (1, 2)


class TestAnywhereLeavesTheFillAlone(unittest.TestCase):
    def test_nothing_moves(self) -> None:
        multiworld = _build([{**_EXTRAS_ON, "extra_powerup_placement": "anywhere"}], 1)
        distribute_items_restrictive(multiworld)
        before = {loc.name: loc.item.name for loc in multiworld.get_filled_locations()}
        call_all(multiworld, "post_fill")
        after = {loc.name: loc.item.name for loc in multiworld.get_filled_locations()}
        self.assertEqual(before, after)


class TestLateOnlyMovesWhatItShould(unittest.TestCase):
    def test_only_the_extras_and_their_partners_change(self) -> None:
        multiworld = _build([{**_EXTRAS_ON, "extra_powerup_placement": "late"}], 2)
        distribute_items_restrictive(multiworld)
        before = {loc.name: loc.item.name for loc in multiworld.get_filled_locations()}
        moved = placement.defer_extra_powerups(multiworld.worlds[1])
        after = {loc.name: loc.item.name for loc in multiworld.get_filled_locations()}
        changed = {name for name in before if before[name] != after[name]}
        self.assertLessEqual(len(changed), 2 * moved)
        self.assertEqual(sorted(before.values()), sorted(after.values()), "swaps must conserve items")


class TestTwoPlayers(unittest.TestCase):
    def test_extras_end_up_late_in_a_two_player_multiworld(self) -> None:
        for seed in (1, 2):
            with self.subTest(seed=seed):
                multiworld = _build(
                    [{**_EXTRAS_ON, "extra_powerup_placement": "late"}, {"extra_powerup_placement": "late"}], seed
                )
                distribute_items_restrictive(multiworld)
                call_all(multiworld, "post_fill")
                self.assertTrue(multiworld.can_beat_game())
                order = _spheres(multiworld)
                ranked = sorted((loc for loc in order if loc.address is not None), key=lambda loc: order[loc])
                cut = order[ranked[len(ranked) // 2]]
                for location in _own_extras(multiworld, 1):
                    self.assertGreaterEqual(order[location], cut)


class TestHelpers(unittest.TestCase):
    def test_late_fractions_cover_every_choice_but_anywhere(self) -> None:
        self.assertEqual(
            {ExtraPowerupPlacement.option_late, ExtraPowerupPlacement.option_very_late},
            set(placement.LATE_FRACTION),
        )

    def test_partner_preference_orders_by_how_little_it_matters_early(self) -> None:
        from BaseClasses import Item, ItemClassification

        def item(classification: ItemClassification) -> Item:
            return Item("x", classification, None, 1)

        order = [
            placement._partner_preference(item(c))
            for c in (
                ItemClassification.filler,
                ItemClassification.useful,
                ItemClassification.progression_skip_balancing,
                ItemClassification.progression,
                ItemClassification.trap,
            )
        ]
        self.assertEqual([0, 0, 1, 2, 3], order)
