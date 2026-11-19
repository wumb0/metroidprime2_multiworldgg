"""Tests for the pre-scanned Phazon Site (``pre_scan_phazon_site``).

Two halves: the SCLY edit (``client/phazon_site_patch.py``), checked against
fake room instances the way ``test_elevator_prescan_patch.py`` does -- the
relay ids/names are load-bearing, and whether the room really comes up solved
can only be seen in game; and the logic half: the option pre-grants the
Phazon Site Barrier event, so its location and item leave the world and the
Watering Hole door stops waiting on it.
"""

from __future__ import annotations

import importlib.util
import unittest
from typing import Any, cast

from .. import constants
from ..client import phazon_site_patch
from .bases import MP2TestBase

_OPR_AVAILABLE = importlib.util.find_spec("open_prime_rando") is not None
_RDS_AVAILABLE = importlib.util.find_spec("retro_data_structures") is not None


class _FakeConnection:
    def __init__(self, state: Any, target: int, message: Any) -> None:
        self.state = state
        self.target = target
        self.message = message


class _FakeInstance:
    def __init__(self, name: str, connections: list[_FakeConnection]) -> None:
        self.name = name
        self.connections = connections


class _FakeTimer:
    def __init__(self, properties: Any) -> None:
        self.properties = properties
        self.sent: list[tuple[Any, Any, Any]] = []

    def add_connection(self, state: Any, message: Any, target: Any) -> None:
        self.sent.append((state, message, target))


class _FakeLayer:
    def __init__(self) -> None:
        self.instances: list[_FakeTimer] = []

    def add_instance_with(self, properties: Any) -> _FakeTimer:
        timer = _FakeTimer(properties)
        self.instances.append(timer)
        return timer


def _fake_area(*, active_connections: int = 2, wrong_name: bool = False) -> _Proxy:
    from retro_data_structures.enums.echoes import Message, State

    instances = {}
    for instance_id, name in phazon_site_patch.SOLVED_RELAYS:
        connections = [
            _FakeConnection(State.Active, instance_id + 1, Message.Activate) for _ in range(active_connections)
        ] + [_FakeConnection(State.Inactive, instance_id + 2, Message.Deactivate)]
        instances[instance_id] = _FakeInstance("Wrong Relay" if wrong_name else name, connections)
    return _Proxy(instances, _FakeLayer(), [])


class _Proxy:
    """Duck-typed ``Area``: instance lookup by id (unknown ids get a plain
    stand-in, they're connection targets) and the Default layer."""

    def __init__(self, instances: dict[int, _FakeInstance], layer: _FakeLayer, requested: list[int]) -> None:
        self._instances = instances
        self.layer = layer
        self.requested = requested
        self.name = "Phazon Site"

    def get_instance(self, instance_id: int) -> _FakeInstance:
        self.requested.append(instance_id)
        return self._instances.setdefault(instance_id, _FakeInstance("Connection Target", []))

    def get_layer(self, name: str) -> _FakeLayer:
        assert name == "Default"
        return self.layer


@unittest.skipUnless(_RDS_AVAILABLE, "retro_data_structures is not installed")
class TestMakeRoomPreSolved(unittest.TestCase):
    def _run(self, **kwargs: Any) -> tuple[_Proxy, _FakeTimer]:
        area = _fake_area(**kwargs)
        phazon_site_patch.make_room_pre_solved(None, None, cast(Any, area))
        (timer,) = area.layer.instances
        return area, timer

    def test_touches_exactly_the_solved_state_relays(self) -> None:
        area, _ = self._run(active_connections=1)
        relay_ids = [i for i, _ in phazon_site_patch.SOLVED_RELAYS]
        # The relays are looked up first, then each Active connection's target.
        self.assertEqual(area.requested, relay_ids + [i + 1 for i in relay_ids])

    def test_rejects_a_room_whose_relay_ids_moved(self) -> None:
        with self.assertRaises(AssertionError):
            self._run(wrong_name=True)

    def test_timer_is_auto_started_immediately(self) -> None:
        _, timer = self._run()
        self.assertTrue(timer.properties.auto_start)
        self.assertLess(timer.properties.time, 0.02)

    def test_copies_only_active_connections_in_relay_order(self) -> None:
        from retro_data_structures.enums.echoes import Message, State

        area, timer = self._run(active_connections=2)
        expected: list[tuple[Any, Any, Any]] = [
            (State.Zero, Message.Activate, area.get_instance(instance_id + 1))
            for instance_id, _ in phazon_site_patch.SOLVED_RELAYS
            for _ in range(2)
        ]
        self.assertEqual(expected, timer.sent)

    def test_refuses_a_room_with_nothing_to_replay(self) -> None:
        with self.assertRaises(AssertionError):
            self._run(active_connections=0)


@unittest.skipUnless(_OPR_AVAILABLE, "open-prime-rando is not installed")
class TestInstalled(unittest.TestCase):
    def test_swaps_and_restores_register_world_changes(self) -> None:
        from open_prime_rando.echoes import patcher as opr_patcher

        original = opr_patcher.register_world_changes
        with phazon_site_patch.installed():
            self.assertIsNot(opr_patcher.register_world_changes, original)
            registered: list[tuple[int, int, Any]] = []

            class _Patcher:
                def add_raw_function(self, mlvl_id: int, mrea_id: int, func: Any) -> None:
                    registered.append((mlvl_id, mrea_id, func))

            opr_patcher.register_world_changes(cast(Any, _Patcher()), [])
            phazon_site = (
                phazon_site_patch.PHAZON_SITE_MLVL,
                phazon_site_patch.PHAZON_SITE_MREA,
                phazon_site_patch.make_room_pre_solved,
            )
            self.assertIn(phazon_site, registered)
        self.assertIs(opr_patcher.register_world_changes, original)

    def test_restores_even_on_exception(self) -> None:
        from open_prime_rando.echoes import patcher as opr_patcher

        original = opr_patcher.register_world_changes
        with self.assertRaises(RuntimeError), phazon_site_patch.installed():
            raise RuntimeError("boom")
        self.assertIs(opr_patcher.register_world_changes, original)


def _phazon_barrier_locations(test: MP2TestBase) -> list[str]:
    return sorted(loc.name for loc in test.multiworld.get_locations(test.player) if "Phazon Site Barrier" in loc.name)


class TestPreScanPhazonSiteOff(MP2TestBase):
    def test_the_barrier_event_is_a_location(self) -> None:
        (name,) = _phazon_barrier_locations(self)
        self.assertEqual(name, "Dark Agon Wastes/Phazon Site/Event - Phazon Site Barrier")


class TestPreScanPhazonSiteOn(MP2TestBase):
    options = {"pre_scan_phazon_site": True}

    def test_the_barrier_event_leaves_the_world(self) -> None:
        self.assertEqual([], _phazon_barrier_locations(self))

    def test_other_events_are_untouched(self) -> None:
        events = [loc.name for loc in self.multiworld.get_locations(self.player) if "/Event - " in loc.name]
        self.assertGreater(len(events), 10)

    def test_logic_pregrants_exactly_the_barrier_event(self) -> None:
        from ..logic.requirements import extra_pregranted_events

        self.assertEqual(extra_pregranted_events(self.world), frozenset({constants.PHAZON_SITE_BARRIER_EVENT}))


class TestPreScanPhazonSiteOffPregrantsNothing(MP2TestBase):
    def test_nothing_extra_is_pregranted(self) -> None:
        from ..logic.requirements import extra_pregranted_events

        self.assertEqual(extra_pregranted_events(self.world), frozenset())
