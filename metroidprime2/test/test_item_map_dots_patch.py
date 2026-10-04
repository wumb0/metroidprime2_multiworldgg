"""Tests for item map dots (``client/item_map_dots_patch.py``): the cave and
jump table entry once ``CodeCaveTracker`` has placed them, the build guard,
the MAPA visibility rewrite, and the option's route from the YAML into the
``.apmp2``'s options.json.

Whether a dot actually shows can only be checked in-game; what's locked
down here is everything that can drift silently.
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

from ..client import item_map_dots_patch, spring_ball_patch, versions
from .bases import MP2TestBase
from .test_spring_ball_patch import _OPR_FREE_SPACE, _branch_target, _FakeDol, _write_vanilla_hook_site

_OPR_AVAILABLE = importlib.util.find_spec("open_prime_rando") is not None
_PPC_ASM_AVAILABLE = importlib.util.find_spec("ppc_asm") is not None

_TEXTURE_ID = 0x3DCBACA5
"""``resolve_asset_id("pickup_map_icon.TXTR")`` -- a hash of the name."""


def _write_vanilla_draw(dol: _FakeDol, addresses: versions.ItemMapDotAddresses) -> None:
    from ppc_asm.assembler import ppc

    entry = addresses.icon_jump_table + 4 * (item_map_dots_patch.PICKUP_OBJECT_TYPE - 0x10)
    dol.write(entry, struct.pack(">I", addresses.no_icon_case))
    dol.write_instructions(addresses.flag_lookup_call, [ppc.bl(addresses.object_flag_lookup)])


def _entry(addresses: versions.ItemMapDotAddresses) -> int:
    return addresses.icon_jump_table + 4 * (item_map_dots_patch.PICKUP_OBJECT_TYPE - 0x10)


@unittest.skipUnless(_OPR_AVAILABLE and _PPC_ASM_AVAILABLE, "open-prime-rando is not installed")
class TestCave(unittest.TestCase):
    """Runs the real ``CodeCaveTracker`` over open-prime-rando's free space,
    competing with every other cave request an Echoes patch can make, then
    reads the placed cave back."""

    def _place(self, version: versions.EchoesVersionInfo) -> tuple[_FakeDol, int]:
        from open_prime_rando.dol_patching.code_cave_tracker import CodeCaveTracker
        from ppc_asm.assembler import ppc

        from ..client import warp_patch

        dol = _FakeDol()
        _write_vanilla_draw(dol, version.item_map_dots)
        _write_vanilla_hook_site(dol, version.spring_ball)
        cave = CodeCaveTracker(dol)  # type: ignore[arg-type]
        for start, length in _OPR_FREE_SPACE:
            cave.add_empty_space(start, length=length)
        # open-prime-rando's own requests: the new inventory slot table, the
        # "Locations: %d/N" format string, Massive Damage's cave.
        cave.request_data_cave(bytes(0x35), 1, lambda _: None)
        cave.request_data_cave(b"%d/100\x00", 1, lambda _: None)
        cave.request_code_cave([ppc.nop()] * 11, lambda _: None)
        warp_patch.apply_dol_patches(cave, version.warp_to_start)
        spring_ball_patch.apply_dol_patches(cave, version.spring_ball, "c_stick_up")
        item_map_dots_patch.apply_dol_patches(cave, version.item_map_dots, _TEXTURE_ID)
        cave.fulfill_requests()
        return dol, dol.word(_entry(version.item_map_dots))

    def test_jump_table_entry_points_at_the_cave(self) -> None:
        for version in versions.VERSIONS:
            with self.subTest(version.name):
                dol, cave = self._place(version)
                self.assertNotEqual(cave, version.item_map_dots.no_icon_case)
                self.assertEqual(cave % 4, 0)
                # The cave starts by reading the object's editor id.
                obj = version.item_map_dots.object_register
                self.assertEqual(dol.word(cave), 0x80000008 | (obj << 16))  # lwz r0, 8(obj)

    def test_other_jump_table_entries_untouched(self) -> None:
        for version in versions.VERSIONS:
            with self.subTest(version.name):
                dol, _ = self._place(version)
                addresses = version.item_map_dots
                for object_type in range(0x10, 0x1A):
                    if object_type != item_map_dots_patch.PICKUP_OBJECT_TYPE:
                        self.assertEqual(dol.word(addresses.icon_jump_table + 4 * (object_type - 0x10)), 0)

    def test_loads_the_texture_into_r30(self) -> None:
        for version in versions.VERSIONS:
            with self.subTest(version.name):
                dol, cave = self._place(version)
                self.assertEqual(dol.word(cave + 8), 0x3FC00000 | (_TEXTURE_ID >> 16))  # lis r30, hi
                self.assertEqual(dol.word(cave + 12), 0x63DE0000 | (_TEXTURE_ID & 0xFFFF))  # ori r30, r30, lo

    def test_ends_by_branching_to_the_translator_lookup_call(self) -> None:
        for version in versions.VERSIONS:
            with self.subTest(version.name):
                from ppc_asm import assembler

                dol, cave = self._place(version)
                size = assembler.byte_count(item_map_dots_patch.build_cave(version.item_map_dots, _TEXTURE_ID))
                last = cave + size - 4
                word = dol.word(last)
                self.assertEqual(word & 0xFC000003, 0x48000000, "must be a plain b")
                self.assertEqual(_branch_target(last, word), version.item_map_dots.flag_lookup_call)

    def test_lookup_arguments(self) -> None:
        # NTSC's Draw already has the CMapWorldInfo in r3; PAL keeps it in r29.
        ntsc, ntsc_cave = self._place(versions.NTSC)
        self.assertEqual(ntsc.word(ntsc_cave + 16), 0x38810010)  # addi r4, r1, 0x10
        pal, pal_cave = self._place(versions.PAL)
        self.assertEqual(pal.word(pal_cave + 16), 0x7FA3EB78)  # mr r3, r29
        self.assertEqual(pal.word(pal_cave + 20), 0x38810010)  # addi r4, r1, 0x10

    def test_stores_the_editor_id_where_r4_points(self) -> None:
        for version in versions.VERSIONS:
            with self.subTest(version.name):
                dol, cave = self._place(version)
                self.assertEqual(dol.word(cave + 4), 0x90010010)  # stw r0, 0x10(r1)

    def test_refuses_an_unexpected_jump_table_entry(self) -> None:
        from open_prime_rando.dol_patching.code_cave_tracker import CodeCaveTracker

        addresses = versions.NTSC.item_map_dots
        dol = _FakeDol()
        _write_vanilla_draw(dol, addresses)
        dol.write(_entry(addresses), struct.pack(">I", 0x800BBAB8))  # already the translator case
        with self.assertRaises(ValueError):
            item_map_dots_patch.apply_dol_patches(CodeCaveTracker(dol), addresses, _TEXTURE_ID)  # type: ignore[arg-type]

    def test_refuses_an_unexpected_lookup_call(self) -> None:
        from open_prime_rando.dol_patching.code_cave_tracker import CodeCaveTracker

        addresses = versions.NTSC.item_map_dots
        dol = _FakeDol()
        _write_vanilla_draw(dol, addresses)
        dol.write(addresses.flag_lookup_call, b"\x60\x00\x00\x00")  # nop
        with self.assertRaises(ValueError):
            item_map_dots_patch.apply_dol_patches(CodeCaveTracker(dol), addresses, _TEXTURE_ID)  # type: ignore[arg-type]


@unittest.skipUnless(_OPR_AVAILABLE, "open-prime-rando is not installed")
class TestItemMapDotsInstalled(unittest.TestCase):
    def test_rejects_builds_without_known_addresses(self) -> None:
        from open_prime_rando.echoes.version import EchoesVersion

        from ..client.patcher_runner import item_map_dots_installed

        @dataclass(frozen=True)
        class FakeDolVersion:
            echoes_version: object
            description: str = "Fake"

        for echoes_version in (EchoesVersion.NTSC_J, EchoesVersion.TRILOGY_NTSC):
            with self.subTest(echoes_version.name), self.assertRaises(ValueError):
                with item_map_dots_installed(object(), FakeDolVersion(echoes_version)):
                    pass


@unittest.skipUnless(_OPR_AVAILABLE, "open-prime-rando is not installed")
class TestPickupIconVisibility(unittest.TestCase):
    """``pickup_icon_visibility_installed`` swaps open-prime-rando's
    hardcoded visibility (1, which Echoes treats as "always") for
    ``MAP_STATION_OR_VISIT``."""

    def test_wraps_and_restores_add_map_icon(self) -> None:
        from open_prime_rando.echoes.pickups import pickup_editing

        original = pickup_editing._add_map_icon
        with item_map_dots_patch.pickup_icon_visibility_installed():
            self.assertIsNot(pickup_editing._add_map_icon, original)
        self.assertIs(pickup_editing._add_map_icon, original)

    def test_restores_even_on_exception(self) -> None:
        from open_prime_rando.echoes.pickups import pickup_editing

        original = pickup_editing._add_map_icon
        with self.assertRaises(RuntimeError):
            with item_map_dots_patch.pickup_icon_visibility_installed():
                raise RuntimeError("boom")
        self.assertIs(pickup_editing._add_map_icon, original)

    def test_sets_appended_icons_to_map_station_or_visit(self) -> None:
        # The stub "original" reproduces the one side effect the wrapper
        # relies on (appending to area.mapa.mappable_objects), with OPR's
        # own hardcoded value, so the assertion proves the wrapper changed it.
        from open_prime_rando.echoes.pickups import pickup_editing
        from retro_data_structures.formats.mapa import ObjectVisibility

        class _FakeMappable:
            def __init__(self) -> None:
                self.visibility_mode = ObjectVisibility.AreaVisitOrMapStation

        class _FakeMapa:
            def __init__(self) -> None:
                self.mappable_objects: list[_FakeMappable] = [_FakeMappable()]

        class _FakeArea:
            def __init__(self) -> None:
                self.mapa = _FakeMapa()

        area = _FakeArea()

        def _stub_original_add_map_icon(editor, mlvl, area, instances) -> None:
            area.mapa.mappable_objects.append(_FakeMappable())

        original = pickup_editing._add_map_icon
        pickup_editing._add_map_icon = _stub_original_add_map_icon
        try:
            with item_map_dots_patch.pickup_icon_visibility_installed():
                pickup_editing._add_map_icon("editor", "mlvl", area, "instances")
        finally:
            pickup_editing._add_map_icon = original

        existing, added = area.mapa.mappable_objects
        self.assertEqual(int(added.visibility_mode), item_map_dots_patch.MAP_STATION_OR_VISIT)
        self.assertEqual(existing.visibility_mode, ObjectVisibility.AreaVisitOrMapStation, "existing icon untouched")

    def test_opr_still_adds_pickup_icons_the_way_this_patch_expects(self) -> None:
        # The cave keys on OPR's custom type and the dot texture's name; a
        # newer OPR changing either would silently stop the dots drawing.
        import inspect

        from open_prime_rando.echoes import patcher
        from open_prime_rando.echoes.pickups import pickup_editing

        self.assertIn("object_type=0x12", inspect.getsource(pickup_editing._add_map_icon))
        self.assertIn(
            f'"{item_map_dots_patch.PICKUP_ICON_TEXTURE}"', inspect.getsource(patcher.add_pickup_map_icon)
        )


class _ItemMapDotsOptionTest(MP2TestBase):
    """Like spring ball, item map dots has no field in OPR's
    ``RandoConfiguration``, so it travels in options.json, where
    ``patcher_runner.patch_iso_with_ap`` reads it back from."""

    expected: bool

    def test_lands_in_options_json(self) -> None:
        if type(self) is _ItemMapDotsOptionTest:
            self.skipTest("base class")
        with tempfile.TemporaryDirectory() as output_directory:
            self.world.generate_output(output_directory)
            (container_path,) = pathlib.Path(output_directory).glob("*.apmp2")
            with zipfile.ZipFile(container_path) as container:
                options = json.loads(container.read("options.json"))
                config = json.loads(container.read("config.json"))
        self.assertNotIn("item_map_dots", config)
        self.assertEqual(options["item_map_dots"], self.expected)


class TestItemMapDotsDefault(_ItemMapDotsOptionTest):
    expected = True


class TestItemMapDotsOff(_ItemMapDotsOptionTest):
    options = {"item_map_dots": False}
    expected = False
