"""Tests for spring ball (``client/spring_ball_patch.py``): the code
cave's layout once ``CodeCaveTracker`` has placed it, the PPC encoding
pitfalls they have to avoid, the hook-site guard, and the options' route
from the YAML into the ``.apmp2``'s options.json.

The in-game half can only be checked against a real ISO (see
``metroidprime2/tools/find_spring_ball_addresses.py``); what's locked down
here is everything that can drift silently.
"""

from __future__ import annotations

import importlib.util
import json
import pathlib
import struct
import tempfile
import unittest
import zipfile
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from ..client import spring_ball_patch, versions
from ..options import SpringBallButton
from .bases import MP2TestBase

_OPR_AVAILABLE = importlib.util.find_spec("open_prime_rando") is not None
_PPC_ASM_AVAILABLE = importlib.util.find_spec("ppc_asm") is not None

_MEMORY_BASE = 0x80000000
_MEMORY_SIZE = 0x400000


class _FakeDol:
    """The slice of ``ppc_asm``'s ``DolEditor`` that ``CodeCaveTracker``
    and ``apply_dol_patches`` use, over a flat buffer of the DOL's address
    range."""

    def __init__(self) -> None:
        self.memory = bytearray(_MEMORY_SIZE)
        self.symbols: dict[str, int] = {}

    def resolve_symbol(self, address_or_symbol: int | str) -> int:
        if isinstance(address_or_symbol, str):
            return self.symbols[address_or_symbol]
        return address_or_symbol

    def read(self, address: int, size: int) -> bytes:
        offset = address - _MEMORY_BASE
        return bytes(self.memory[offset : offset + size])

    def write(self, address_or_symbol: int | str, data: bytes) -> None:
        offset = self.resolve_symbol(address_or_symbol) - _MEMORY_BASE
        data = bytes(data)
        self.memory[offset : offset + len(data)] = data

    def write_instructions(self, address_or_symbol: int | str, instructions: Sequence[Any]) -> None:
        from ppc_asm import assembler

        address = self.resolve_symbol(address_or_symbol)
        self.write(address, bytes(assembler.assemble_instructions(address, instructions, symbols=self.symbols)))

    def word(self, address: int) -> int:
        return struct.unpack(">I", self.read(address, 4))[0]


def _branch_target(address: int, word: int) -> int:
    if (word >> 26) == 18:
        displacement = word & 0x03FFFFFC
        if displacement & 0x02000000:
            displacement -= 0x04000000
    else:
        displacement = word & 0xFFFC
        if displacement & 0x8000:
            displacement -= 0x10000
    return (address + displacement) & 0xFFFFFFFF


def _words(instructions: Sequence[Any], address: int = 0x80100000) -> list[int]:
    from ppc_asm import assembler

    data = bytes(assembler.assemble_instructions(address, instructions, symbols={}))
    return [word[0] for word in struct.iter_unpack(">I", data)]


def _cave(version: versions.EchoesVersionInfo, button: str) -> list[Any]:
    return spring_ball_patch.build_cave(version.spring_ball, spring_ball_patch.BUTTONS[button])


def _write_vanilla_hook_site(dol: _FakeDol, addresses: versions.SpringBallAddresses) -> None:
    from ppc_asm.assembler import ppc

    site = addresses.boost_ball_argument_setup
    for index, word in enumerate(spring_ball_patch.HOOK_SITE_WORDS):
        dol.write(site + 4 * index, struct.pack(">I", word))
    call = site + 4 * len(spring_ball_patch.HOOK_SITE_WORDS)
    dol.write_instructions(call, [ppc.bl(addresses.compute_boost_ball_movement)])


@dataclass(frozen=True)
class _Placed:
    dol: _FakeDol
    cave: int
    size: int


# The free space open-prime-rando registers for Echoes, in the NTSC
# layout: CMapWorldInfo::IsAnythingSet after its new `li r3, 1; blr`, the
# error handler's controller-combo wait loop, and the original
# kInventorySlotToItemType table.
_OPR_FREE_SPACE = ((0x8010F08C, 0xB4), (0x8028C4BC, 0x14C), (0x803A7A7C, 0x35 * 4))
_LARGEST_FREE_REGION = max(length for _, length in _OPR_FREE_SPACE)


