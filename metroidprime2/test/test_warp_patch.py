"""Tests for warp-to-start (``client/warp_patch.py``): the save-station
discovery predicate, the PPC gate cave's exact encoding, and the option's
route from the YAML into the ``.apmp2``'s options.json.

The in-game half can only be checked against a real ISO (see
``metroidprime2/tools/find_warp_addresses.py`` and the manual steps in
README.md); what's locked down here is everything that can drift silently.
"""

from __future__ import annotations

import importlib.util
import json
import pathlib
import struct
import tempfile
import unittest
import zipfile
from dataclasses import dataclass
from typing import TYPE_CHECKING, cast

from ..client import versions, warp_patch
from .bases import MP2TestBase

if TYPE_CHECKING:
    from retro_data_structures.formats.mrea import Area

_OPR_AVAILABLE = importlib.util.find_spec("open_prime_rando") is not None
_PPC_ASM_AVAILABLE = importlib.util.find_spec("ppc_asm") is not None


@dataclass(frozen=True)
class _FakeConnection:
    state: object


class _FakeInstance:
    """Enough of ``retro_data_structures``' ScriptInstance for the discovery
    predicate: a type name, decodable properties and connections."""

    def __init__(self, type_name: str, properties: object, states: list[object]) -> None:
        self.type_name = type_name
        self._properties = properties
        self.connections = [_FakeConnection(state) for state in states]

    def get_properties(self) -> object:
        return self._properties


class _FakeLayer:
    def __init__(self, instances: list[_FakeInstance]) -> None:
        self.instances = instances


class _FakeArea:
    name = "Fake Area"

    def __init__(self, instances: list[_FakeInstance]) -> None:
        self.layers = [_FakeLayer(instances)]


def _fake_area(instances: list[_FakeInstance]) -> Area:
    """A real ``Area`` can't be built without an MREA, and the discovery
    predicate only touches ``layers``/``name``."""
    return cast("Area", _FakeArea(instances))


@unittest.skipUnless(_OPR_AVAILABLE, "retro_data_structures is not installed")
class TestSaveStationDiscovery(unittest.TestCase):
    """``find_save_station_special_function`` must match a prompting Save
    Station and nothing else. The negative case is real: Great Temple's
    Sanctum has a SaveStationCheckpoint SpecialFunction with no ``Zero``
    connections (an autosave that never prompts), and patching it would wire
    a warp to a state the game never broadcasts there."""

    def _special_function(self, function: int, states: list[object]) -> _FakeInstance:
        from retro_data_structures.properties.echoes.objects import SpecialFunction
        from retro_data_structures.properties.echoes.objects.SpecialFunction import Function

        return _FakeInstance("SPFN", SpecialFunction(function=Function(function)), states)

    def test_finds_save_station_with_a_zero_connection(self) -> None:
        from retro_data_structures.enums.echoes import State

        instance = self._special_function(7, [State.Closed, State.Zero, State.MaxReached])
        self.assertIs(
            warp_patch.find_save_station_special_function(_fake_area([instance])),
            instance,
        )

    def test_skips_save_station_without_a_zero_connection(self) -> None:
        from retro_data_structures.enums.echoes import State

        instance = self._special_function(7, [State.MaxReached])
        self.assertIsNone(warp_patch.find_save_station_special_function(_fake_area([instance])))

    def test_skips_other_special_functions(self) -> None:
        from retro_data_structures.enums.echoes import State

        # Function 6 is MapStation, which also lives in rooms with Zero
        # connections.
        instance = self._special_function(6, [State.Zero])
        self.assertIsNone(warp_patch.find_save_station_special_function(_fake_area([instance])))

    def test_skips_non_special_function_instances(self) -> None:
        from retro_data_structures.enums.echoes import State

        instance = _FakeInstance("TIMR", object(), [State.Zero])
        self.assertIsNone(warp_patch.find_save_station_special_function(_fake_area([instance])))

    def test_rejects_multiple_save_stations_in_one_area(self) -> None:
        from retro_data_structures.enums.echoes import State

        instances = [self._special_function(7, [State.Zero]) for _ in range(2)]
        with self.assertRaises(ValueError):
            warp_patch.find_save_station_special_function(_fake_area(instances))


