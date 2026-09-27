"""Tests for spring ball (``client/spring_ball_patch.py``): the two code
caves' layout once ``CodeCaveTracker`` has placed them, the PPC encoding
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
    """Assembles one cave on its own, with the other cave's symbols
    pointing somewhere nearby."""
    from ppc_asm import assembler

    symbols = dict.fromkeys(
        (spring_ball_patch.BODY_SYMBOL, spring_ball_patch.DONE_SYMBOL, spring_ball_patch.COOLDOWNS_SYMBOL),
        address + 0x1000,
    )
    data = bytes(assembler.assemble_instructions(address, instructions, symbols=symbols))
    return [word[0] for word in struct.iter_unpack(">I", data)]


@dataclass(frozen=True)
class _Placed:
    dol: _FakeDol
    entry: int
    entry_size: int
    body: int
    body_size: int


# The free space open-prime-rando registers for Echoes, in the NTSC
# layout: CMapWorldInfo::IsAnythingSet after its new `li r3, 1; blr`, the
# error handler's controller-combo wait loop, and the original
# kInventorySlotToItemType table.
_OPR_FREE_SPACE = ((0x8010F08C, 0xB4), (0x8028C4BC, 0x14C), (0x803A7A7C, 0x35 * 4))


@unittest.skipUnless(_OPR_AVAILABLE and _PPC_ASM_AVAILABLE, "open-prime-rando is not installed")
class TestCavePlacement(unittest.TestCase):
    """Runs the real ``CodeCaveTracker`` over open-prime-rando's free space,
    competing with every other cave request an Echoes patch makes (its own,
    plus warp-to-start), then walks the result."""

    def _place(self, version: versions.EchoesVersionInfo, button: str) -> _Placed:
        from open_prime_rando.dol_patching.code_cave_tracker import CodeCaveTracker
        from ppc_asm.assembler import ppc

        from ..client import warp_patch

        addresses = version.spring_ball
        dol = _FakeDol()
        dol.write_instructions(addresses.boost_ball_movement_call, [ppc.bl(addresses.compute_boost_ball_movement)])
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

        hook = dol.word(addresses.boost_ball_movement_call)
        self.assertEqual(hook & 0xFC000003, 0x48000001, "hook must be a bl")
        body = dol.symbols[spring_ball_patch.BODY_SYMBOL]
        from ppc_asm import assembler

        return _Placed(
            dol=dol,
            entry=_branch_target(addresses.boost_ball_movement_call, hook),
            entry_size=assembler.byte_count(spring_ball_patch.build_entry_cave(spring_ball_patch.BUTTONS[button])),
            body=body,
            body_size=assembler.byte_count(spring_ball_patch.build_body_cave(addresses)),
        )

    def test_every_version_and_button_places(self) -> None:
        for version in versions.VERSIONS:
            for button in spring_ball_patch.BUTTONS:
                with self.subTest(version=version.name, button=button):
                    self._place(version, button)

    def test_entry_exits_only_through_its_trampolines(self) -> None:
        # Conditional branches reach +-32 KiB and the body can be megabytes
        # away, so every one of them must stay inside the entry cave; the
        # last two instructions are the unconditional hops into the body.
        for version in versions.VERSIONS:
            for button in spring_ball_patch.BUTTONS:
                with self.subTest(version=version.name, button=button):
                    placed = self._place(version, button)
                    end = placed.entry + placed.entry_size
                    for address in range(placed.entry, end, 4):
                        word = placed.dol.word(address)
                        if (word >> 26) == 16:
                            self.assertTrue(placed.entry <= _branch_target(address, word) < end, hex(address))
                    into_body = placed.dol.word(end - 8)
                    to_done = placed.dol.word(end - 4)
                    self.assertEqual(_branch_target(end - 8, into_body), placed.body)
                    self.assertEqual(
                        _branch_target(end - 4, to_done),
                        placed.dol.symbols[spring_ball_patch.DONE_SYMBOL],
                    )

    def test_body_tail_branches_into_the_hooked_function(self) -> None:
        for version in versions.VERSIONS:
            with self.subTest(version.name):
                placed = self._place(version, "c_stick_up")
                data = placed.dol.symbols[spring_ball_patch.COOLDOWNS_SYMBOL]
                tail = placed.dol.word(data - 4)
                self.assertEqual(tail & 0xFC000003, 0x48000000, "must be a plain b")
                self.assertEqual(_branch_target(data - 4, tail), version.spring_ball.compute_boost_ball_movement)

    def test_data_words(self) -> None:
        placed = self._place(versions.NTSC, "c_stick_up")
        data = placed.dol.symbols[spring_ball_patch.COOLDOWNS_SYMBOL]
        self.assertEqual(placed.dol.read(data, 16), bytes(16), "one zeroed cooldown per controller")
        self.assertEqual(struct.unpack(">f", placed.dol.read(data + 16, 4))[0], spring_ball_patch.HALF_PIPE_DIVISOR)
        self.assertEqual(data + 20, placed.body + placed.body_size)

    def test_entry_loads_the_cooldown_array(self) -> None:
        placed = self._place(versions.NTSC, "c_stick_up")
        data = placed.dol.symbols[spring_ball_patch.COOLDOWNS_SYMBOL]
        lis, ori = placed.dol.word(placed.entry + 0x24), placed.dol.word(placed.entry + 0x28)
        self.assertEqual(lis, 0x3F600000 | (data >> 16))  # lis r27, hi
        self.assertEqual(ori, 0x637B0000 | (data & 0xFFFF))  # ori r27, r27, lo


@unittest.skipUnless(_PPC_ASM_AVAILABLE, "ppc_asm is not installed")
class TestEncodingPitfalls(unittest.TestCase):
    """Both of these shipped in the first draft and were only caught by
    disassembling a patched DOL."""

    def _all_caves(self) -> list[list[int]]:
        # The body's five trailing data words are skipped: 1.5f happens to
        # decode as `lis r30, 0`.
        caves = [_words(spring_ball_patch.build_body_cave(v.spring_ball))[:-5] for v in versions.VERSIONS]
        caves += [_words(spring_ball_patch.build_entry_cave(button)) for button in spring_ball_patch.BUTTONS.values()]
        return caves

    def test_cooldown_decrement_is_arithmetic(self) -> None:
        # `addi r0, r0, -1` assembles to `li r0, -1` (r0 as a base register
        # reads as 0), which pins the cooldown at -1 instead of counting
        # down. The decrement must use a real base register.
        for name, button in spring_ball_patch.BUTTONS.items():
            with self.subTest(name):
                decrements = [
                    word
                    for word in _words(spring_ball_patch.build_entry_cave(button))
                    if (word >> 26) == 14 and (word & 0xFFFF) == 0xFFFF
                ]
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

    def test_body_is_placed_before_entry(self) -> None:
        from ppc_asm import assembler

        for version in versions.VERSIONS:
            body = assembler.byte_count(spring_ball_patch.build_body_cave(version.spring_ball))
            for name, button in spring_ball_patch.BUTTONS.items():
                with self.subTest(version=version.name, button=name):
                    entry = assembler.byte_count(spring_ball_patch.build_entry_cave(button))
                    self.assertGreater(body, entry)

    def test_button_checks(self) -> None:
        entry_done = spring_ball_patch.build_entry_cave(spring_ball_patch.BUTTONS["c_stick_up"])[-1]

        def check(button: str) -> list[int]:
            # _button_check branches to the entry cave's trampoline label.
            return _words([*spring_ball_patch._button_check(spring_ball_patch.BUTTONS[button]), entry_done])

        up = check("c_stick_up")
        self.assertEqual(up[0], 0x801E0014)  # lwz r0, 0x14(r30)
        self.assertEqual(up[1:3], [0x3D803F33, 0x618C3333])  # r12 = 0.7f
        down = check("c_stick_down")
        self.assertEqual(down[1], 0x6C008000)  # xoris r0, r0, 0x8000
        d_pad = check("d_pad_up")
        self.assertEqual(d_pad[:2], [0x881E0029, 0x70000010])  # lbz r0, 0x29(r30); andi. r0, r0, 0x10
        l_trigger = check("l_trigger")
        self.assertEqual(l_trigger[1], 0x70000040)


@unittest.skipUnless(_PPC_ASM_AVAILABLE, "ppc_asm is not installed")
class TestApplyGuards(unittest.TestCase):
    def test_refuses_an_unexpected_hook_site(self) -> None:
        from open_prime_rando.dol_patching.code_cave_tracker import CodeCaveTracker

        dol = _FakeDol()  # hook site is all zeroes
        with self.assertRaises(ValueError):
            spring_ball_patch.apply_dol_patches(CodeCaveTracker(dol), versions.NTSC.spring_ball, "c_stick_up")  # type: ignore[arg-type]
        self.assertEqual(dol.memory, bytearray(_MEMORY_SIZE), "nothing may be written")

    def test_refuses_an_unknown_button(self) -> None:
        from open_prime_rando.dol_patching.code_cave_tracker import CodeCaveTracker
        from ppc_asm.assembler import ppc

        addresses = versions.NTSC.spring_ball
        dol = _FakeDol()
        dol.write_instructions(addresses.boost_ball_movement_call, [ppc.bl(addresses.compute_boost_ball_movement)])
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
