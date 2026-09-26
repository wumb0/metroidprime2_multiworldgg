"""M3 tests: ``client/receive_items.py``'s pure functions --
``compute_desired_capacities`` and ``plan_grants``. See PLAN.md sections J
and K (M3).
"""

from __future__ import annotations

import unittest

from ..client import receive_items
from ..client.receive_items import compute_desired_capacities, plan_grants


def _received(*names: str) -> list[tuple[str, int]]:
    """Builds a ``received`` list where every item is from sender slot 2
    (a remote sender) -- sender attribution isn't exercised by
    ``compute_desired_capacities``/``plan_grants``, only by client.py."""
    return [(name, 2) for name in names]


class TestMissileGating(unittest.TestCase):
    def test_no_launcher_no_missiles(self) -> None:
        desired = compute_desired_capacities(_received("Missile Expansion", "Missile Expansion"), 0)
        self.assertEqual(0, desired[44])
        self.assertEqual(0, desired[73])

    def test_launcher_alone_grants_five(self) -> None:
        desired = compute_desired_capacities(_received("Missile Launcher"), 0)
        self.assertEqual(1, desired[73])
        self.assertEqual(5, desired[44])

    def test_expansions_add_five_each_only_with_launcher(self) -> None:
        desired = compute_desired_capacities(
            _received("Missile Launcher", "Missile Expansion", "Missile Expansion"), 0
        )
        self.assertEqual(5 * (1 + 0 + 2), desired[44])

        # Expansions received before the launcher still count once it arrives
        # (PLAN.md Risk L8: gating lives in the client, not the ISO).
        desired_reordered = compute_desired_capacities(
            _received("Missile Expansion", "Missile Expansion", "Missile Launcher"), 0
        )
        self.assertEqual(desired[44], desired_reordered[44])

    def test_seeker_launcher_adds_five_only_with_missile_launcher(self) -> None:
        # Seeker Launcher alone (no Missile Launcher): still 0 missile capacity.
        desired_no_launcher = compute_desired_capacities(_received("Seeker Launcher"), 0)
        self.assertEqual(0, desired_no_launcher[44])

        desired_with_launcher = compute_desired_capacities(
            _received("Missile Launcher", "Seeker Launcher"), 0
        )
        self.assertEqual(5 * (1 + 1 + 0), desired_with_launcher[44])

    def test_unlock_option_expansions_alone_unlock_launcher(self) -> None:
        # With missile_expansions_unlock_launcher on, expansions alone (no
        # Missile Launcher) unlock the launcher flag and grant 5 capacity
        # per expansion.
        for n in (1, 2, 3):
            with self.subTest(n=n):
                desired = compute_desired_capacities(
                    _received(*(["Missile Expansion"] * n)), 0, True
                )
                self.assertEqual(1, desired[73])
                self.assertEqual(5 * n, desired[44])

    def test_unlock_option_launcher_plus_expansions_unchanged(self) -> None:
        # Launcher + expansions already unlocked without the option; the
        # option must not change that result.
        received = _received("Missile Launcher", "Missile Expansion", "Missile Expansion")
        desired_off = compute_desired_capacities(received, 0, False)
        desired_on = compute_desired_capacities(received, 0, True)
        self.assertEqual(desired_off, desired_on)

    def test_unlock_option_seeker_launcher_alone_still_grants_nothing(self) -> None:
        # Seeker Launcher alone is neither a Missile Launcher nor a Missile
        # Expansion, so the option must not unlock anything for it.
        desired = compute_desired_capacities(_received("Seeker Launcher"), 0, True)
        self.assertEqual(0, desired[73])
        self.assertEqual(0, desired[44])


