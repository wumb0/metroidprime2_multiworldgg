"""Tests for the base damage multipliers (``client/damage_multiplier_patch.py``):
the encoded factor, the caves' layout once ``CodeCaveTracker`` has placed them
next to every other cave an Echoes patch asks for, the hook-site guards, and
the options' route from the YAML into the ``.apmp2``'s options.json.

Whether the numbers come out right in game can't be checked here; what is
locked down is everything that can drift silently, plus a hand-assembled
reference for each cave.
"""

from __future__ import annotations

import importlib.util
import json
import pathlib
import struct
import tempfile
import unittest
import zipfile

from ..client import damage_multiplier_patch as patch
from ..client import spring_ball_patch, versions, warp_patch
from .bases import MP2TestBase
from .test_spring_ball_patch import _OPR_FREE_SPACE, _branch_target, _FakeDol

_OPR_AVAILABLE = importlib.util.find_spec("open_prime_rando") is not None
_PPC_ASM_AVAILABLE = importlib.util.find_spec("ppc_asm") is not None


def _write_vanilla_sites(dol: _FakeDol, addresses: versions.DamageMultiplierAddresses) -> None:
    dol.write(addresses.local_damage_hook - 4, struct.pack(">3I", *patch.LOCAL_DAMAGE_HOOK_WORDS))
    dol.write(
        addresses.double_damage_epilogue_hook - 4, struct.pack(">3I", *patch.APPLY_DOUBLE_DAMAGE_HOOK_WORDS)
    )


class TestMultiplierBits(unittest.TestCase):
    def test_encodes_a_single_precision_float(self) -> None:
        for percent, bits in ((100, 0x3F800000), (200, 0x40000000), (50, 0x3F000000), (150, 0x3FC00000)):
            with self.subTest(percent=percent):
                self.assertEqual(bits, patch.multiplier_bits(percent))

    def test_rejects_out_of_range(self) -> None:
        for percent in (0, -5, patch.MAX_PERCENT + 1):
            with self.subTest(percent=percent), self.assertRaises(ValueError):
                patch.multiplier_bits(percent)


class TestAddresses(unittest.TestCase):
    def test_pal_sits_a_fixed_distance_after_ntsc(self) -> None:
        ntsc, pal = versions.NTSC.damage_multiplier, versions.PAL.damage_multiplier
        # ApplyLocalDamage and ApplyDoubleDamage moved by different amounts, but
        # every instruction inside each is at the same offset on both.
        self.assertEqual(0x150, pal.local_damage_hook - ntsc.local_damage_hook)
        self.assertEqual(0x300, pal.double_damage_epilogue_hook - ntsc.double_damage_epilogue_hook)

    def test_hook_site_words_are_the_documented_instructions(self) -> None:
        self.assertEqual(0xA0140000, patch.LOCAL_DAMAGE_HOOK_WORDS[1])  # lhz r0, 0(r20)
        self.assertEqual(0x80010014, patch.APPLY_DOUBLE_DAMAGE_HOOK_WORDS[1])  # lwz r0, 0x14(r1)


