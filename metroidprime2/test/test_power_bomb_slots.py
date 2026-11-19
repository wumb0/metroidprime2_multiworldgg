"""Power Bomb Expansions as dummy slots (``power_bomb_dummy_slots``,
``power_bomb_gains_removed_power_bombs``).

Traps and the extra pickups used to displace Missile Expansions only. Now up
to ``power_bomb_dummy_slots`` of them displace Power Bomb Expansions instead
(the Missile Expansions they'd have replaced stay), and the main Power Bomb
pickup grants what was given up. ``item_pool.expansion_plan`` computes all of
it from the options alone, so these tests pin it to the pool that really gets
built, and to what logic, the ISO's starting inventory and the client grant.
"""

from __future__ import annotations

import itertools
from collections import Counter

from ..client.receive_items import compute_desired_capacities
from ..item_pool import expansion_plan, power_bomb_main_bonus, removed_expansion_count
from ..items import TRAP_ITEM_NAMES
from ..logic import item_mapping
from ..patch_data import starting_items_config
from .bases import MP2TestBase

_EXTRAS_NAMES = ("Unlimited Missiles", "Double Damage", "Unlimited Beam Ammo")
_EXTRAS = {
    "enable_unlimited_missiles_pickup": True,
    "enable_double_damage_pickup": True,
    "enable_unlimited_beam_ammo_pickup": True,
}


def _own_pool_names(test: MP2TestBase) -> list[str]:
    return [item.name for item in test.multiworld.itempool if item.player == test.player]


class TestNothingToDisplaceByDefault(MP2TestBase):
    """No traps and no extra pickups: the default slot count changes nothing."""

    def test_pool_is_unchanged(self) -> None:
        counts = Counter(_own_pool_names(self))
        self.assertEqual(8, counts["Power Bomb Expansion"])
        self.assertEqual(34, counts["Missile Expansion"])
        self.assertEqual(0, power_bomb_main_bonus(self.world))
        self.assertEqual(0, self.world.fill_slot_data()["power_bomb_main_bonus"])


class TestExtrasTakePowerBombSlots(MP2TestBase):
    options = dict(_EXTRAS)

    def test_pool(self) -> None:
        names = _own_pool_names(self)
        counts = Counter(names)
        self.assertEqual(119, len(names))
        for extra in _EXTRAS_NAMES:
            self.assertEqual(1, counts[extra])
        # Three extras, three slots: the three Power Bomb Expansions give way
        # and every Missile Expansion the extras would have replaced stays.
        self.assertEqual(5, counts["Power Bomb Expansion"])
        self.assertEqual(34, counts["Missile Expansion"])

    def test_missiles_are_not_lost_and_power_bombs_move_to_the_main_pickup(self) -> None:
        self.assertEqual(0, removed_expansion_count(self.world))
        self.assertEqual(3, power_bomb_main_bonus(self.world))
        self.assertEqual(3, self.world.fill_slot_data()["power_bomb_main_bonus"])
        self.assertEqual(0, self.world.fill_slot_data()["missile_launcher_bonus"])

    def test_power_bomb_capacity_is_kept(self) -> None:
        # main (2 + 3) + 5 expansions == the game's cap of 10.
        received = [("Power Bomb", 0)] + [("Power Bomb Expansion", 0)] * 5
        desired = compute_desired_capacities(received, 0, power_bomb_main_bonus=3)
        self.assertEqual(10, desired[43])


class TestSingleExtraTakesOneSlot(MP2TestBase):
    options = {"enable_double_damage_pickup": True}

    def test_one_power_bomb_expansion_given_up(self) -> None:
        counts = Counter(_own_pool_names(self))
        self.assertEqual(7, counts["Power Bomb Expansion"])
        self.assertEqual(34, counts["Missile Expansion"])
        self.assertEqual(1, power_bomb_main_bonus(self.world))


class TestSlotsDisabled(MP2TestBase):
    options = {**_EXTRAS, "power_bomb_dummy_slots": 0}

    def test_extras_take_missile_expansions_as_before(self) -> None:
        counts = Counter(_own_pool_names(self))
        self.assertEqual(8, counts["Power Bomb Expansion"])
        self.assertEqual(31, counts["Missile Expansion"])
        self.assertEqual(0, power_bomb_main_bonus(self.world))
        self.assertEqual(2, removed_expansion_count(self.world))


