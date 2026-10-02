"""Tests for the client's item-collection strip (``client/item_panel.py``):
the pure ``compute_panel_state`` and the icon assets it needs."""

from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path

from .. import constants
from ..client.item_panel import COUNTER_NAMES, COUNTERS, UPGRADES, compute_panel_state, tooltip_position
from ..items import ITEM_TABLE

ASSETS = Path(__file__).resolve().parents[1] / "assets" / "items"
STARTING = list(constants.DEFAULT_STARTING_ITEMS)


class TestAssets(unittest.TestCase):
    def test_every_icon_exists(self) -> None:
        for stem in [s for s, _ in UPGRADES] + [s for s, _ in COUNTERS]:
            self.assertTrue((ASSETS / f"{stem}.png").is_file(), f"missing icon {stem}.png")

    def test_upgrade_items_are_real_items(self) -> None:
        for _, item in UPGRADES:
            self.assertIn(item, ITEM_TABLE)

    def test_every_counter_icon_has_a_name(self) -> None:
        self.assertEqual({s for s, _ in COUNTERS}, set(COUNTER_NAMES))

    def test_icon_and_counter_keys_unique(self) -> None:
        self.assertEqual(len(UPGRADES), len({s for s, _ in UPGRADES}))
        self.assertEqual(len(COUNTERS), len({k for _, k in COUNTERS}))


class TestComputePanelState(unittest.TestCase):
    def test_empty_everything_dim(self) -> None:
        state = compute_panel_state([], {})
        self.assertFalse(any(state.owned.values()))
        self.assertEqual("0", state.counters["missiles"])
        self.assertEqual("0/14", state.counters["energy_tanks"])
        self.assertEqual("0/3", state.counters["ing_hive_keys"])

    def test_starting_items_lit(self) -> None:
        state = compute_panel_state(STARTING, {})
        for icon in ("powerbeam", "chargebeam", "combatvisor", "scanvisor", "variasuit", "morphball"):
            self.assertTrue(state.owned[icon], icon)
        self.assertFalse(state.owned["darkbeam"])

    def test_progressive_suit_stages(self) -> None:
        one = compute_panel_state(["Progressive Suit"], {})
        self.assertTrue(one.owned["darksuit"])
        self.assertFalse(one.owned["lightsuit"])
        two = compute_panel_state(["Progressive Suit", "Progressive Suit"], {})
        self.assertTrue(two.owned["darksuit"])
        self.assertTrue(two.owned["lightsuit"])

    def test_progressive_grapple_stages(self) -> None:
        one = compute_panel_state(["Progressive Grapple"], {})
        self.assertTrue(one.owned["grapplebeam"])
        self.assertFalse(one.owned["screwattack"])
        two = compute_panel_state(["Progressive Grapple"] * 2, {})
        self.assertTrue(two.owned["screwattack"])

    def test_missile_expansion_counter_and_launcher_gating(self) -> None:
        totals = {"expansion_totals": {"Missile Expansion": 33}}
        with_launcher = compute_panel_state(["Missile Launcher", "Missile Expansion", "Missile Expansion"], totals)
        self.assertEqual("2/33", with_launcher.counters["missiles"])
        self.assertTrue(with_launcher.owned["missilelauncher"])

        no_launcher = compute_panel_state(["Missile Expansion"], totals)
        self.assertEqual("1/33", no_launcher.counters["missiles"])
        self.assertFalse(no_launcher.owned["missilelauncher"])

        unlocked = compute_panel_state(["Missile Expansion"], {**totals, "missile_expansions_unlock_launcher": True})
        self.assertTrue(unlocked.owned["missilelauncher"])

    def test_power_bomb_gating(self) -> None:
        self.assertFalse(compute_panel_state(["Power Bomb Expansion"], {}).owned["powerbomb"])
        unlocked = compute_panel_state(["Power Bomb Expansion"], {"power_bomb_expansions_unlock_power_bombs": True})
        self.assertTrue(unlocked.owned["powerbomb"])
        totals = {"expansion_totals": {"Power Bomb Expansion": 8}}
        self.assertEqual("1/8", compute_panel_state(["Power Bomb", "Power Bomb Expansion"], totals).counters["power_bombs"])

    def test_counters_without_totals_show_bare_count(self) -> None:
        state = compute_panel_state(["Missile Expansion"] * 3, {})
        self.assertEqual("3", state.counters["missiles"])

    def test_beam_ammo_expansions(self) -> None:
        split = {"expansion_totals": {"Dark Ammo Expansion": 10, "Light Ammo Expansion": 10}}
        state = compute_panel_state(["Dark Beam", "Dark Ammo Expansion", "Dark Ammo Expansion"], split)
        self.assertEqual("2/10", state.counters["dark_ammo"])
        self.assertEqual("0/10", state.counters["light_ammo"])

        unified = {"expansion_totals": {"Beam Ammo Expansion": 20}}
        state = compute_panel_state(["Beam Ammo Expansion"] * 3, unified)
        self.assertEqual("3/20", state.counters["dark_ammo"])
        self.assertEqual("3/20", state.counters["light_ammo"])

    def test_unlimited_ammo(self) -> None:
        state = compute_panel_state(["Missile Launcher", "Unlimited Missiles", "Unlimited Beam Ammo"], {})
        self.assertEqual("∞", state.counters["missiles"])
        self.assertEqual("∞", state.counters["dark_ammo"])
        self.assertEqual("∞", state.counters["light_ammo"])

    def test_keys(self) -> None:
        names = ["Sky Temple Key 1", "Sky Temple Key 4", "Dark Agon Key 2", "Ing Hive Key 1", "Ing Hive Key 3"]
        state = compute_panel_state(names, {"sky_temple_keys_required": 9})
        self.assertEqual("2/9", state.counters["sky_temple_keys"])
        self.assertEqual("1/3", state.counters["dark_agon_keys"])
        self.assertEqual("0/3", state.counters["dark_torvus_keys"])
        self.assertEqual("2/3", state.counters["ing_hive_keys"])

    def test_counters_never_exceed_their_max_when_everything_is_resent(self) -> None:
        # The server's collect on goal completion can deliver every item again.
        keys = [f"Sky Temple Key {n}" for n in range(1, 10)]
        temple_keys = [f"{area} Key {n}" for area in ("Dark Agon", "Dark Torvus", "Ing Hive") for n in range(1, 4)]
        ammo = ["Dark Beam", "Light Beam"] + ["Dark Ammo Expansion", "Light Ammo Expansion"] * 10
        names = (keys + temple_keys + ammo) * 2
        totals = {"Dark Ammo Expansion": 10, "Light Ammo Expansion": 10}
        for slot_data in ({"expansion_totals": totals}, {"sky_temple_keys_required": 9, "expansion_totals": totals}):
            state = compute_panel_state(names, slot_data)
            self.assertEqual("9/9" if "sky_temple_keys_required" in slot_data else "9", state.counters["sky_temple_keys"])
            for counter in ("dark_agon_keys", "dark_torvus_keys", "ing_hive_keys"):
                self.assertEqual("3/3", state.counters[counter])
            self.assertEqual("10/10", state.counters["dark_ammo"])
            self.assertEqual("10/10", state.counters["light_ammo"])

    def test_sky_temple_keys_clamped_to_required(self) -> None:
        keys = [f"Sky Temple Key {n}" for n in range(1, 10)]
        state = compute_panel_state(keys, {"sky_temple_keys_required": 3})
        self.assertEqual("3/3", state.counters["sky_temple_keys"])

    def test_energy_tanks_capped(self) -> None:
        self.assertEqual("14/14", compute_panel_state(["Energy Tank"] * 20, {}).counters["energy_tanks"])
        state = compute_panel_state(["Energy Tank"] * 3, {"expansion_totals": {"Energy Tank": 14}})
        self.assertEqual("3/14", state.counters["energy_tanks"])


