"""Tests for the Sky Temple Key gate rewrite
(``client/sky_temple_key_gate_patch.py``): the connection-rewiring logic
itself, and the option's route from the YAML into the ``.apmp2``'s
options.json.

The in-game half (does moving the connection actually still open the
gate) can only be checked against a real ISO -- see the module's own
docstring for how the mechanism was reverse-engineered.
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

from ..client import sky_temple_key_gate_patch
from .bases import MP2TestBase

_OPR_AVAILABLE = importlib.util.find_spec("open_prime_rando") is not None
_RDS_AVAILABLE = importlib.util.find_spec("retro_data_structures") is not None


@dataclass
class _FakeConnection:
    state: object
    message: object
    target: object


class _FakeProps:
    def __init__(self, name: str, string: int = 0) -> None:
        self.name = name
        self.string = string

    @property
    def editor_properties(self) -> _FakeProps:
        return self


class _FakeInstance:
    """Enough of retro_data_structures' ScriptInstance for the gate
    rewrite: a name, and a mutable connection list matching the real
    ``add_connection``/``remove_connection`` contract."""

    def __init__(self, name: str, connections: list[_FakeConnection], string: int = 0) -> None:
        self._name = name
        self._string = string
        self.connections = list(connections)

    def get_properties_as(self, type_cls: object) -> _FakeProps:
        return _FakeProps(self._name, self._string)

    def get_properties(self) -> _FakeProps:
        return _FakeProps(self._name, self._string)

    def remove_connection(self, connection: _FakeConnection) -> None:
        self.connections = [c for c in self.connections if c is not connection]

    def add_connection(self, state: object, message: object, target: object) -> None:
        self.connections.append(_FakeConnection(state, message, target))


class _FakeArea:
    name = "Fake Sky Temple Gateway"

    def __init__(self, instances: dict[Any, _FakeInstance]) -> None:
        self._instances = instances

    def get_instance(self, name_or_id: Any) -> _FakeInstance:
        return self._instances[name_or_id]


class _FakeStrg:
    def __init__(self) -> None:
        self.strings = ["vanilla"]

    def set_single_string(self, index: int, value: str) -> None:
        self.strings[index] = value


class _FakeEditor:
    """``get_file`` hands out one ``_FakeStrg`` per asset id."""

    def __init__(self) -> None:
        self.strgs: dict[int, _FakeStrg] = {}

    def get_file(self, asset_id: int, type_cls: object = None) -> _FakeStrg:
        return self.strgs.setdefault(asset_id, _FakeStrg())


_MEMO_STRG_BASE = 0x1000


def _fake_counter(open_target: int = 0x2A0203) -> tuple[_FakeArea, _FakeInstance]:
    """A counter wired like the real one: ``InternalState{N-1}`` activates
    the "Returned N Keys" memo (target id ``0x2A0100 + N``, STRG
    ``_MEMO_STRG_BASE + N``) for N=1..8, plus a Deactivate decoy and the
    ``Open`` connection from the 9th state."""
    from retro_data_structures.enums.echoes import Message, State

    connections = [_FakeConnection(State.InternalState02, Message.Deactivate, 0xDEAD)]
    instances: dict[Any, _FakeInstance] = {}
    for returned in range(1, 9):
        target = 0x2A0100 + returned
        connections.append(_FakeConnection(State[f"InternalState{returned - 1:02d}"], Message.Activate, target))
        instances[target] = _FakeInstance(f"Returned {returned} Keys", [], string=_MEMO_STRG_BASE + returned)
    connections.append(_FakeConnection(State.InternalState08, Message.Open, open_target))
    counter = _FakeInstance("Count Keys Returned", connections)
    instances["Count Keys Returned"] = counter
    return _FakeArea(instances), counter


@unittest.skipUnless(_RDS_AVAILABLE, "retro_data_structures is not installed")
class TestSetSkyTempleKeyRequirement(unittest.TestCase):
    def test_moves_open_connection_to_the_required_internal_state(self) -> None:
        from retro_data_structures.enums.echoes import Message, State

        area, counter = _fake_counter()
        sky_temple_key_gate_patch.set_sky_temple_key_requirement(_FakeEditor(), None, cast(Any, area), 6)

        open_connections = [c for c in counter.connections if c.message == Message.Open]
        self.assertEqual(len(open_connections), 1)
        self.assertEqual(open_connections[0].state, State.InternalState05)
        self.assertEqual(open_connections[0].target, 0x2A0203)

    def test_preserves_other_connections(self) -> None:
        from retro_data_structures.enums.echoes import Message, State

        area, counter = _fake_counter()
        sky_temple_key_gate_patch.set_sky_temple_key_requirement(_FakeEditor(), None, cast(Any, area), 6)

        decoy = _FakeConnection(State.InternalState02, Message.Deactivate, 0xDEAD)
        non_open = [c for c in counter.connections if c.message != Message.Open]
        self.assertEqual(len(non_open), 9)
        self.assertIn(decoy, non_open)

    def test_nine_is_a_no_op(self) -> None:
        area, counter = _fake_counter()
        editor = _FakeEditor()
        original = list(counter.connections)
        sky_temple_key_gate_patch.set_sky_temple_key_requirement(editor, None, cast(Any, area), 9)
        self.assertEqual(counter.connections, original)
        self.assertEqual(editor.strgs, {})

    def test_return_memos_count_down_to_the_required_value(self) -> None:
        area, _counter = _fake_counter()
        editor = _FakeEditor()
        sky_temple_key_gate_patch.set_sky_temple_key_requirement(editor, None, cast(Any, area), 6)

        def text(returned: int) -> str:
            return editor.strgs[_MEMO_STRG_BASE + returned].strings[0]

        self.assertEqual(text(1), "1 Sky Temple Key has been returned.\nYou must find 5 more.")
        self.assertEqual(text(3), "3 Sky Temple Keys have been returned.\nYou must find 3 more.")
        self.assertEqual(text(5), "5 Sky Temple Keys have been returned.\nYou must find 1 more.")
        # At and past the requirement the gate is open: no "find 0 more".
        for returned in (6, 7, 8):
            self.assertEqual(
                text(returned), f"{returned} Sky Temple Keys have been returned.\nYou can now enter the Sky Temple."
            )

    def test_required_one_opens_on_the_first_key(self) -> None:
        area, _counter = _fake_counter()
        editor = _FakeEditor()
        sky_temple_key_gate_patch.set_sky_temple_key_requirement(editor, None, cast(Any, area), 1)
        self.assertEqual(
            editor.strgs[_MEMO_STRG_BASE + 1].strings[0],
            "1 Sky Temple Key has been returned.\nYou can now enter the Sky Temple.",
        )

    def test_rejects_out_of_range_values(self) -> None:
        area, _counter = _fake_counter()
        for bad in (0, 10, -1):
            with self.subTest(bad):
                with self.assertRaises(ValueError):
                    sky_temple_key_gate_patch.set_sky_temple_key_requirement(_FakeEditor(), None, cast(Any, area), bad)

    def test_rejects_more_than_one_open_connection(self) -> None:
        from retro_data_structures.enums.echoes import Message, State

        counter = _FakeInstance(
            "Count Keys Returned",
            [
                _FakeConnection(State.InternalState08, Message.Open, 1),
                _FakeConnection(State.InternalState07, Message.Open, 2),
            ],
        )
        area = _FakeArea({"Count Keys Returned": counter})
        with self.assertRaises(AssertionError):
            sky_temple_key_gate_patch.set_sky_temple_key_requirement(_FakeEditor(), None, cast(Any, area), 6)


class _FakeAreaPatcher:
    def __init__(self) -> None:
        self.calls: list[tuple[int, int, Any]] = []

    def add_raw_function(self, mlvl_id: int, mrea_id: int, func: Any) -> None:
        self.calls.append((mlvl_id, mrea_id, func))


class TestRegister(unittest.TestCase):
    def test_registers_against_sky_temple_gateway_with_the_required_value_bound(self) -> None:
        patcher = _FakeAreaPatcher()
        sky_temple_key_gate_patch.register(cast(Any, patcher), 6)

        self.assertEqual(len(patcher.calls), 1)
        mlvl_id, mrea_id, func = patcher.calls[0]
        self.assertEqual(mlvl_id, sky_temple_key_gate_patch._TEMPLE_GROUNDS_MLVL)
        self.assertEqual(mrea_id, sky_temple_key_gate_patch._SKY_TEMPLE_GATEWAY_MREA)
        self.assertEqual(func.func, sky_temple_key_gate_patch.set_sky_temple_key_requirement)
        self.assertEqual(func.keywords, {"required": 6})


@unittest.skipUnless(_OPR_AVAILABLE, "open-prime-rando is not installed")
class TestSkyTempleKeysRequiredInstalled(unittest.TestCase):
    """``sky_temple_keys_required_installed`` wraps the open-prime-rando
    hook and must restore it just as carefully -- it nests inside one
    ``_apply_patches`` call alongside every other hook (e.g.
    ``warp_to_start_installed``, ``item_map_dots_installed``)."""

    def test_wraps_and_restores_register_world_changes(self) -> None:
        from open_prime_rando.echoes import patcher as opr_patcher

        from ..client.patcher_runner import sky_temple_keys_required_installed

        original = opr_patcher.register_world_changes
        with sky_temple_keys_required_installed(6):
            self.assertIsNot(opr_patcher.register_world_changes, original)
        self.assertIs(opr_patcher.register_world_changes, original)

    def test_restores_even_on_exception(self) -> None:
        from open_prime_rando.echoes import patcher as opr_patcher

        from ..client.patcher_runner import sky_temple_keys_required_installed

        original = opr_patcher.register_world_changes
        with self.assertRaises(RuntimeError):
            with sky_temple_keys_required_installed(6):
                raise RuntimeError("boom")
        self.assertIs(opr_patcher.register_world_changes, original)


class _SkyTempleKeysRequiredOptionTest(MP2TestBase):
    """Generates the ``.apmp2`` and checks where the resolved value ended
    up. config.json is an OPR ``RandoConfiguration`` validated with
    ``extra="forbid"`` and has no ``sky_temple_keys_required`` field, so
    the (already-clamped, see ``item_pool.sky_temple_keys_required_count``)
    value has to travel in options.json instead -- exactly where
    ``patcher_runner.patch_iso_with_ap`` reads it back from."""

    expected: int

    def _generate_container(self) -> dict[str, object]:
        with tempfile.TemporaryDirectory() as output_directory:
            self.world.generate_output(output_directory)
            containers = list(pathlib.Path(output_directory).glob("*.apmp2"))
            self.assertEqual(len(containers), 1)
            with zipfile.ZipFile(containers[0]) as container:
                options = json.loads(container.read("options.json"))
                config = json.loads(container.read("config.json"))
        self.assertNotIn("sky_temple_keys_required", config)
        return options

    def test_value_lands_in_options_json(self) -> None:
        if type(self) is _SkyTempleKeysRequiredOptionTest:
            self.skipTest("base class")
        self.assertEqual(self._generate_container()["sky_temple_keys_required"], self.expected)


class TestSkyTempleKeysRequiredDefaultInOptionsJson(_SkyTempleKeysRequiredOptionTest):
    expected = 9


class TestSkyTempleKeysRequiredLoweredInOptionsJson(_SkyTempleKeysRequiredOptionTest):
    options = {"sky_temple_keys_required": 6}
    expected = 6


class TestSkyTempleKeysRequiredClampedInOptionsJson(_SkyTempleKeysRequiredOptionTest):
    options = {"sky_temple_keys": 3, "sky_temple_keys_required": 9}
    expected = 3
