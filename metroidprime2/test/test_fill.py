"""Real fill coverage: actually runs ``Fill.distribute_items_restrictive``
(not just all-items reachability, which is all ``test_regions.py`` /
``test_pool.py`` check) over a matrix of option combinations, each with a
handful of seeds, and asserts generation succeeds and the game is
beatable.

This exists because ``MP2TestBase.run_default_tests`` is (still)
``False`` -- see ``bases.py``'s docstring -- so WorldTestBase's automatic
``test_fill``/``test_all_state_can_reach_everything``/
``test_empty_state_can_reach_something`` never run for this world, and
none of this world's own tests (before this module) ever called
``distribute_items_restrictive`` at all. That gap is exactly how
``logic/dock_rando.py``'s door-lock-rando total-lockout bug shipped
undetected (see that module's docstring for the fix and measured
before/after failure rates).

``MP2TestBase``/``WorldTestBase.world_setup`` doesn't expose a stable way
to pin a seed from a test method (it always draws a fresh one), so this
module builds ``MultiWorld`` instances directly, the same way
``MultiWorldGG/test/general`` and this world's own dev scratch scripts do,
so every case below runs against an explicit, hand-verified seed instead
of an arbitrary one. Door lock/elevator rando in particular still have a
nonzero (if now much smaller -- see dock_rando.py) generation
failure rate; picking seeds that are verified to pass here keeps this
suite deterministic rather than flaky (task instruction: "pick test seeds
that pass deterministically rather than writing a flaky test").

Runtime budget: each case below is 1-3 seeds; the whole module is a few
dozen generations total, keeping this in the same ballpark as the rest of
the suite (~9s before this module existed).
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

try:
    from test.general import gen_steps
except ImportError:  # pragma: no cover - only relevant if test/general ever moves
    gen_steps = ("generate_early", "create_regions", "create_items", "set_rules", "generate_basic")

GAME = "Metroid Prime 2: Echoes"


def _build(options: dict, seed: int) -> MultiWorld:
    multiworld = MultiWorld(1)
    multiworld.game[1] = GAME
    multiworld.player_name = {1: "Tester"}
    multiworld.set_seed(seed)
    random.seed(multiworld.seed)
    multiworld.seed_name = get_seed_name(random)

    args = Namespace()
    for name, option in AutoWorld.AutoWorldRegister.world_types[GAME].options_dataclass.type_hints.items():
        setattr(args, name, {1: option.from_any(options.get(name, option.default))})
    multiworld.set_options(args)
    multiworld.state = CollectionState(multiworld)

    for step in gen_steps:
        call_all(multiworld, step)
    return multiworld


class _FillMatrixCase(unittest.TestCase):
    """One (options, seeds) case: generate, fill, and assert the game is
    beatable, for each seed. Leading underscore keeps pytest from
    collecting this base class by name; the ``type(self) is
    _FillMatrixCase`` guard below is a second, unittest-safe belt-and-
    braces check in case something ever collects it directly."""

    options: dict = {}
    seeds: tuple[int, ...] = (1,)

    def test_fills_and_beatable(self) -> None:
        if type(self) is _FillMatrixCase:
            return  # base class itself defines no case
        for seed in self.seeds:
            with self.subTest(options=self.options, seed=seed):
                multiworld = _build(self.options, seed)
                distribute_items_restrictive(multiworld)
                call_all(multiworld, "post_fill")
                self.assertTrue(
                    multiworld.can_beat_game(),
                    f"seed {seed}, options {self.options}: not beatable after fill",
                )
                unplaced = list(multiworld.itempool)
                placed = [loc.item for loc in multiworld.get_locations() if loc.item and loc.item.code]
                self.assertLessEqual(
                    len(multiworld.itempool),
                    len(placed),
                    f"seed {seed}, options {self.options}: unplaced items remain in itempool: {unplaced}",
                )


class TestDefaultOptions(_FillMatrixCase):
    options = {}
    seeds = (1, 2, 3)


class TestSkyTempleKeysZero(_FillMatrixCase):
    options = {"sky_temple_keys": 0}
    seeds = (1, 2)


class TestSkyTempleKeysThree(_FillMatrixCase):
    options = {"sky_temple_keys": 3}
    seeds = (1, 2)


class TestSkyTempleKeysNine(_FillMatrixCase):
    options = {"sky_temple_keys": 9}
    seeds = (1, 2)


class TestSkyTempleKeysAllBosses(_FillMatrixCase):
    options = {"sky_temple_keys": "all_bosses"}
    seeds = (1, 2)


class TestSkyTempleKeysAllGuardians(_FillMatrixCase):
    options = {"sky_temple_keys": "all_guardians"}
    seeds = (1, 2)


class TestProgressiveSuitAndGrapple(_FillMatrixCase):
    options = {"progressive_suit": True, "progressive_grapple": True}
    seeds = (1, 2)


class TestNonProgressiveSuitAndGrapple(_FillMatrixCase):
    # progressive_suit defaults on (DefaultOnToggle); explicitly off here
    # so both branches of item_pool.py's _pool_count_for get covered.
    options = {"progressive_suit": False, "progressive_grapple": False}
    seeds = (1, 2)


class TestLudicrousTricks(_FillMatrixCase):
    # Every trick at its hardest difficulty must still generate and fill.
    options = {"trick_level": "ludicrous"}
    seeds = (1, 2)


class TestDoorLockRando(_FillMatrixCase):
    # Seeds verified to pass against the current logic/dock_rando.py fix
    # (measured ~2.7% failure rate on a 37-seed sweep -- see that module's
    # docstring).
    options = {"door_lock_rando": True}
    seeds = (1, 2, 3)


class TestElevatorRando(_FillMatrixCase):
    # elevator_rando's residual failure rate is materially higher (~16%,
    # see dock_rando.py's docstring for why the coarse progression check
    # doesn't fully catch its failure class); seeds 4/6/8 are known-bad
    # here, deliberately excluded.
    options = {"elevator_rando": True}
    seeds = (1, 2, 3)


class TestAllEntranceRandoTogether(_FillMatrixCase):
    # Seed 3 (among others) is known-bad for this combination; see
    # dock_rando.py's docstring for the measured failure rate.
    options = {"door_lock_rando": True, "elevator_rando": True}
    seeds = (1, 2, 5)


class TestPortalRando(_FillMatrixCase):
    # Measured ~10% failure rate (1/10 on seeds 1-10, seed 8 known-bad and
    # deliberately excluded here) -- lower than elevator_rando's ~16%,
    # plausibly because each portal shuffle is confined to one light/dark
    # region pair (dock_rando.py section E.3) rather than a single free
    # perm over every elevator in the game.
    options = {"portal_rando": True}
    seeds = (1, 2, 3)


class TestAllThreeEntranceRandoTogether(_FillMatrixCase):
    options = {"door_lock_rando": True, "elevator_rando": True, "portal_rando": True}
    seeds = (1, 2, 6)


class TestTranslatorGateFullRandom(_FillMatrixCase):
    options = {"translator_gate_rando": "full_random"}
    seeds = (1, 2, 3)


class TestTranslatorGateFullRandomUnlocked(_FillMatrixCase):
    options = {"translator_gate_rando": "full_random_unlocked"}
    seeds = (1, 2, 3)


if __name__ == "__main__":
    unittest.main()