@unittest.skipUnless(_PPC_ASM_AVAILABLE, "ppc_asm is not installed")
class TestCaves(unittest.TestCase):
    def _words(self, instructions: list, address: int = 0x80300000) -> list[int]:
        from ppc_asm import assembler

        data = bytes(assembler.assemble_instructions(address, instructions, symbols={}))
        return [word for (word,) in struct.iter_unpack(">I", data)]

    def test_incoming_cave_for_a_float_with_a_low_half(self) -> None:
        # 150% = 0x3FC00000 (no low half); 125% = 0x3FA00000; 130% has one.
        words = self._words(patch.build_incoming_cave(130, 0x8003DA18))
        bits = patch.multiplier_bits(130)
        self.assertEqual(0x3C000000 | (bits >> 16), words[0])  # lis r0, hi
        self.assertEqual(0x60000000 | (bits & 0xFFFF), words[1])  # ori r0, r0, lo
        self.assertEqual(0x9001FFF8, words[2])  # stw r0, -8(r1)
        self.assertEqual(0xC001FFF8, words[3])  # lfs f0, -8(r1)
        self.assertEqual(0xEFBD0032, words[4])  # fmuls f29, f29, f0
        self.assertEqual(0xA0140000, words[5])  # lhz r0, 0(r20): the instruction the hook replaced
        self.assertEqual(0x8003DA18, _branch_target(0x80300000 + 4 * 6, words[6]))
        self.assertEqual(7, len(words))

    def test_incoming_cave_skips_the_ori_when_the_low_half_is_zero(self) -> None:
        words = self._words(patch.build_incoming_cave(200, 0x8003DA18))
        self.assertEqual(0x3C004000, words[0])  # lis r0, 0x4000
        self.assertEqual(0x9001FFF8, words[1])  # stw: no ori in between

    def test_outgoing_cave_scales_exactly_damage_radius_damage_and_knockback(self) -> None:
        words = self._words(patch.build_outgoing_cave(200, 0x8018A174))
        # lis; stw; lfs f0; then three (lfs f1, fmuls, stfs) triples on r30.
        self.assertEqual(0xC03E0004, words[3])  # lfs f1, 4(r30)
        self.assertEqual(0xEC210032, words[4])  # fmuls f1, f1, f0
        self.assertEqual(0xD03E0004, words[5])  # stfs f1, 4(r30)
        self.assertEqual(0xC03E0008, words[6])
        self.assertEqual(0xD03E0008, words[8])
        self.assertEqual(0xC03E0010, words[9])
        self.assertEqual(0xD03E0010, words[11])
        self.assertEqual(0x80010014, words[12])  # lwz r0, 0x14(r1): the replaced epilogue instruction
        self.assertEqual(0x8018A174, _branch_target(0x80300000 + 4 * 13, words[13]))
        self.assertEqual(14, len(words))


@unittest.skipUnless(_OPR_AVAILABLE and _PPC_ASM_AVAILABLE, "open-prime-rando is not installed")
class TestPlacement(unittest.TestCase):
    """The real ``CodeCaveTracker`` over open-prime-rando's free space, with
    every other cave a full patch asks for competing."""

    def _place(self, version: versions.EchoesVersionInfo, **percent: int) -> tuple[_FakeDol, list[int]]:
        from open_prime_rando.dol_patching.code_cave_tracker import CodeCaveTracker
        from ppc_asm.assembler import ppc

        addresses = version.damage_multiplier
        dol = _FakeDol()
        _write_vanilla_sites(dol, addresses)
        cave = CodeCaveTracker(dol)  # type: ignore[arg-type]
        for start, length in _OPR_FREE_SPACE:
            cave.add_empty_space(start, length=length)
        cave.request_data_cave(bytes(0x35), 1, lambda _: None)
        cave.request_data_cave(b"%d/100\x00", 1, lambda _: None)
        cave.request_code_cave([ppc.nop()] * 11, lambda _: None)
        warp_patch.apply_dol_patches(cave, version.warp_to_start)
        # Spring ball is applied with its hook site vanilla, as in test_spring_ball_patch.
        from .test_spring_ball_patch import _write_vanilla_hook_site

        _write_vanilla_hook_site(dol, version.spring_ball)
        spring_ball_patch.apply_dol_patches(cave, version.spring_ball, "c_stick_up")
        patch.apply_dol_patches(
            cave,
            addresses,
            incoming_percent=percent.get("incoming", 100),
            outgoing_percent=percent.get("outgoing", 100),
        )
        cave.fulfill_requests()
        return dol, [
            _branch_target(addresses.local_damage_hook, dol.word(addresses.local_damage_hook)),
            _branch_target(addresses.double_damage_epilogue_hook, dol.word(addresses.double_damage_epilogue_hook)),
        ]

    def test_both_caves_fit_on_both_versions_and_hooks_are_branches(self) -> None:
        for version in versions.VERSIONS:
            with self.subTest(version.name):
                dol, targets = self._place(version, incoming=150, outgoing=50)
                for hook in (
                    version.damage_multiplier.local_damage_hook,
                    version.damage_multiplier.double_damage_epilogue_hook,
                ):
                    word = dol.word(hook)
                    self.assertEqual(0x48000000, word & 0xFC000003, "the hook must be a plain b")
                for target in targets:
                    self.assertGreaterEqual(target, 0x80003100)

    def test_a_multiplier_of_100_touches_nothing(self) -> None:
        for version in versions.VERSIONS:
            with self.subTest(version.name):
                dol, _ = self._place(version)
                for hook, words in (
                    (version.damage_multiplier.local_damage_hook, patch.LOCAL_DAMAGE_HOOK_WORDS),
                    (version.damage_multiplier.double_damage_epilogue_hook, patch.APPLY_DOUBLE_DAMAGE_HOOK_WORDS),
                ):
                    self.assertEqual(words[1], dol.word(hook))

    def test_only_the_changed_multiplier_is_patched(self) -> None:
        version = versions.NTSC
        dol, _ = self._place(version, incoming=150)
        self.assertEqual(0x48000000, dol.word(version.damage_multiplier.local_damage_hook) & 0xFC000003)
        self.assertEqual(
            patch.APPLY_DOUBLE_DAMAGE_HOOK_WORDS[1], dol.word(version.damage_multiplier.double_damage_epilogue_hook)
        )

    def test_the_cave_returns_to_the_instruction_after_the_hook(self) -> None:
        version = versions.NTSC
        dol, (incoming, outgoing) = self._place(version, incoming=150, outgoing=150)
        addresses = version.damage_multiplier
        # The last word of each cave (150% has no `ori`) is its branch back.
        for cave, hook, size in (
            (incoming, addresses.local_damage_hook, 5),
            (outgoing, addresses.double_damage_epilogue_hook, 13),
        ):
            last = cave + 4 * size
            self.assertEqual(hook + 4, _branch_target(last, dol.word(last)))


