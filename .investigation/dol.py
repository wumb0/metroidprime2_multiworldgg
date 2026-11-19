"""Echoes DOL reverse-engineering helpers: capstone disasm + xref search.

Parsing/reads come from ppc_asm's DolFile; this adds only what it lacks:
disassembly and address scans.
"""
from __future__ import annotations

import struct
from pathlib import Path

from capstone import CS_ARCH_PPC, CS_MODE_32, CS_MODE_BIG_ENDIAN, Cs
from ppc_asm.dol_file import DolFile, DolHeader

NTSC_DOL = Path("/Users/wumb0/Projects/prime2mwgg/.investigation/main.dol")
PAL_DOL = Path("/Users/wumb0/Projects/prime2mwgg/.investigation/main_pal.dol")


class _Symbols:
    """Known function names; add entries as the investigation names them."""

    TABLE: dict[int, str] = {
        0x80184118: "CPlayer::EnterMorphBallState",
        0x80085314: "CPlayer::StartTransitionToVisor",
        0x80085334: "CPlayer::ResetVisor",
    }

    def name(self, addr: int) -> str:
        return self.TABLE.get(addr, "?")


SYM = _Symbols()


class Dol:
    def __init__(self, path: Path = NTSC_DOL):
        self._buf = path.read_bytes()
        header = DolHeader.from_bytes(self._buf[:0x100])
        self.text_start = 0x80003100
        # (memory addr, buffer offset, size) for every loaded section
        self._segments = [
            (sec.base_address, sec.offset, sec.size) for sec in header.sections if sec.size and sec.offset
        ]
        self._segments.sort()
        self._cs = Cs(CS_ARCH_PPC, CS_MODE_32 | CS_MODE_BIG_ENDIAN)

    def read(self, addr: int, n: int) -> bytes:
        for a, off, size in self._segments:
            if a <= addr and addr + n <= a + size:
                return self._buf[off + (addr - a) : off + (addr - a) + n]
        raise ValueError(f"read {addr:#x}+{n:#x} outside DOL")

    def disasm(self, addr: int, count: int = 40) -> list[str]:
        raw = self.read(addr, count * 4)
        out = []
        for ins in self._cs.disasm(raw, addr):
            comment = ""
            if ins.mnemonic in ("bl", "b") and ins.op_str.startswith("0x"):
                comment = f"  ; {SYM.name(int(ins.op_str, 16))}"
            out.append(f"{ins.address:08x}  {ins.mnemonic:<8} {ins.op_str}{comment}")
        return out

    def show(self, addr: int, count: int = 40) -> None:
        print("\n".join(self.disasm(addr, count)))

    def find_calls_to(self, target: int) -> list[int]:
        """All `bl target` instruction addresses (plain bl encoding only)."""
        hits = []
        for a, off, size in self._segments:
            chunk = bytes(self._buf[off : off + size])
            for i in range(0, len(chunk) - 3, 4):
                w = struct.unpack(">I", chunk[i : i + 4])[0]
                if w & 0xFC000003 == 0x48000001:  # bl (no link-edit, absolute)
                    delta = w & 0x03FFFFFC
                    if w & 0x02000000:
                        delta -= 0x04000000
                    if a + i + delta == target:
                        hits.append(a + i)
        return hits

    def find_words(self, value: int) -> list[int]:
        needle = struct.pack(">I", value)
        hits = []
        for a, off, size in self._segments:
            chunk = bytes(self._buf[off : off + size])
            pos = 0
            while (pos := chunk.find(needle, pos)) != -1:
                if pos % 4 == 0:
                    hits.append(a + pos)
                pos += 4
        return hits

    def find_bytes(self, pattern: bytes) -> list[int]:
        hits = []
        for a, off, size in self._segments:
            chunk = bytes(self._buf[off : off + size])
            pos = 0
            while (pos := chunk.find(pattern, pos)) != -1:
                hits.append(a + pos)
                pos += 1
        return hits


D = Dol()
