"""Tests for the boss-skip goal warps (``client/goal_warp_patch.py``): the
connection rewiring against fake rooms shaped like the real ones, which
registrations each ``goal`` gets, and the option's route into the
``.apmp2``'s options.json.

The in-game half (does the teleporter actually deliver the player to the
Credits) can only be checked against a real ISO -- see MT17. The room shapes
the fakes mimic were read from a retail NTSC-U and a PAL ISO.
"""

from __future__ import annotations

import importlib.util
import json
import pathlib
import tempfile
import unittest
import zipfile
from dataclasses import dataclass
from typing import Any, cast

from .. import constants
from ..client import goal_warp_patch
from .bases import MP2TestBase

_OPR_AVAILABLE = importlib.util.find_spec("open_prime_rando") is not None
_RDS_AVAILABLE = importlib.util.find_spec("retro_data_structures") is not None


@dataclass
class _FakeConnection:
    state: object
    message: object
    target: int


class _FakeInstance:
    """Enough of retro_data_structures' ScriptInstance: an id, a name, a
    type, properties and a mutable connection list with the real
    ``add_connection``/``remove_connection`` contract."""

    def __init__(self, instance_id: int, name: str, type_name: str = "SRLY", properties: object = None) -> None:
        self.id = instance_id
        self.name = name
        self.type_name = type_name
        self.properties = properties
        self.connections: list[_FakeConnection] = []

    def connect(self, state: object, message: object, target: _FakeInstance) -> _FakeInstance:
        self.connections.append(_FakeConnection(state, message, target.id))
        return self

    def remove_connection(self, connection: _FakeConnection) -> None:
        self.connections = [c for c in self.connections if c is not connection]

    def add_connection(self, state: object, message: object, target: Any) -> None:
        self.connections.append(_FakeConnection(state, message, target if isinstance(target, int) else target.id))


class _FakeLayer:
    def __init__(self, name: str, area: _FakeArea) -> None:
        self.name = name
        self._area = area
        self.instances: list[_FakeInstance] = []

    def add(self, name: str, type_name: str = "SRLY") -> _FakeInstance:
        instance = _FakeInstance(self._area.allocate_id(), name, type_name)
        self.instances.append(instance)
        return instance

    def get_instance(self, name: str) -> _FakeInstance:
        (instance,) = (i for i in self.instances if i.name == name)
        return instance

    def add_instance_with(self, properties: Any) -> _FakeInstance:
        instance = _FakeInstance(
            self._area.allocate_id(),
            properties.editor_properties.name,
            type(properties).__name__,
            properties,
        )
        self.instances.append(instance)
        return instance


class _FakeArea:
    name = "Fake Area"

    def __init__(self, *layer_names: str) -> None:
        self._next_id = 1
        self.layers = [_FakeLayer(name, self) for name in layer_names]

    def allocate_id(self) -> int:
        self._next_id += 1
        return self._next_id

    def get_layer(self, name: str) -> _FakeLayer:
        (layer,) = (layer for layer in self.layers if layer.name == name)
        return layer

    def all_instances(self) -> list[_FakeInstance]:
        return [i for layer in self.layers for i in layer.instances]

    def get_instance(self, ref: int) -> _FakeInstance:
        (instance,) = (i for i in self.all_instances() if i.id == ref)
        return instance

    def get_all_connections_to(self, target: int) -> list[tuple[_FakeInstance, _FakeConnection]]:
        return [(i, c) for i in self.all_instances() for c in i.connections if c.target == target]


def _energy_controller() -> tuple[_FakeArea, _FakeInstance]:
    """The arrival spawn point wired to both cinematic starts and the layer
    reset, as in the retail room."""
    from retro_data_structures.enums.echoes import Message, State

    area = _FakeArea("Default", "Teleport Arrival", "Other Arrivals")
    default, arrival, other_arrivals = area.layers
    layer_reset = default.add("Setup 08_Temple Layers after Arrival")
    finish_cinema = other_arrivals.add("Finish Cinema Start")
    final_boss_intro = area.get_layer("Default").add("Final Boss Intro", "SQTR")
    spawn = arrival.add("Inital Spawn Point 001", "SPWN")
    spawn.connect(State.Zero, Message.SetToZero, finish_cinema)
    spawn.connect(State.Zero, Message.SetToZero, layer_reset)
    spawn.connect(State.Zero, Message.Start, final_boss_intro)
    return area, spawn


