"""Tests for ``pickup_encoding.py`` -- the one-bit-per-pickup counter
layout that replaced the additive single-counter scheme (PLAN.md section
P). Correctness here matters more than usual: a wrong ``(item, bit)``
assignment, or a decode that drops/duplicates a bit, corrupts a location
check (and the item sent for it) the same way a wrong answer from the
now-removed ``location_reconciliation`` subset-sum search used to.
"""

from __future__ import annotations

import unittest

from .. import constants
from ..data import load_json
from ..items import ITEM_TABLE
from ..locations import LOCATION_TABLE
from ..pickup_encoding import BITS_PER_COUNTER, PICKUP_COUNTER_ITEMS, Decoded, counter_and_amount, decode


def _empty_inventory() -> dict[int, tuple[int, int]]:
    return dict.fromkeys(constants.PICKUP_COUNTER_ITEMS, (0, 0))


def _reserved_item_ids() -> set[int]:
    """Every ``PlayerItemEnum`` id randovania's own resource database
    allocates (``data/logic_database/header.json``'s
    ``resource_database.items[*].extra.item_id``), unioned with every id
    this world's own ``ITEM_TABLE`` gains write to (including progressive
    stages) -- the complete set of ids a pickup counter must never
    collide with.

    This is exactly the check that would have caught section P's first
    slot allocation (``PersistentCounter1..8``, ids 67-74): 71/72/73 are
    randovania's Temporary1/Temporary2/MissileLauncher, live ids this
    world's own ``items.py``/``client/receive_items.py`` already depend
    on -- see ``constants.PICKUP_COUNTER_ITEMS``'s docstring.
    """
    header = load_json("logic_database/header.json")
    reserved = {
        entry["extra"]["item_id"]
        for entry in header["resource_database"]["items"].values()
        if "item_id" in entry.get("extra", {})
    }
    for item_data in ITEM_TABLE.values():
        for item_id, _amount in item_data.gains:
            reserved.add(item_id)
        if item_data.progression is not None:
            for stage in item_data.progression:
                for item_id, _amount in stage:
                    reserved.add(item_id)
    return reserved


class TestCounterAndAmount(unittest.TestCase):
    def test_round_trips_every_real_index(self) -> None:
        for index in range(len(LOCATION_TABLE)):
            item_id, bit = counter_and_amount(index)
            inventory = _empty_inventory()
            inventory[item_id] = (bit, 0)
            decoded = decode(inventory)
            self.assertEqual([index], decoded.indices, f"index {index} did not round-trip")
            self.assertEqual([], decoded.stray, f"index {index} produced unexpected stray bits")
            self.assertEqual([(item_id, -bit)], decoded.deltas)

    def test_index_0_and_index_bits_per_counter_minus_1_share_the_first_counter(self) -> None:
        first_item, first_bit = counter_and_amount(0)
        last_item, last_bit = counter_and_amount(BITS_PER_COUNTER - 1)
        self.assertEqual(first_item, last_item)
        self.assertEqual(PICKUP_COUNTER_ITEMS[0], first_item)
        self.assertEqual(1, first_bit)
        self.assertEqual(1 << (BITS_PER_COUNTER - 1), last_bit)

    def test_index_bits_per_counter_lands_on_the_second_counter(self) -> None:
        item_id, bit = counter_and_amount(BITS_PER_COUNTER)
        self.assertEqual(PICKUP_COUNTER_ITEMS[1], item_id)
        self.assertEqual(1, bit)


class TestFullCounterRoundTrip(unittest.TestCase):
    """PLAN.md section P's constraint-1 escape hatch, as an executable
    check. A full counter's bit complement (``2**BITS_PER_COUNTER - 1``,
    30 bits) is well past what ``ppc_asm.assembler.ppc.li``
    (``addi rD, r0, SIMM16``, asserting ``-32768 <= literal < 32768``)
    could ever consume -- that's exactly why
    ``client/game_interface.py``'s ``_wide_decrement_patch`` exists
    instead of OPR's unmodified ``adjust_item_amount_patch`` for the
    pickup counters (see ``test_game_interface.py``'s
    ``TestConsumeCounters`` for the assembly-level check of that patch).
    This module only needs to confirm ``decode`` itself has no hidden
    ceiling below a full counter's value."""

    def test_full_counter_value_round_trips_through_decode(self) -> None:
        full_value = (1 << BITS_PER_COUNTER) - 1
        item_id = PICKUP_COUNTER_ITEMS[0]
        inventory = _empty_inventory()
        inventory[item_id] = (full_value, 0)

        decoded = decode(inventory)

        self.assertEqual([(item_id, -full_value)], decoded.deltas)
        # Every one of BITS_PER_COUNTER bits decodes to either a real index
        # or a stray report -- decode() must account for all of them, none
        # silently dropped.
        self.assertEqual(BITS_PER_COUNTER, len(decoded.indices) + len(decoded.stray))