class TestPowerBombGating(unittest.TestCase):
    def test_no_main_no_power_bombs(self) -> None:
        desired = compute_desired_capacities(_received("Power Bomb Expansion"), 0)
        self.assertEqual(0, desired[43])

    def test_main_grants_two_plus_expansions(self) -> None:
        desired = compute_desired_capacities(
            _received("Power Bomb", "Power Bomb Expansion", "Power Bomb Expansion", "Power Bomb Expansion"), 0
        )
        self.assertEqual(2 + 3, desired[43])

        # Expansions received before the main pickup still count once it
        # arrives, same as missiles (and the historical /grant_item bug).
        desired_reordered = compute_desired_capacities(
            _received("Power Bomb Expansion", "Power Bomb Expansion", "Power Bomb Expansion", "Power Bomb"), 0
        )
        self.assertEqual(desired[43], desired_reordered[43])

    def test_unlock_option_expansions_alone_unlock_power_bombs(self) -> None:
        # With power_bomb_expansions_unlock_power_bombs on, expansions alone
        # (no Power Bomb main pickup) unlock Power Bombs and grant 1
        # capacity per expansion (no +2, since the main pickup is what
        # carries that).
        for n in (1, 2, 3):
            with self.subTest(n=n):
                desired = compute_desired_capacities(
                    _received(*(["Power Bomb Expansion"] * n)), 0, False, True
                )
                self.assertEqual(n, desired[43])

    def test_unlock_option_main_plus_expansions_unchanged(self) -> None:
        # Main + expansions already unlocked without the option; the option
        # must not change that result.
        received = _received(
            "Power Bomb", "Power Bomb Expansion", "Power Bomb Expansion"
        )
        desired_off = compute_desired_capacities(received, 0, False, False)
        desired_on = compute_desired_capacities(received, 0, False, True)
        self.assertEqual(desired_off, desired_on)

    def test_missile_and_power_bomb_options_do_not_leak_into_each_other(self) -> None:
        # missile_expansions_unlock_launcher must not affect Power Bomb
        # gating, and power_bomb_expansions_unlock_power_bombs must not
        # affect Missile gating.
        received = _received("Missile Expansion", "Missile Expansion", "Power Bomb Expansion")

        desired_missile_flag_only = compute_desired_capacities(received, 0, True, False)
        self.assertEqual(0, desired_missile_flag_only[43])

        desired_power_bomb_flag_only = compute_desired_capacities(received, 0, False, True)
        self.assertEqual(0, desired_power_bomb_flag_only[44])
        self.assertEqual(0, desired_power_bomb_flag_only[73])


class TestBeamAmmo(unittest.TestCase):
    def test_dark_and_light_ammo_formula(self) -> None:
        desired = compute_desired_capacities(
            _received(
                "Dark Beam",
                "Dark Ammo Expansion",
                "Dark Ammo Expansion",
                "Light Beam",
                "Light Ammo Expansion",
                "Beam Ammo Expansion",
            ),
            0,
        )
        self.assertEqual(50 * 1 + 20 * 2 + 10 * 1, desired[45])
        self.assertEqual(50 * 1 + 20 * 1 + 10 * 1, desired[46])

    def test_no_beam_no_ammo(self) -> None:
        desired = compute_desired_capacities(_received("Dark Ammo Expansion"), 0)
        self.assertEqual(20, desired[45])


class TestVariaSuitClamp(unittest.TestCase):
    def test_varia_capacity_always_exactly_one(self) -> None:
        # Even with nothing received (Varia is a starting item skipped by
        # first_non_starting_item_index in real play), the client must
        # never let OPR's Defense Up counter (item 12) exceed capacity 1.
        desired_empty = compute_desired_capacities([], 0)
        self.assertEqual(1, desired_empty[12])

        desired_received = compute_desired_capacities(_received("Varia Suit"), 0)
        self.assertEqual(1, desired_received[12])


class TestEnergyTankCap(unittest.TestCase):
    def test_tank_count_under_cap(self) -> None:
        desired = compute_desired_capacities(_received(*(["Energy Tank"] * 5)), 0)
        self.assertEqual(5, desired[42])

    def test_tank_count_clamped_to_fourteen(self) -> None:
        desired = compute_desired_capacities(_received(*(["Energy Tank"] * 20)), 0)
        self.assertEqual(14, desired[42])