@unittest.skipUnless(_OPR_AVAILABLE and _PPC_ASM_AVAILABLE, "open-prime-rando is not installed")
class TestCavePlacement(unittest.TestCase):
    """Runs the real ``CodeCaveTracker`` over open-prime-rando's free space,
    competing with every other cave request an Echoes patch makes (its own,
    plus warp-to-start), then walks the result."""

    def _place(self, version: versions.EchoesVersionInfo, button: str) -> _Placed:
        from open_prime_rando.dol_patching.code_cave_tracker import CodeCaveTracker
        from ppc_asm import assembler
        from ppc_asm.assembler import ppc

        from ..client import warp_patch

        addresses = version.spring_ball
        dol = _FakeDol()
        _write_vanilla_hook_site(dol, addresses)
        cave = CodeCaveTracker(dol)  # type: ignore[arg-type]
        for start, length in _OPR_FREE_SPACE:
            cave.add_empty_space(start, length=length)
        # open-prime-rando's own requests: the new inventory slot table, the
        # "Locations: %d/N" format string, Massive Damage's cave.
        cave.request_data_cave(bytes(0x35), 1, lambda _: None)
        cave.request_data_cave(b"%d/100\x00", 1, lambda _: None)
        cave.request_code_cave([ppc.nop()] * 11, lambda _: None)
        warp_patch.apply_dol_patches(cave, version.warp_to_start)
        spring_ball_patch.apply_dol_patches(cave, addresses, button)
        cave.fulfill_requests()

        site = addresses.boost_ball_argument_setup
        hook = dol.word(site)
        self.assertEqual(hook & 0xFC000003, 0x48000001, "hook must be a bl")
        return _Placed(
            dol=dol,
            cave=_branch_target(site, hook),
            size=assembler.byte_count(_cave(version, button)),
        )

    def test_every_version_and_button_places(self) -> None:
        for version in versions.VERSIONS:
            for button in spring_ball_patch.BUTTONS:
                with self.subTest(version=version.name, button=button):
                    self._place(version, button)

    def test_rest_of_the_call_sequence_is_untouched(self) -> None:
        for version in versions.VERSIONS:
            with self.subTest(version.name):
                placed = self._place(version, "c_stick_up")
                site = version.spring_ball.boost_ball_argument_setup
                for index, word in enumerate(spring_ball_patch.HOOK_SITE_WORDS[1:], start=1):
                    self.assertEqual(placed.dol.word(site + 4 * index), word)
                call = site + 4 * len(spring_ball_patch.HOOK_SITE_WORDS)
                self.assertEqual(
                    _branch_target(call, placed.dol.word(call)), version.spring_ball.compute_boost_ball_movement
                )

    def test_branches_stay_inside_the_cave(self) -> None:
        for version in versions.VERSIONS:
            for button in spring_ball_patch.BUTTONS:
                with self.subTest(version=version.name, button=button):
                    placed = self._place(version, button)
                    end = placed.cave + placed.size
                    for address in range(placed.cave, end - 4, 4):
                        word = placed.dol.word(address)
                        if (word >> 26) == 16 or ((word >> 26) == 18 and not word & 1):
                            self.assertTrue(placed.cave <= _branch_target(address, word) < end, hex(address))

    def test_ends_with_the_replaced_instruction_and_returns(self) -> None:
        placed = self._place(versions.NTSC, "c_stick_up")
        end = placed.cave + placed.size
        self.assertEqual(placed.dol.word(end - 12), spring_ball_patch.HOOK_SITE_WORDS[0])  # fmr f1, f31
        self.assertEqual(placed.dol.word(end - 8), 0x4E800020)  # blr
        self.assertEqual(placed.dol.word(end - 4), 0, "the cooldown word starts at 0")

    def test_loads_its_own_cooldown_word(self) -> None:
        placed = self._place(versions.NTSC, "c_stick_up")
        cooldown = placed.cave + placed.size - 4
        lis, ori = placed.dol.word(placed.cave + 0x14), placed.dol.word(placed.cave + 0x18)
        self.assertEqual(lis, 0x3F600000 | (cooldown >> 16))  # lis r27, hi
        self.assertEqual(ori, 0x637B0000 | (cooldown & 0xFFFF))  # ori r27, r27, lo


@unittest.skipUnless(_PPC_ASM_AVAILABLE, "ppc_asm is not installed")
class TestEncoding(unittest.TestCase):
    """The first two tests guard pitfalls that shipped in the first draft and
    were only caught by disassembling a patched DOL."""

    def _all_caves(self) -> list[list[int]]:
        # The trailing cooldown data word is skipped.
        return [_words(_cave(v, button))[:-1] for v in versions.VERSIONS for button in spring_ball_patch.BUTTONS]

    def test_cooldown_decrement_is_arithmetic(self) -> None:
        # `addi r0, r0, -1` assembles to `li r0, -1` (r0 as a base register
        # reads as 0), which pins the cooldown at -1 instead of counting
        # down. The decrement must use a real base register.
        for words in self._all_caves():
            decrements = [word for word in words if (word >> 26) == 14 and (word & 0xFFFF) == 0xFFFF]
            self.assertEqual(len(decrements), 1)
            rd, ra = (decrements[0] >> 21) & 0x1F, (decrements[0] >> 16) & 0x1F
            self.assertEqual(rd, ra)
            self.assertNotEqual(ra, 0)

    def test_rlwinm_is_in_place(self) -> None:
        # ppc_asm's rlwinm(out, in) encodes `in` as the destination.
        for words in self._all_caves():
            for word in words:
                if (word >> 26) == 21:
                    self.assertEqual((word >> 21) & 0x1F, (word >> 16) & 0x1F, f"{word:08x}")

    def test_raw_encodings(self) -> None:
        self.assertEqual(_words([spring_ball_patch._or_dot(0, 12)]), [0x7C006379])  # or. r0, r0, r12
        self.assertEqual(_words([spring_ball_patch._xori(12, 0xFFFF)]), [0x698CFFFF])  # xori r12, r12, 0xffff
        self.assertEqual(_words([spring_ball_patch._andi_dot(0, 0x10)]), [0x70000010])  # andi. r0, r0, 0x10

    def test_fits_the_largest_free_region(self) -> None:
        from ppc_asm import assembler

        for version in versions.VERSIONS:
            for button in spring_ball_patch.BUTTONS:
                with self.subTest(version=version.name, button=button):
                    self.assertLessEqual(assembler.byte_count(_cave(version, button)), _LARGEST_FREE_REGION)

    def test_button_checks(self) -> None:
        from ppc_asm.assembler import ppc

        def check(button: str) -> list[int]:
            done = ppc.nop().with_label("_done")
            return _words([*spring_ball_patch._button_check(spring_ball_patch.BUTTONS[button]), done])

        up = check("c_stick_up")
        self.assertEqual(up[0], 0x801E0014)  # lwz r0, 0x14(r30)
        self.assertEqual(up[1:3], [0x3D803F33, 0x618C3333])  # r12 = 0.7f
        down = check("c_stick_down")
        self.assertEqual(down[1], 0x6C008000)  # xoris r0, r0, 0x8000
        d_pad = check("d_pad_up")
        self.assertEqual(d_pad[:2], [0x881E0029, 0x70000010])  # lbz r0, 0x29(r30); andi. r0, r0, 0x10
        l_trigger = check("l_trigger")
        self.assertEqual(l_trigger[1], 0x70000040)