class TestTrapsTakePowerBombSlotsToo(MP2TestBase):
    options = {**_EXTRAS, "trap_percentage": 50}

    def test_slots_are_capped_by_the_option_and_the_rest_comes_out_of_missiles(self) -> None:
        counts = Counter(_own_pool_names(self))
        traps = sum(counts[trap] for trap in TRAP_ITEM_NAMES)
        self.assertEqual(15, traps)  # 31 Missile Expansions after trimming * 50%
        self.assertEqual(5, counts["Power Bomb Expansion"])  # 3 slots of the 18 traps and extras
        # 31 - 15 traps + the 3 the slots gave back.
        self.assertEqual(31 - 15 + 3, counts["Missile Expansion"])
        self.assertEqual(2 + traps - 3, removed_expansion_count(self.world))
        self.assertEqual(119, sum(counts.values()))


class TestSlotsLeaveTwoPowerBombExpansions(MP2TestBase):
    options = {"trap_percentage": 50, "power_bomb_dummy_slots": 6}

    def test_never_fewer_than_logic_needs(self) -> None:
        counts = Counter(_own_pool_names(self))
        self.assertEqual(2, counts["Power Bomb Expansion"])
        self.assertEqual(6, power_bomb_main_bonus(self.world))
        # Main (2 + 6) alone covers the most any requirement asks for (4).
        self.assertGreaterEqual(2 + 6, 4)


class TestGainsRemovedPowerBombsOff(MP2TestBase):
    options = {**_EXTRAS, "power_bomb_gains_removed_power_bombs": False}

    def test_expansions_still_given_up_but_nothing_added_to_the_main_pickup(self) -> None:
        counts = Counter(_own_pool_names(self))
        self.assertEqual(5, counts["Power Bomb Expansion"])
        self.assertEqual(0, power_bomb_main_bonus(self.world))
        self.assertEqual(0, self.world.fill_slot_data()["power_bomb_main_bonus"])


class TestPlanMatchesPool(MP2TestBase):
    """``expansion_plan`` is what logic and the client trust; the pool has to
    agree with it for every combination of the options that feed it."""

    auto_construct = False

    def test_every_combination(self) -> None:
        for extras, traps, slots in itertools.product(
            (0, 1, 3), (0, 50, 100), (0, 2, 6)
        ):
            options = {"trap_percentage": traps, "power_bomb_dummy_slots": slots}
            for name in list(_EXTRAS)[:extras]:
                options[name] = True
            with self.subTest(options=options):
                self.options = options
                self.world_setup()
                plan = expansion_plan(self.world)
                counts = Counter(_own_pool_names(self))
                self.assertEqual(8 - plan.power_bomb_slots, counts["Power Bomb Expansion"])
                self.assertEqual(extras, plan.extras)
                self.assertEqual(traps_in_pool(counts), plan.traps)
                self.assertEqual(119, sum(counts.values()))
                self.assertLessEqual(plan.power_bomb_slots, slots)
                self.assertGreaterEqual(counts["Power Bomb Expansion"], 2)


def traps_in_pool(counts: Counter) -> int:
    return sum(counts[trap] for trap in TRAP_ITEM_NAMES)


class TestLogicCountsTheBonus(MP2TestBase):
    options = dict(_EXTRAS)

    def test_main_pickup_counts_its_bonus(self) -> None:
        kind, count = item_mapping.expression("PowerBomb", self.player, False, False, 0, 3)
        self.assertEqual("count", kind)
        self.collect(self.get_item_by_name("Power Bomb"))
        self.assertEqual(5, count(self.multiworld.state))
        self.collect(self.get_item_by_name("Power Bomb Expansion"))
        self.assertEqual(6, count(self.multiworld.state))

    def test_expansions_alone_never_get_a_bonus(self) -> None:
        _, count = item_mapping.expression("PowerBomb", self.player, True, True, 0, 3)
        self.collect(self.get_item_by_name("Power Bomb Expansion"))
        self.assertEqual(1, count(self.multiworld.state))


class TestStartingMainPowerBombCarriesTheBonus(MP2TestBase):
    options = {**_EXTRAS}

    def test_precollected_power_bomb(self) -> None:
        self.multiworld.push_precollected(self.multiworld.create_item("Power Bomb", self.player))
        capacities = {entry["item"]: entry["capacity"] for entry in starting_items_config(self.world)}
        self.assertEqual(2 + 3, capacities[43])

    def test_precollected_expansion_alone_still_grants_nothing(self) -> None:
        self.multiworld.push_precollected(self.multiworld.create_item("Power Bomb Expansion", self.player))
        capacities = {entry["item"]: entry["capacity"] for entry in starting_items_config(self.world)}
        self.assertNotIn(43, capacities)