@unittest.skipUnless(_OPR_AVAILABLE and _PPC_ASM_AVAILABLE, "open-prime-rando is not installed")
class TestGuards(unittest.TestCase):
    def test_refuses_a_dol_whose_hook_sites_differ(self) -> None:
        from open_prime_rando.dol_patching.code_cave_tracker import CodeCaveTracker

        addresses = versions.NTSC.damage_multiplier
        for kwargs in ({"incoming_percent": 150}, {"outgoing_percent": 150}):
            with self.subTest(kwargs):
                dol = _FakeDol()  # all zeroes: not a vanilla DOL
                cave = CodeCaveTracker(dol)  # type: ignore[arg-type]
                with self.assertRaises(ValueError):
                    patch.apply_dol_patches(cave, addresses, **kwargs)

    def test_a_vanilla_multiplier_needs_no_dol_check(self) -> None:
        from open_prime_rando.dol_patching.code_cave_tracker import CodeCaveTracker

        patch.apply_dol_patches(CodeCaveTracker(_FakeDol()), versions.NTSC.damage_multiplier)  # type: ignore[arg-type]


class _OptionsJsonTest(MP2TestBase):
    """Neither multiplier has a field in OPR's ``RandoConfiguration``, so they
    travel in options.json, where ``patcher_runner.patch_iso_with_ap`` reads
    them."""

    expected = (100, 100)

    def test_lands_in_options_json(self) -> None:
        if type(self) is _OptionsJsonTest:
            self.skipTest("base class")
        with tempfile.TemporaryDirectory() as output_directory:
            self.world.generate_output(output_directory)
            (container_path,) = pathlib.Path(output_directory).glob("*.apmp2")
            with zipfile.ZipFile(container_path) as container:
                options = json.loads(container.read("options.json"))
                config = json.loads(container.read("config.json"))
        self.assertNotIn("incoming_damage_multiplier", config)
        self.assertNotIn("outgoing_damage_multiplier", config)
        self.assertEqual(self.expected, (options["incoming_damage_multiplier"], options["outgoing_damage_multiplier"]))


class TestMultipliersDefault(_OptionsJsonTest):
    expected = (100, 100)


class TestMultipliersSet(_OptionsJsonTest):
    options = {"incoming_damage_multiplier": 150, "outgoing_damage_multiplier": 75}
    expected = (150, 75)
