"""Tests for the map reveal patch (``client/map_reveal_patch.py``): the DOL
write that lets a map station reveal dark world rooms, and the Great Temple
always-drawn override. Whether the names then show can only be checked
in-game."""

from __future__ import annotations

import importlib.util
import json
import pathlib
import struct
import tempfile
import unittest
import zipfile
from types import SimpleNamespace

from ..client import map_reveal_patch, versions
from .bases import MP2TestBase
from .test_spring_ball_patch import _FakeDol

_OPR_AVAILABLE = importlib.util.find_spec("open_prime_rando") is not None
_PPC_ASM_AVAILABLE = importlib.util.find_spec("ppc_asm") is not None

_VANILLA = struct.pack(">3I", *map_reveal_patch._VANILLA_DARK_WORLD_CHECK)


@unittest.skipUnless(_PPC_ASM_AVAILABLE, "ppc_asm is not installed")
class TestDarkRoomReveal(unittest.TestCase):
    def test_replaces_the_dark_world_check_with_true(self) -> None:
        for version in versions.VERSIONS:
            with self.subTest(version.name):
                dol = _FakeDol()
                address = version.map_reveal.dark_world_check
                dol.write(address, _VANILLA)
                map_reveal_patch.reveal_dark_rooms_on_map_station(dol, version.map_reveal)  # type: ignore[arg-type]
                self.assertEqual(dol.word(address), 0x38600001)  # li r3, 1
                self.assertEqual(dol.word(address + 4), 0x60000000)  # nop
                self.assertEqual(dol.word(address + 8), 0x60000000)  # nop

    def test_refuses_an_unexpected_dol(self) -> None:
        addresses = versions.NTSC.map_reveal
        dol = _FakeDol()
        dol.write(addresses.dark_world_check, b"\x60\x00\x00\x00" * 3)
        with self.assertRaises(ValueError):
            map_reveal_patch.reveal_dark_rooms_on_map_station(dol, addresses)  # type: ignore[arg-type]

    def test_addresses_are_distinct_per_version(self) -> None:
        self.assertNotEqual(versions.NTSC.map_reveal.dark_world_check, versions.PAL.map_reveal.dark_world_check)


@unittest.skipUnless(_OPR_AVAILABLE, "open-prime-rando is not installed")
class TestGreatTempleAlwaysMapped(unittest.TestCase):
    def _run(self, in_great_temple: bool, original_mode: object) -> object:
        from open_prime_rando.echoes import general_changes

        great_temple = object()
        editor = SimpleNamespace(get_mlvl=lambda _: great_temple)
        area = SimpleNamespace(mapa=SimpleNamespace(visibility_mode=original_mode))
        mlvl = great_temple if in_great_temple else object()
        real = general_changes.change_map_visibility
        general_changes.change_map_visibility = lambda *_: None  # OPR's own rewrite is not under test
        try:
            with map_reveal_patch.great_temple_always_mapped():
                general_changes.change_map_visibility(editor, mlvl, area, None)  # type: ignore[arg-type]
        finally:
            general_changes.change_map_visibility = real
        return area.mapa.visibility_mode

    def test_great_temple_rooms_become_always_visible(self) -> None:
        from retro_data_structures.formats.mapa import AreaVisibility

        self.assertEqual(self._run(True, AreaVisibility.VisitOrMapStation), AreaVisibility.Always)

    def test_hidden_rooms_stay_hidden(self) -> None:
        from retro_data_structures.formats.mapa import AreaVisibility

        self.assertEqual(self._run(True, AreaVisibility.Never), AreaVisibility.Never)

    def test_other_worlds_keep_what_opr_decided(self) -> None:
        from retro_data_structures.formats.mapa import AreaVisibility

        self.assertEqual(self._run(False, AreaVisibility.VisitOrMapStation), AreaVisibility.VisitOrMapStation)

    def test_restores_opr_on_exit(self) -> None:
        from open_prime_rando.echoes import general_changes

        before = general_changes.change_map_visibility
        with map_reveal_patch.great_temple_always_mapped():
            self.assertIsNot(general_changes.change_map_visibility, before)
        self.assertIs(general_changes.change_map_visibility, before)


@unittest.skipUnless(_OPR_AVAILABLE, "open-prime-rando is not installed")
class TestMapRevealInstalled(unittest.TestCase):
    def _install(self, **kwargs: bool) -> tuple[_FakeDol, object, object]:
        from open_prime_rando.echoes import general_changes
        from open_prime_rando.echoes.version import EchoesVersion

        from ..client.patcher_runner import map_reveal_installed

        dol = _FakeDol()
        address = versions.NTSC.map_reveal.dark_world_check
        dol.write(address, _VANILLA)
        dol_version = SimpleNamespace(echoes_version=EchoesVersion.NTSC_U)
        before = general_changes.change_map_visibility
        with map_reveal_installed(SimpleNamespace(dol=dol), dol_version, **kwargs):
            during = general_changes.change_map_visibility
        return dol, before, during

    def test_dark_world_option_alone_writes_the_dol_only(self) -> None:
        dol, before, during = self._install(dark_world=True, great_temple=False)
        self.assertEqual(dol.word(versions.NTSC.map_reveal.dark_world_check), 0x38600001)
        self.assertIs(during, before)

    def test_unvisited_names_alone_leaves_the_dol_vanilla(self) -> None:
        dol, before, during = self._install(dark_world=False, great_temple=True)
        self.assertEqual(dol.read(versions.NTSC.map_reveal.dark_world_check, 12), _VANILLA)
        self.assertIsNot(during, before)


class _DarkWorldOptionTest(MP2TestBase):
    """The option has no field in OPR's ``RandoConfiguration``, so it travels
    in options.json, where ``patcher_runner.patch_iso_with_ap`` reads it."""

    expected: bool

    def test_lands_in_options_json(self) -> None:
        if type(self) is _DarkWorldOptionTest:
            self.skipTest("base class")
        with tempfile.TemporaryDirectory() as output_directory:
            self.world.generate_output(output_directory)
            (container_path,) = pathlib.Path(output_directory).glob("*.apmp2")
            with zipfile.ZipFile(container_path) as container:
                options = json.loads(container.read("options.json"))
                config = json.loads(container.read("config.json"))
        self.assertNotIn("map_rooms_reveal_dark_world_map", config)
        self.assertIs(options["map_rooms_reveal_dark_world_map"], self.expected)


class TestDarkWorldMapDefault(_DarkWorldOptionTest):
    expected = True


class TestDarkWorldMapOff(_DarkWorldOptionTest):
    options = {"map_rooms_reveal_dark_world_map": False}
    expected = False
