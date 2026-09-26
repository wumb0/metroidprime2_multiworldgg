"""M1a tests: items.py / locations.py static data sanity checks.

Plain unittest.TestCase -- no WorldTestBase / AutoWorld dependency, since
this only exercises the static ITEM_TABLE / LOCATION_TABLE data, not a
generated World.
"""

from __future__ import annotations

import unittest

from .. import constants
from ..items import ITEM_TABLE, gains_for
from ..locations import LOCATION_GROUPS, LOCATION_TABLE


class TestLocations(unittest.TestCase):
    def test_location_count(self) -> None:
        self.assertEqual(119, len(LOCATION_TABLE))

    def test_unique_names(self) -> None:
        names = [loc.name for loc in LOCATION_TABLE]
        self.assertEqual(len(names), len(set(names)))

    def test_codes_contiguous_from_base(self) -> None:
        codes = sorted(loc.code for loc in LOCATION_TABLE)
        expected = [constants.LOCATION_ID_BASE + i for i in range(119)]
        self.assertEqual(expected, codes)

    def test_boss_and_guardian_group_sizes(self) -> None:
        self.assertEqual(9, len(LOCATION_GROUPS["Boss"]))
        self.assertEqual(3, len(LOCATION_GROUPS["Guardian"]))
        # Guardian is a subset of Boss.
        self.assertTrue(LOCATION_GROUPS["Guardian"] <= LOCATION_GROUPS["Boss"])


class TestItems(unittest.TestCase):
    def test_item_codes_unique_and_contiguous(self) -> None:
        codes = sorted(item.code for item in ITEM_TABLE.values())
        expected = [constants.ITEM_ID_BASE + i for i in range(len(ITEM_TABLE))]
        self.assertEqual(expected, codes)

    def test_default_pool_total(self) -> None:
        # See items.py module docstring: the literal per-row default pool
        # counts (using default option values) sum to 118, one short of
        # the 119 pickup locations -- item_pool.py's padding step (filler
        # Missile Expansion) is designed to cover exactly this kind of
        # shortfall. PLAN.md's illustrative "26 majors + ... = 119"
        # arithmetic has an off-by-one (the suit and grapple progressive
        # trios always contribute a fixed total of 2 each, regardless of
        # the progressive_suit/progressive_grapple toggle, which pins the
        # "majors" total at 25, not 26).
        total = sum(item.default_pool_count for item in ITEM_TABLE.values())
        self.assertEqual(118, total)
        # Sanity: still only one short of the number of locations.
        self.assertEqual(1, len(LOCATION_TABLE) - total)

    def test_models_are_valid_opr_models(self) -> None:
        for item in ITEM_TABLE.values():
            self.assertIn(
                item.model,
                constants.OPR_MODEL_NAMES,
                f"{item.name}: model {item.model!r} not a known OPR model",
            )

    def test_gains_for_progressive_suit_second_copy(self) -> None:
        self.assertEqual(((14, 1),), gains_for("Progressive Suit", 1))

    def test_gains_for_progressive_suit_first_copy(self) -> None:
        self.assertEqual(((13, 1),), gains_for("Progressive Suit", 0))

    def test_gains_for_missile_launcher(self) -> None:
        gains = gains_for("Missile Launcher")
        self.assertIn((73, 1), gains)
        self.assertIn((44, 5), gains)


if __name__ == "__main__":
    unittest.main()