def _gateway() -> tuple[_FakeArea, _FakeInstance, _FakeInstance]:
    """The Dark Samus intro layer's ``OcclusionRelay`` wired to the intro's
    "Cinema Start" and to an unrelated object, as in the retail room."""
    from retro_data_structures.enums.echoes import Message, State

    area = _FakeArea("Default", "Dark Samus Battle3 Intro", "Game Ending Part1")
    default, intro, ending = area.layers
    cinema_start = intro.add("Cinema Start")
    ending_cinema_start = ending.add("Cinema Start")  # same name, other layer
    unrelated = default.add("Load/Unload 0T", "TRGR")
    relay = intro.add("OcclusionRelay", "SPFN")
    relay.connect(State.InternalState01, Message.SetToZero, cinema_start)
    relay.connect(State.InternalState01, Message.Deactivate, unrelated)
    return area, relay, ending_cinema_start


def _added_timer_and_teleporter(area: _FakeArea) -> tuple[_FakeInstance, _FakeInstance]:
    (timer,) = (i for i in area.get_layer("Default").instances if i.type_name == "Timer")
    (teleporter,) = (i for i in area.get_layer("Default").instances if i.type_name == "WorldTeleporter")
    return timer, teleporter


@unittest.skipUnless(_RDS_AVAILABLE, "retro_data_structures is not installed")
class TestEnergyControllerWarp(unittest.TestCase):
    def test_cinematic_starts_are_replaced_by_the_warp_timer(self) -> None:
        from retro_data_structures.enums.echoes import Message, State

        area, spawn = _energy_controller()
        goal_warp_patch.warp_to_credits_from_energy_controller(None, None, cast(Any, area))

        timer, _teleporter = _added_timer_and_teleporter(area)
        targets = [area.get_instance(c.target).name for c in spawn.connections]
        self.assertEqual(targets, ["Setup 08_Temple Layers after Arrival", timer.name])
        self.assertEqual(spawn.connections[-1].state, State.Zero)
        self.assertEqual(spawn.connections[-1].message, Message.ResetAndStart)

    def test_timer_feeds_a_teleporter_to_the_credits(self) -> None:
        from retro_data_structures.enums.echoes import Message, State

        area, _spawn = _energy_controller()
        goal_warp_patch.warp_to_credits_from_energy_controller(None, None, cast(Any, area))

        timer, teleporter = _added_timer_and_teleporter(area)
        self.assertEqual(timer.properties.time, goal_warp_patch.WARP_DELAY_SECONDS)
        self.assertFalse(timer.properties.auto_start)
        self.assertEqual(
            timer.connections,
            [_FakeConnection(State.Zero, Message.SetToZero, teleporter.id)],
        )
        self.assertTrue(teleporter.properties.editor_properties.active)
        self.assertEqual(teleporter.properties.world, constants.TEMPLE_GROUNDS_MLVL)
        self.assertEqual(teleporter.properties.area, constants.CREDITS_MREA)

    def test_changed_room_shape_fails_loudly(self) -> None:
        area, spawn = _energy_controller()
        spawn.connections.pop(0)  # lose one of the two cinematic starts
        with self.assertRaises(AssertionError):
            goal_warp_patch.warp_to_credits_from_energy_controller(None, None, cast(Any, area))


@unittest.skipUnless(_RDS_AVAILABLE, "retro_data_structures is not installed")
class TestGatewayWarp(unittest.TestCase):
    def test_intro_trigger_is_replaced_by_the_warp_timer(self) -> None:
        from retro_data_structures.enums.echoes import Message, State

        area, relay, _ending_cinema_start = _gateway()
        goal_warp_patch.warp_to_credits_from_gateway(None, None, cast(Any, area))

        timer, _teleporter = _added_timer_and_teleporter(area)
        self.assertEqual(
            [(c.state, c.message, area.get_instance(c.target).name) for c in relay.connections],
            [
                (State.InternalState01, Message.Deactivate, "Load/Unload 0T"),
                (State.InternalState01, Message.ResetAndStart, timer.name),
            ],
        )

    def test_only_the_intro_layers_cinema_start_is_touched(self) -> None:
        area, _relay, ending_cinema_start = _gateway()
        goal_warp_patch.warp_to_credits_from_gateway(None, None, cast(Any, area))
        # The vanilla ending's own "Cinema Start" (same name, other layer)
        # must still be reachable; nothing of it is rewired.
        self.assertEqual(ending_cinema_start.connections, [])

    def test_timer_feeds_a_teleporter_to_the_credits(self) -> None:
        area, _relay, _ending_cinema_start = _gateway()
        goal_warp_patch.warp_to_credits_from_gateway(None, None, cast(Any, area))

        _timer, teleporter = _added_timer_and_teleporter(area)
        self.assertEqual(teleporter.properties.world, constants.TEMPLE_GROUNDS_MLVL)
        self.assertEqual(teleporter.properties.area, constants.CREDITS_MREA)

    def test_changed_room_shape_fails_loudly(self) -> None:
        area, relay, _ending_cinema_start = _gateway()
        relay.connections.pop(0)  # nothing triggers the intro any more
        with self.assertRaises(AssertionError):
            goal_warp_patch.warp_to_credits_from_gateway(None, None, cast(Any, area))