@unittest.skipUnless(importlib.util.find_spec("kivymd") is not None, "kivymd not installed")
class TestTooltipPosition(unittest.TestCase):
    WINDOW = (1000.0, 800.0)

    def _position(self, mouse: tuple[float, float]) -> tuple[float, float]:
        return tooltip_position(mouse, (100.0, 40.0), self.WINDOW, gap=8.0, margin=10.0)

    def test_centered_right_above_the_mouse(self) -> None:
        self.assertEqual((450.0, 308.0), self._position((500.0, 300.0)))

    def test_clamped_to_the_left_and_right_edges(self) -> None:
        self.assertEqual(10.0, self._position((5.0, 300.0))[0])
        self.assertEqual(1000.0 - 100.0 - 10.0, self._position((995.0, 300.0))[0])

    def test_flips_below_the_mouse_when_there_is_no_room_above(self) -> None:
        # 790 + 8 + 40 would overflow the 800-high window (10 margin).
        self.assertEqual(790.0 - 8.0 - 40.0, self._position((500.0, 790.0))[1])

    def test_never_below_the_bottom_margin(self) -> None:
        self.assertEqual(10.0, self._position((500.0, 0.0))[1])


class TestKivyPanel(unittest.TestCase):
    def test_builds_and_updates_headless(self) -> None:
        # kivy's "mock" GL backend lets widgets and textures build without a
        # display. kvui must be imported before anything else imports kivy,
        # and kivymd widgets need a running MDApp for theming.
        import os

        os.environ.setdefault("KIVY_NO_ARGS", "1")
        os.environ.setdefault("KIVY_GL_BACKEND", "mock")
        try:
            import kvui  # noqa: F401
            from kivy.app import App
            from kivymd.app import MDApp
        except ImportError as exc:  # pragma: no cover
            self.skipTest(str(exc))

        from ..client.item_panel import ItemPanel

        previous = App._running_app
        App._running_app = MDApp()
        try:
            panel = ItemPanel()
            panel.update(compute_panel_state([*STARTING, "Dark Beam", "Energy Tank"], {}))
            self.assertEqual(1, panel.upgrade_icons["darkbeam"].opacity)
            self.assertEqual(0.2, panel.upgrade_icons["lightbeam"].opacity)
            self.assertEqual("1/14", panel.counter_labels["energy_tanks"].text)
            # Hovering an icon shows its name; leaving dismisses it.
            icon = panel.upgrade_icons["darkbeam"]
            self.assertEqual("Dark Beam", icon._tooltip.text)
            # kvui's <ToolTip> style centers it in the window via pos_hint
            # (overriding any pos we set); it must have been cleared.
            self.assertEqual({}, icon._tooltip.pos_hint)
            icon.on_enter()
            icon.on_leave()
        finally:
            App._running_app = previous