class TestDecodeMultiBitMultiCounter(unittest.TestCase):
    def test_bits_spread_across_several_counters(self) -> None:
        indices = [0, 20, 44, 60, 118]
        inventory = _empty_inventory()
        expected_deltas: dict[int, int] = {}
        for index in indices:
            item_id, bit = counter_and_amount(index)
            amount, _capacity = inventory[item_id]
            inventory[item_id] = (amount | bit, 0)
            expected_deltas[item_id] = expected_deltas.get(item_id, 0) | bit

        decoded = decode(inventory)
        self.assertEqual(sorted(indices), decoded.indices)
        self.assertEqual([], decoded.stray)
        self.assertEqual(
            sorted(expected_deltas.items()),
            sorted((item_id, -delta) for item_id, delta in decoded.deltas),
        )


class TestStrayBitReporting(unittest.TestCase):
    def test_bit_past_the_last_real_index_is_stray(self) -> None:
        # The last counter (item 70) only uses indices 90..118 -> bits
        # 0..28; bit 29 (value 1 << 29) decodes past the last real index
        # and must be reported as stray, not silently accepted as a
        # location check for a pickup that doesn't exist.
        last_item = PICKUP_COUNTER_ITEMS[-1]
        unused_bit = 1 << (BITS_PER_COUNTER - 1)
        last_real_index = len(LOCATION_TABLE) - 1
        # Sanity: confirm this bit really is one past the last real index
        # mapped to this counter, i.e. genuinely unused by any pickup.
        slot = PICKUP_COUNTER_ITEMS.index(last_item)
        self.assertGreater(slot * BITS_PER_COUNTER + (BITS_PER_COUNTER - 1), last_real_index)

        inventory = _empty_inventory()
        inventory[last_item] = (unused_bit, 0)
        decoded = decode(inventory)
        self.assertEqual([], decoded.indices)
        self.assertEqual([(last_item, unused_bit)], decoded.stray)
        # Still consumed even though it's stray -- nothing is left behind
        # to corrupt a future decode (PLAN.md section P point 2).
        self.assertEqual([(last_item, -unused_bit)], decoded.deltas)

    def test_stray_bit_does_not_suppress_good_indices_on_the_same_counter(self) -> None:
        last_item = PICKUP_COUNTER_ITEMS[-1]
        slot = PICKUP_COUNTER_ITEMS.index(last_item)
        good_index = len(LOCATION_TABLE) - 1
        good_bit = 1 << (good_index - slot * BITS_PER_COUNTER)
        stray_bit = 1 << (BITS_PER_COUNTER - 1)

        inventory = _empty_inventory()
        inventory[last_item] = (good_bit | stray_bit, 0)
        decoded = decode(inventory)
        self.assertEqual([good_index], decoded.indices)
        self.assertEqual([(last_item, stray_bit)], decoded.stray)

    def test_bit_above_bits_per_counter_range_is_stray_overflow(self) -> None:
        # A value that grew past what any pickup could ever legitimately
        # write (bit BITS_PER_COUNTER and above) must not be silently
        # ignored either.
        item_id = PICKUP_COUNTER_ITEMS[0]
        overflow_bit = 1 << BITS_PER_COUNTER
        inventory = _empty_inventory()
        inventory[item_id] = (overflow_bit, 0)
        decoded = decode(inventory)
        self.assertEqual([], decoded.indices)
        self.assertEqual([(item_id, overflow_bit)], decoded.stray)
        self.assertEqual([(item_id, -overflow_bit)], decoded.deltas)


class TestDecodedDefaults(unittest.TestCase):
    def test_all_zero_inventory_decodes_to_nothing(self) -> None:
        decoded = decode(_empty_inventory())
        self.assertEqual(Decoded(), decoded)

    def test_missing_counter_keys_are_treated_as_zero(self) -> None:
        # decode() must tolerate an inventory snapshot missing one of the
        # counter ids outright (defensive: EchoesInterface.read_inventory
        # always returns all 109 items in practice, but decode() shouldn't
        # crash if a caller passes a partial dict, e.g. in a future test).
        decoded = decode({})
        self.assertEqual(Decoded(), decoded)


class TestReservedItemIdsDisjoint(unittest.TestCase):
    """Guards against this design's own near-miss: the first version of
    ``PICKUP_COUNTER_ITEMS`` (PersistentCounter1..8, ids 67-74) collided
    with 71/72/73 -- randovania-allocated ids this world's own item model
    already depends on (Temporary1/Temporary2/MissileLauncher) -- and that
    was only caught by manual code review, not a test. This derives the
    full reserved-id set programmatically and keeps another id from
    silently becoming unsafe the same way.
    """

    def test_pickup_counter_items_are_disjoint_from_every_reserved_id(self) -> None:
        reserved = _reserved_item_ids()
        overlap = set(PICKUP_COUNTER_ITEMS) & reserved
        self.assertEqual(
            set(),
            overlap,
            f"PICKUP_COUNTER_ITEMS overlaps randovania/ITEM_TABLE-reserved ids: {overlap}",
        )


if __name__ == "__main__":
    unittest.main()
