"""``missile_expansion_progression: required_only``: only as many Missile
Expansions as logic can ever ask for stay progression; the rest are
``useful``. Logic only counts the progression ones (``CollectionState``
counts nothing else), which is sound because the required count is what the
highest Missile requirement needs.
"""

from __future__ import annotations

import unittest
from collections import Counter

from BaseClasses import ItemClassification
from Fill import distribute_items_restrictive
from worlds.AutoWorld import call_all

from ..item_pool import _MIN_MISSILE_EXPANSIONS
from .bases import MP2TestBase
from .test_extra_powerup_placement import _build


def _expansions(test: MP2TestBase) -> list:
    return [i for i in test.multiworld.itempool if i.player == test.player and i.name == "Missile Expansion"]


class TestAllByDefault(MP2TestBase):
    def test_every_missile_expansion_is_progression(self) -> None:
        expansions = _expansions(self)
        self.assertEqual(34, len(expansions))
        for item in expansions:
            self.assertTrue(item.advancement)
            self.assertTrue(item.classification & ItemClassification.skip_balancing)


class TestRequiredOnly(MP2TestBase):
    options = {"missile_expansion_progression": "required_only"}

    def test_only_the_required_count_is_progression(self) -> None:
        expansions = _expansions(self)
        self.assertEqual(34, len(expansions))
        progression = [item for item in expansions if item.advancement]
        self.assertEqual(_MIN_MISSILE_EXPANSIONS, len(progression))
        for item in expansions:
            if not item.advancement:
                self.assertEqual(ItemClassification.useful, item.classification)

    def test_other_items_are_untouched(self) -> None:
        for item in self.multiworld.itempool:
            if item.name == "Power Bomb Expansion":
                self.assertTrue(item.classification & ItemClassification.skip_balancing)
            if item.name == "Energy Tank":
                self.assertEqual(ItemClassification.progression, item.classification)

    def test_logic_counts_enough_missiles_for_the_highest_requirement(self) -> None:
        # Every progression item collected: logic must still see >= 65 missiles
        # (the highest requirement in the database) from expansions + launcher.
        state = self.multiworld.get_all_state()
        self.assertEqual(_MIN_MISSILE_EXPANSIONS, state.count("Missile Expansion", self.player))
        missiles = 5 * (state.count("Missile Expansion", self.player) + state.count("Missile Launcher", self.player))
        self.assertGreaterEqual(missiles, 65 - 5)  # the Seeker Launcher carries the other 5


class TestRequiredOnlyWithFewExpansions(MP2TestBase):
    """With traps eating the expansions down to the logic minimum, nothing is
    left to downgrade."""

    options = {"missile_expansion_progression": "required_only", "trap_percentage": 100, "power_bomb_dummy_slots": 0}

    def test_all_remaining_stay_progression(self) -> None:
        expansions = _expansions(self)
        self.assertEqual(_MIN_MISSILE_EXPANSIONS, len(expansions))
        self.assertTrue(all(item.advancement for item in expansions))


class TestFillsAndStaysBeatable(unittest.TestCase):
    def test_real_fills(self) -> None:
        for seed in (1, 2, 3):
            for extra in ({}, {"trap_percentage": 40}, {"missile_expansions_unlock_launcher": True}):
                with self.subTest(seed=seed, extra=extra):
                    multiworld = _build([{"missile_expansion_progression": "required_only", **extra}], seed)
                    distribute_items_restrictive(multiworld)
                    call_all(multiworld, "post_fill")
                    self.assertTrue(multiworld.can_beat_game())
                    counts = Counter(
                        loc.item.classification & ItemClassification.progression
                        for loc in multiworld.get_filled_locations()
                        if loc.item and loc.item.name == "Missile Expansion"
                    )
                    self.assertLessEqual(counts[ItemClassification.progression], _MIN_MISSILE_EXPANSIONS)