@unittest.skipUnless(_PPC_ASM_AVAILABLE, "ppc_asm is not installed")
class TestGateCave(unittest.TestCase):
    """Pins the assembled gate cave, the way test_game_interface pins
    ``create_remote_execution_body``. This can't prove the hook is correct
    in-game, but it catches an encoding or branch-offset regression -- and a
    wrong branch offset here would fall through into the state swap and
    broadcast a corrupted script state on every declined save."""

    def _assemble(self, address: int, version: versions.EchoesVersionInfo) -> list[int]:
        from ppc_asm import assembler

        data = bytes(
            assembler.assemble_instructions(
                address, warp_patch.build_gate_cave(version.warp_to_start)
            )
        )
        return [word[0] for word in struct.iter_unpack(">I", data)]

    def test_ntsc_encoding(self) -> None:
        self.assertEqual(
            self._assemble(0x8010F08C, versions.NTSC),
            [
                0x3965153C,  # addi  r11, r5, 0x153c   ; &CFinalInput[0]
                0x3D803D4C,  # lis   r12, 0x3d4c       ; 0.05f, as raw bits
                0x618CCCCD,  # ori   r12, r12, 0xcccd
                0x800B0018,  # lwz   r0, 0x18(r11)     ; left trigger, held
                0x7C006000,  # cmpw  r0, r12
                0x40810018,  # ble   +0x18             ; -> tail branch
                0x800B001C,  # lwz   r0, 0x1c(r11)     ; right trigger, held
                0x7C006000,  # cmpw  r0, r12
                0x4081000C,  # ble   +0xc              ; -> tail branch
                0x3C804953,  # lis   r4, 0x4953        ; 'IS15'
                0x60843135,  # ori   r4, r4, 0x3135
                0x4BF38F38,  # b     0x80047ff0        ; SendScriptMsgs
            ],
        )

    def test_both_branches_skip_the_whole_state_swap(self) -> None:
        # Each `ble` must land exactly on the tail branch: one instruction
        # short and the `ori` still runs, OR-ing 0x3135 into the ZERO fourcc.
        for version in versions.VERSIONS:
            with self.subTest(version.name):
                address = 0x8010F000
                words = self._assemble(address, version)
                tail = address + (len(words) - 1) * 4
                for index, word in enumerate(words):
                    if (word >> 26) == 16:  # bc
                        offset = word & 0xFFFC
                        if offset & 0x8000:
                            offset -= 0x10000
                        self.assertEqual(address + index * 4 + offset, tail)

    def test_tail_branch_targets_send_script_msgs(self) -> None:
        for version in versions.VERSIONS:
            with self.subTest(version.name):
                address = 0x8010F000
                words = self._assemble(address, version)
                tail_index = len(words) - 1
                tail = words[tail_index]
                self.assertEqual(tail >> 26, 18, "last instruction must be a branch")
                self.assertFalse(tail & 1, "tail branch must not link")
                displacement = tail & 0x03FFFFFC
                if displacement & 0x02000000:
                    displacement -= 0x04000000
                self.assertEqual(
                    address + tail_index * 4 + displacement,
                    version.warp_to_start.send_script_msgs,
                )

    def test_fits_in_the_code_cave_budget(self) -> None:
        # open-prime-rando's registered empty space is ~0x150 bytes and it
        # spends some itself, so keep this comfortably small.
        self.assertLessEqual(len(self._assemble(0x8010F000, versions.NTSC)) * 4, 0x80)


class _WarpToStartOptionTest(MP2TestBase):
    """Generates the ``.apmp2`` and checks where the flag ended up.

    config.json is an OPR ``RandoConfiguration`` validated with
    ``extra="forbid"`` and has no ``warp_to_start`` field, so the flag has
    to travel in options.json instead -- which is exactly where
    ``patcher_runner.patch_iso_with_ap`` reads it back from.
    """

    expected: bool

    def _generate_container(self) -> dict[str, object]:
        with tempfile.TemporaryDirectory() as output_directory:
            self.world.generate_output(output_directory)
            containers = list(pathlib.Path(output_directory).glob("*.apmp2"))
            self.assertEqual(len(containers), 1)
            with zipfile.ZipFile(containers[0]) as container:
                options = json.loads(container.read("options.json"))
                config = json.loads(container.read("config.json"))
        self.assertNotIn("warp_to_start", config)
        return options

    def test_flag_lands_in_options_json(self) -> None:
        if type(self) is _WarpToStartOptionTest:
            self.skipTest("base class")
        self.assertEqual(self._generate_container()["warp_to_start"], self.expected)


class TestWarpToStartEnabled(_WarpToStartOptionTest):
    options = {"warp_to_start": True}
    expected = True


class TestWarpToStartDisabled(_WarpToStartOptionTest):
    options = {"warp_to_start": False}
    expected = False


@unittest.skipUnless(_OPR_AVAILABLE, "open-prime-rando is not installed")
class TestWarpToStartInstalled(unittest.TestCase):
    """``warp_to_start_installed`` wraps the same open-prime-rando hook as
    ``goal_trigger_installed`` and must restore it just as carefully -- the
    two nest inside one ``_apply_patches`` call."""

    def _dol_version(self, echoes_version: object) -> object:
        @dataclass(frozen=True)
        class FakeDolVersion:
            echoes_version: object
            description: str = "Fake"

        return FakeDolVersion(echoes_version)

    def test_wraps_and_restores_register_world_changes(self) -> None:
        from open_prime_rando.echoes import patcher as opr_patcher
        from open_prime_rando.echoes.version import EchoesVersion

        from ..client.patcher_runner import warp_to_start_installed

        original = opr_patcher.register_world_changes
        with warp_to_start_installed(self._dol_version(EchoesVersion.NTSC_U), None):
            self.assertIsNot(opr_patcher.register_world_changes, original)
        self.assertIs(opr_patcher.register_world_changes, original)

    def test_restores_even_on_exception(self) -> None:
        from open_prime_rando.echoes import patcher as opr_patcher
        from open_prime_rando.echoes.version import EchoesVersion

        from ..client.patcher_runner import warp_to_start_installed

        original = opr_patcher.register_world_changes
        with self.assertRaises(RuntimeError):
            with warp_to_start_installed(self._dol_version(EchoesVersion.PAL), None):
                raise RuntimeError("boom")
        self.assertIs(opr_patcher.register_world_changes, original)

    def test_rejects_builds_without_known_addresses(self) -> None:
        # The hook address is build-specific; silently skipping it would
        # ship an ISO where the gesture does nothing.
        from open_prime_rando.echoes.version import EchoesVersion

        from ..client.patcher_runner import warp_to_start_installed

        for echoes_version in (EchoesVersion.NTSC_J, EchoesVersion.TRILOGY_NTSC):
            with self.subTest(echoes_version.name), self.assertRaises(ValueError):
                with warp_to_start_installed(self._dol_version(echoes_version), None):
                    pass
