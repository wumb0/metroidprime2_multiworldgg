"""M1 tests: item_pool.py -- pool sizes across Sky Temple Key modes and
progressive-item toggles. See ``PLAN.md`` sections F and K (M1).
"""

from __future__ import annotations

from collections import Counter

from .bases import MP2TestBase


def _own_pool_names(test: MP2TestBase) -> list[str]:
    return [item.name for item in test.multiworld.itempool if item.player == test.player]


def _own_precollected_names(test: MP2TestBase) -> list[str]:
    return [item.name for item in test.multiworld.precollected_items[test.player]]


class TestSkyTempleKeysNumeric(MP2TestBase):
    """Numeric N: keys 1..N enter the general pool, keys N+1..9 are
    precollected; no locations are locked, so the pool always pads/trims
    back up to all 119 locations."""

    options = {"sky_temple_keys": 0}

    def test_pool_size_and_precollection(self) -> None:
        pool_names = _own_pool_names(self)
        precollected_names = _own_precollected_names(self)
        self.assertEqual(119, len(pool_names))
        stk_in_pool = [n for n in pool_names if n.startswith("Sky Temple Key")]
        stk_precollected = [n for n in precollected_names if n.startswith("Sky Temple Key")]
        self.assertEqual(0, len(stk_in_pool))
        self.assertEqual(9, len(stk_precollected))
        self.assertEqual(0, len(self.world.sky_temple_key_locations))


class TestSkyTempleKeysNumericThree(MP2TestBase):
    options = {"sky_temple_keys": 3}

    def test_pool_size_and_precollection(self) -> None:
        pool_names = _own_pool_names(self)
        precollected_names = _own_precollected_names(self)
        self.assertEqual(119, len(pool_names))
        stk_in_pool = sorted(n for n in pool_names if n.startswith("Sky Temple Key"))
        stk_precollected = sorted(n for n in precollected_names if n.startswith("Sky Temple Key"))
        self.assertEqual(["Sky Temple Key 1", "Sky Temple Key 2", "Sky Temple Key 3"], stk_in_pool)
        self.assertEqual(6, len(stk_precollected))
        self.assertEqual(0, len(self.world.sky_temple_key_locations))


class TestSkyTempleKeysNumericNine(MP2TestBase):
    options = {"sky_temple_keys": 9}

    def test_pool_size_and_precollection(self) -> None:
        pool_names = _own_pool_names(self)
        precollected_names = _own_precollected_names(self)
        self.assertEqual(119, len(pool_names))
        stk_in_pool = [n for n in pool_names if n.startswith("Sky Temple Key")]
        stk_precollected = [n for n in precollected_names if n.startswith("Sky Temple Key")]
        self.assertEqual(9, len(stk_in_pool))
        self.assertEqual(0, len(stk_precollected))
        self.assertEqual(0, len(self.world.sky_temple_key_locations))


class TestSkyTempleKeysAllBosses(MP2TestBase):
    """All 9 keys are locked directly onto the 9 boss/guardian pickup
    locations; none enter the pool or start precollected, so only the
    remaining 119 - 9 = 110 locations need a pool item."""

    options = {"sky_temple_keys": "all_bosses"}

    def test_nine_keys_locked_on_boss_locations(self) -> None:
        self.assertEqual(9, len(self.world.sky_temple_key_locations))
        for location_name in self.world.sky_temple_key_locations:
            location = self.multiworld.get_location(location_name, self.player)
            self.assertIsNotNone(location.item)
            self.assertTrue(location.item.name.startswith("Sky Temple Key"))
            self.assertTrue(location.locked)

    def test_pool_size(self) -> None:
        pool_names = _own_pool_names(self)
        precollected_names = _own_precollected_names(self)
        self.assertEqual(110, len(pool_names))
        self.assertEqual(0, len([n for n in pool_names if n.startswith("Sky Temple Key")]))
        self.assertEqual(0, len([n for n in precollected_names if n.startswith("Sky Temple Key")]))


class TestSkyTempleKeysAllGuardians(MP2TestBase):
    """Keys 1-3 are locked onto the 3 dark temple guardians; keys 4-9 are
    precollected; only 119 - 3 = 116 locations need a pool item."""

    options = {"sky_temple_keys": "all_guardians"}

    def test_three_keys_locked_six_precollected(self) -> None:
        self.assertEqual(3, len(self.world.sky_temple_key_locations))
        for location_name in self.world.sky_temple_key_locations:
            location = self.multiworld.get_location(location_name, self.player)
            self.assertIsNotNone(location.item)
            self.assertTrue(location.item.name.startswith("Sky Temple Key"))

        precollected_names = _own_precollected_names(self)
        stk_precollected = sorted(n for n in precollected_names if n.startswith("Sky Temple Key"))
        self.assertEqual(6, len(stk_precollected))

    def test_pool_size(self) -> None:
        pool_names = _own_pool_names(self)
        self.assertEqual(116, len(pool_names))
        self.assertEqual(0, len([n for n in pool_names if n.startswith("Sky Temple Key")]))


class TestProgressiveSuitOn(MP2TestBase):
    options = {"progressive_suit": True, "progressive_grapple": False}

    def test_progressive_suit_pair_replaced_by_two_progressive_items(self) -> None:
        counts = Counter(_own_pool_names(self))
        self.assertEqual(2, counts["Progressive Suit"])
        self.assertEqual(0, counts["Dark Suit"])
        self.assertEqual(0, counts["Light Suit"])


class TestProgressiveSuitOff(MP2TestBase):
    options = {"progressive_suit": False, "progressive_grapple": False}

    def test_separate_dark_and_light_suit_items(self) -> None:
        counts = Counter(_own_pool_names(self))
        self.assertEqual(0, counts["Progressive Suit"])
        self.assertEqual(1, counts["Dark Suit"])
        self.assertEqual(1, counts["Light Suit"])


class TestProgressiveGrappleOn(MP2TestBase):
    options = {"progressive_suit": False, "progressive_grapple": True}

    def test_progressive_grapple_pair_replaced_by_two_progressive_items(self) -> None:
        counts = Counter(_own_pool_names(self))
        self.assertEqual(2, counts["Progressive Grapple"])
        self.assertEqual(0, counts["Grapple Beam"])
        self.assertEqual(0, counts["Screw Attack"])


class TestProgressiveGrappleOff(MP2TestBase):
    options = {"progressive_suit": False, "progressive_grapple": False}

    def test_separate_grapple_and_screw_attack_items(self) -> None:
        counts = Counter(_own_pool_names(self))
        self.assertEqual(0, counts["Progressive Grapple"])
        self.assertEqual(1, counts["Grapple Beam"])
        self.assertEqual(1, counts["Screw Attack"])


class TestSplitBeamAmmoOn(MP2TestBase):
    options = {"split_beam_ammo": True}

    def test_separate_dark_and_light_ammo_expansions(self) -> None:
        counts = Counter(_own_pool_names(self))
        self.assertEqual(10, counts["Dark Ammo Expansion"])
        self.assertEqual(10, counts["Light Ammo Expansion"])
        self.assertEqual(0, counts["Beam Ammo Expansion"])


class TestSplitBeamAmmoOff(MP2TestBase):
    options = {"split_beam_ammo": False}

    def test_unified_beam_ammo_expansion_replaces_split_pair(self) -> None:
        counts = Counter(_own_pool_names(self))
        self.assertEqual(0, counts["Dark Ammo Expansion"])
        self.assertEqual(0, counts["Light Ammo Expansion"])
        self.assertEqual(20, counts["Beam Ammo Expansion"])