@unittest.skipUnless(_OPR_AVAILABLE and _PPC_ASM_AVAILABLE, "open-prime-rando is not installed")
class TestApplyGuards(unittest.TestCase):
    def test_refuses_an_unexpected_hook_site(self) -> None:
        from open_prime_rando.dol_patching.code_cave_tracker import CodeCaveTracker

        addresses = versions.NTSC.spring_ball
        for broken_index in range(len(spring_ball_patch.HOOK_SITE_WORDS) + 1):
            with self.subTest(broken_index=broken_index):
                dol = _FakeDol()
                _write_vanilla_hook_site(dol, addresses)
                dol.write(addresses.boost_ball_argument_setup + 4 * broken_index, bytes(4))
                before = bytes(dol.memory)
                with self.assertRaises(ValueError):
                    spring_ball_patch.apply_dol_patches(CodeCaveTracker(dol), addresses, "c_stick_up")  # type: ignore[arg-type]
                self.assertEqual(bytes(dol.memory), before, "nothing may be written")

    def test_refuses_an_unknown_button(self) -> None:
        from open_prime_rando.dol_patching.code_cave_tracker import CodeCaveTracker

        addresses = versions.NTSC.spring_ball
        dol = _FakeDol()
        _write_vanilla_hook_site(dol, addresses)
        with self.assertRaises(ValueError):
            spring_ball_patch.apply_dol_patches(CodeCaveTracker(dol), addresses, "z")  # type: ignore[arg-type]


class TestButtonsMatchOption(unittest.TestCase):
    def test_every_option_has_a_button(self) -> None:
        option_keys = {key for key in SpringBallButton.options if key not in SpringBallButton.aliases}
        self.assertEqual(option_keys, set(spring_ball_patch.BUTTONS))


@unittest.skipUnless(_OPR_AVAILABLE, "open-prime-rando is not installed")
class TestInstallSpringBall(unittest.TestCase):
    def test_rejects_builds_without_known_addresses(self) -> None:
        from open_prime_rando.echoes.version import EchoesVersion

        from ..client.patcher_runner import install_spring_ball

        @dataclass(frozen=True)
        class FakeDolVersion:
            echoes_version: object
            description: str = "Fake"

        for echoes_version in (EchoesVersion.NTSC_J, EchoesVersion.TRILOGY_NTSC):
            with self.subTest(echoes_version.name), self.assertRaises(ValueError):
                install_spring_ball(object(), FakeDolVersion(echoes_version), "c_stick_up")


class _SpringBallOptionTest(MP2TestBase):
    """Like warp-to-start, spring ball has no field in OPR's
    ``RandoConfiguration``, so it travels in options.json, where
    ``patcher_runner.patch_iso_with_ap`` reads it back from."""

    expected: tuple[bool, str]

    def test_lands_in_options_json(self) -> None:
        if type(self) is _SpringBallOptionTest:
            self.skipTest("base class")
        with tempfile.TemporaryDirectory() as output_directory:
            self.world.generate_output(output_directory)
            (container_path,) = pathlib.Path(output_directory).glob("*.apmp2")
            with zipfile.ZipFile(container_path) as container:
                options = json.loads(container.read("options.json"))
                config = json.loads(container.read("config.json"))
        self.assertNotIn("spring_ball", config)
        self.assertEqual((options["spring_ball"], options["spring_ball_button"]), self.expected)


class TestSpringBallDefault(_SpringBallOptionTest):
    expected = (False, "c_stick_up")


class TestSpringBallEnabled(_SpringBallOptionTest):
    options = {"spring_ball": True, "spring_ball_button": "d_pad_up"}
    expected = (True, "d_pad_up")