class TestProgressiveStages(unittest.TestCase):
    def test_progressive_suit_stages(self) -> None:
        desired_one = compute_desired_capacities(_received("Progressive Suit"), 0)
        self.assertEqual(1, desired_one.get(13, 0))
        self.assertEqual(0, desired_one.get(14, 0))

        desired_two = compute_desired_capacities(_received("Progressive Suit", "Progressive Suit"), 0)
        self.assertEqual(1, desired_two[13])
        self.assertEqual(1, desired_two[14])

    def test_progressive_grapple_stages(self) -> None:
        desired_two = compute_desired_capacities(
            _received("Progressive Grapple", "Progressive Grapple"), 0
        )
        self.assertEqual(1, desired_two[23])
        self.assertEqual(1, desired_two[27])

    def test_extra_progressive_copy_clamps_to_final_stage(self) -> None:
        # A third Progressive Suit copy (shouldn't happen in a normal pool,
        # but the client recomputes idempotently every tick) must not raise
        # or roll over -- it just stays on the final stage.
        desired = compute_desired_capacities(_received(*(["Progressive Suit"] * 3)), 0)
        self.assertEqual(1, desired[13])
        self.assertEqual(1, desired[14])


class TestStartingItemsStillCount(unittest.TestCase):
    def test_threshold_does_not_hide_starting_items(self) -> None:
        # A precollected Missile Launcher (index 0, below the threshold) is
        # already in the ISO, but it must still count so later expansions
        # unlock missiles; plan_grants makes the launcher itself a no-op.
        received = _received("Missile Launcher", "Missile Expansion")
        desired = compute_desired_capacities(received, 1)
        self.assertEqual(1, desired[73])
        self.assertEqual(10, desired[44])
        current = {12: (1, 1), 73: (1, 1), 44: (5, 5)}
        self.assertEqual([(44, 5)], plan_grants(desired, current))


class TestGenericBooleanItems(unittest.TestCase):
    def test_boolean_item_capacity_is_one(self) -> None:
        desired = compute_desired_capacities(_received("Grapple Beam"), 0)
        self.assertEqual(1, desired[23])

    def test_key_and_translator_items(self) -> None:
        desired = compute_desired_capacities(
            _received("Sky Temple Key 1", "Violet Translator", "Dark Agon Key 1"), 0
        )
        self.assertEqual(1, desired[29])
        self.assertEqual(1, desired[97])
        self.assertEqual(1, desired[32])


class TestPlanGrants(unittest.TestCase):
    def test_positive_deltas_only(self) -> None:
        desired = {12: 1, 44: 10, 45: 50}
        current = {12: (0, 1), 44: (0, 5), 45: (0, 50)}
        grants = plan_grants(desired, current)
        self.assertEqual([(44, 5)], grants)

    def test_missing_current_entry_treated_as_zero(self) -> None:
        desired = {97: 1}
        grants = plan_grants(desired, {})
        self.assertEqual([(97, 1)], grants)

    def test_negative_delta_is_skipped_not_granted(self) -> None:
        desired = {42: 5}
        current = {42: (5, 14)}
        grants = plan_grants(desired, current)
        self.assertEqual([], grants)

    def test_deltas_sorted_by_item_id(self) -> None:
        desired = {97: 1, 12: 1, 44: 5}
        current: dict[int, tuple[int, int]] = {}
        grants = plan_grants(desired, current)
        self.assertEqual([12, 44, 97], [item_id for item_id, _delta in grants])


class TestPlanGrantsLoggingSuppression(unittest.TestCase):
    """``plan_grants`` is called every ~0.5s tick; before this fix, a
    negative delta (capacity already above what's desired -- see the
    manual-grant bug above, or a stale save) logged a warning on every one
    of those calls, forever. It must now log only the first occurrence of a
    given (item_id, current_capacity, desired_capacity) triple, and this
    suppression must not change ``plan_grants``'s return value."""

    def setUp(self) -> None:
        receive_items._last_negative_delta_warning.clear()

    def test_negative_delta_logged_once_across_repeated_calls(self) -> None:
        desired = {42: 5}
        current = {42: (5, 14)}
        with self.assertLogs(receive_items.logger.name, level="WARNING") as cm:
            for _ in range(3):
                grants = plan_grants(desired, current)
                self.assertEqual([], grants)
        self.assertEqual(1, len(cm.records))

    def test_negative_delta_logged_again_when_it_changes(self) -> None:
        with self.assertLogs(receive_items.logger.name, level="WARNING") as cm:
            plan_grants({42: 5}, {42: (5, 14)})
            plan_grants({42: 5}, {42: (5, 14)})
            plan_grants({42: 5}, {42: (5, 13)})
        self.assertEqual(2, len(cm.records))


if __name__ == "__main__":
    unittest.main()
