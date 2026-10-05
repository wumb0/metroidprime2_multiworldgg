"""Tests for the pre-scanned elevator timer
(``client/elevator_prescan_patch.py``).

The regression guarded here: open-prime-rando's own helper created the
auto-enable timer with ``active=False``, so it never ran and elevators still
needed their pillar scanned. Whether the room then behaves as scanned can
only be checked in game -- see the module docstring.
"""

from __future__ import annotations

import importlib.util
import unittest
from typing import Any, cast

from ..client import elevator_prescan_patch

_OPR_AVAILABLE = importlib.util.find_spec("open_prime_rando") is not None
_RDS_AVAILABLE = importlib.util.find_spec("retro_data_structures") is not None


class _FakeTimerInstance:
    def __init__(self, properties: Any) -> None:
        self.properties = properties
        self.connections: list[tuple[Any, Any, Any]] = []

    def add_connection(self, state: Any, message: Any, target: Any) -> None:
        self.connections.append((state, message, target))


class _FakeLayer:
    def __init__(self) -> None:
        self.instances: list[_FakeTimerInstance] = []

    def add_instance_with(self, properties: Any) -> _FakeTimerInstance:
        instance = _FakeTimerInstance(properties)
        self.instances.append(instance)
        return instance


class _FakeArea:
    def __init__(self) -> None:
        self.layer = _FakeLayer()
        self.relay = object()
        self.requested_layers: list[str] = []
        self.requested_instances: list[int] = []

    def get_layer(self, name: str) -> _FakeLayer:
        self.requested_layers.append(name)
        return self.layer

    def get_instance(self, instance_id: int) -> object:
        self.requested_instances.append(instance_id)
        return self.relay


@unittest.skipUnless(_RDS_AVAILABLE, "retro_data_structures is not installed")
class TestPatchElevator(unittest.TestCase):
    def setUp(self) -> None:
        self.area = _FakeArea()
        elevator_prescan_patch.patch_elevator(None, None, cast(Any, self.area), 0x180040)  # type: ignore[arg-type]
        (self.timer,) = self.area.layer.instances

    def test_timer_is_active(self) -> None:
        # The upstream bug: an inactive timer is never thought.
        self.assertTrue(self.timer.properties.editor_properties.active)

    def test_timer_starts_itself_quickly_and_runs_once(self) -> None:
        self.assertTrue(self.timer.properties.auto_start)
        self.assertFalse(self.timer.properties.auto_reset)
        self.assertLess(self.timer.properties.time, 0.02)  # before "Setup Departure Elevator"

    def test_timer_activates_the_memory_relay(self) -> None:
        from retro_data_structures.enums.echoes import Message, State

        self.assertEqual(self.area.requested_instances, [0x180040])
        self.assertEqual(self.timer.connections, [(State.Zero, Message.Activate, self.area.relay)])

    def test_added_to_the_default_layer(self) -> None:
        self.assertEqual(self.area.requested_layers, ["Default"])


@unittest.skipUnless(_OPR_AVAILABLE, "open-prime-rando is not installed")
class TestInstalled(unittest.TestCase):
    def test_swaps_and_restores_patch_elevator(self) -> None:
        from open_prime_rando.echoes.elevators import auto_enabled_elevator_patches as upstream

        original = upstream.patch_elevator
        with elevator_prescan_patch.installed():
            self.assertIs(upstream.patch_elevator, elevator_prescan_patch.patch_elevator)
        self.assertIs(upstream.patch_elevator, original)

    def test_restores_even_on_exception(self) -> None:
        from open_prime_rando.echoes.elevators import auto_enabled_elevator_patches as upstream

        original = upstream.patch_elevator
        with self.assertRaises(RuntimeError):
            with elevator_prescan_patch.installed():
                raise RuntimeError("boom")
        self.assertIs(upstream.patch_elevator, original)

    def test_register_covers_upstream_rooms_plus_the_missing_temple_grounds_ones(self) -> None:
        from open_prime_rando.echoes.elevators import auto_enabled_elevator_patches as upstream

        registered: list[tuple[int, int, Any]] = []

        class _Patcher:
            def add_raw_function(self, mlvl_id: int, mrea_id: int, func: Any) -> None:
                registered.append((mlvl_id, mrea_id, func))

        with elevator_prescan_patch.installed():
            upstream.register(cast(Any, _Patcher()))
        self.assertEqual(len(registered), 18)
        self.assertEqual(len({(m, r) for m, r, _ in registered}), 18)
        self.assertTrue(all(f.func is elevator_prescan_patch.patch_elevator for _, _, f in registered))

    def test_extras_are_not_already_in_upstreams_table(self) -> None:
        from open_prime_rando.echoes.elevators import auto_enabled_elevator_patches as upstream

        upstream_rooms = {(m, r) for m, areas in upstream.ELEVATOR_MEMORY_RELAY_PER_MREA.items() for r in areas}
        self.assertFalse(upstream_rooms & set(elevator_prescan_patch.EXTRA_MEMORY_RELAY_PER_MREA))

    def test_restores_register(self) -> None:
        from open_prime_rando.echoes.elevators import auto_enabled_elevator_patches as upstream

        original = upstream.register
        with elevator_prescan_patch.installed():
            self.assertIsNot(upstream.register, original)
        self.assertIs(upstream.register, original)