class _FakeAreaPatcher:
    def __init__(self) -> None:
        self.calls: list[tuple[int, int, Any]] = []

    def add_raw_function(self, mlvl_id: int, mrea_id: int, func: Any) -> None:
        self.calls.append((mlvl_id, mrea_id, func))


class TestRegister(unittest.TestCase):
    def _register(self, goal: int) -> list[tuple[int, int, Any]]:
        patcher = _FakeAreaPatcher()
        goal_warp_patch.register(cast(Any, patcher), goal)
        return patcher.calls

    def test_both_bosses_registers_nothing(self) -> None:
        self.assertEqual(self._register(constants.GOAL_BOTH_BOSSES), [])

    def test_keys_registers_the_energy_controller_only(self) -> None:
        self.assertEqual(
            self._register(constants.GOAL_KEYS),
            [
                (
                    constants.GREAT_TEMPLE_SKY_TEMPLE_MLVL,
                    constants.SKY_TEMPLE_ENERGY_CONTROLLER_MREA,
                    goal_warp_patch.warp_to_credits_from_energy_controller,
                )
            ],
        )

    def test_emperor_ing_registers_the_gateway_only(self) -> None:
        self.assertEqual(
            self._register(constants.GOAL_EMPEROR_ING),
            [
                (
                    constants.TEMPLE_GROUNDS_MLVL,
                    constants.SKY_TEMPLE_GATEWAY_MREA,
                    goal_warp_patch.warp_to_credits_from_gateway,
                )
            ],
        )


@unittest.skipUnless(_OPR_AVAILABLE, "open-prime-rando is not installed")
class TestGoalWarpInstalled(unittest.TestCase):
    """``goal_warp_installed`` wraps the open-prime-rando hook and must
    restore it just as carefully as its siblings -- it nests inside one
    ``_apply_patches`` call alongside every other hook."""

    def test_wraps_and_restores_register_world_changes(self) -> None:
        from open_prime_rando.echoes import patcher as opr_patcher

        from ..client.patcher_runner import goal_warp_installed

        original = opr_patcher.register_world_changes
        with goal_warp_installed(constants.GOAL_KEYS):
            self.assertIsNot(opr_patcher.register_world_changes, original)
        self.assertIs(opr_patcher.register_world_changes, original)

    def test_restores_even_on_exception(self) -> None:
        from open_prime_rando.echoes import patcher as opr_patcher

        from ..client.patcher_runner import goal_warp_installed

        original = opr_patcher.register_world_changes
        with self.assertRaises(RuntimeError):
            with goal_warp_installed(constants.GOAL_EMPEROR_ING):
                raise RuntimeError("boom")
        self.assertIs(opr_patcher.register_world_changes, original)


class _GoalOptionTest(MP2TestBase):
    """config.json is an OPR ``RandoConfiguration`` with no field for the
    goal, so it travels in options.json -- where
    ``patcher_runner.patch_iso_with_ap`` reads it back from."""

    expected: int

    def test_goal_lands_in_options_json(self) -> None:
        if type(self) is _GoalOptionTest:
            self.skipTest("base class")
        with tempfile.TemporaryDirectory() as output_directory:
            self.world.generate_output(output_directory)
            containers = list(pathlib.Path(output_directory).glob("*.apmp2"))
            self.assertEqual(len(containers), 1)
            with zipfile.ZipFile(containers[0]) as container:
                options = json.loads(container.read("options.json"))
        self.assertEqual(options["goal"], self.expected)


class TestDefaultGoalInOptionsJson(_GoalOptionTest):
    expected = constants.GOAL_BOTH_BOSSES


class TestEmperorIngGoalInOptionsJson(_GoalOptionTest):
    options = {"goal": "emperor_ing"}
    expected = constants.GOAL_EMPEROR_ING


class TestKeysGoalInOptionsJson(_GoalOptionTest):
    options = {"goal": "keys"}
    expected = constants.GOAL_KEYS
