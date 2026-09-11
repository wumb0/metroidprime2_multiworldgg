"""Locates the DOL addresses the warp-to-start patch hooks, for an Echoes ISO.

The warp-to-start gate (``client/warp_patch.py``) replaces one ``bl`` in
``CScriptSpecialFunction``'s save-station Think: the branch that broadcasts
the ``ZERO`` script state when the player declines the save prompt. That
address differs between NTSC-U and PAL, so it is recovered by pattern
matching rather than hardcoded per build.

The save-station Think is unmistakable in both builds::

    lbz     rA, 0x238(rThis)        ; CScriptSpecialFunction flags
    rlwinm. r0, rA, 30, 31, 31      ; test "save prompt pending" (mask 0x04)
    beq     done
    lwz     r0, 0x2470(rMgr)        ; CStateManager pending transition
    cmpwi   r0, 5                   ; 5 == still saving
    beq     done
    ...
    lbz     r0, 0x294c(rMgr)        ; "the game was saved" flag
    rlwinm. r0, r0, 29, 31, 31
    beq     declined
    ...  SendScriptMsgs(this, 'MAXR', mgr, &editorId, -1)
    b       done
 declined:
    ...  SendScriptMsgs(this, 'ZERO', mgr, &editorId, -1)   <-- hooked

so we anchor on the ``lwz r0, 0x2470(rX)`` / ``cmpwi r0, 5`` pair, then take
the ``bl`` inside that function whose r4 was loaded with the ``ZERO`` fourcc.
The branch target of that ``bl`` is the SCLY state-broadcast helper
(``CEntity::SendScriptMsgs``-alike), which the code cave calls itself.

Usage::

    python -m metroidprime2.tools.find_warp_addresses /path/to/echoes.iso ...

Accepts ISO paths (the DOL is read out with open-prime-rando's
``IsoFileProvider``) or raw ``.dol`` files.
"""

from __future__ import annotations

import struct
import sys
from dataclasses import dataclass
from pathlib import Path

ZERO_FOURCC = 0x5A45524F
"""``State.Zero``, as Echoes stores script states at runtime."""

_FLAGS_OFFSET = 0x238
"""CScriptSpecialFunction flags byte."""

_TRANSITION_OFFSET = 0x2470
"""CStateManager field holding the pending state transition."""

_SAVE_TRANSITION = 5
"""``*(CStateManager + 0x2470)`` while the save prompt is still up."""

_BLR = 0x4E800020


@dataclass(frozen=True)
class WarpAddresses:
    decline_broadcast_call: int
    """Address of the ``bl`` that broadcasts ``ZERO`` on a declined save."""

    send_script_msgs: int
    """That ``bl``'s target: the SCLY state-broadcast helper."""

    think_start: int
    """Start of the enclosing save-station Think, for eyeballing in a
    disassembler."""


class DolText:
    """The text sections of a DOL, addressable by load address."""

    def __init__(self, data: bytes) -> None:
        offsets = struct.unpack_from(">18I", data, 0x00)
        addresses = struct.unpack_from(">18I", data, 0x48)
        sizes = struct.unpack_from(">18I", data, 0x90)
        self.sections = [
            (address, data[offset : offset + size])
            for index, (offset, address, size) in enumerate(zip(offsets, addresses, sizes, strict=True))
            if size and index < 7
        ]

    def words(self):
        """Yields (address, instruction) for every instruction in every text section."""
        for base, body in self.sections:
            for offset in range(0, len(body) - 3, 4):
                yield base + offset, struct.unpack_from(">I", body, offset)[0]

    def section_of(self, address: int) -> tuple[int, bytes] | None:
        for base, body in self.sections:
            if base <= address < base + len(body):
                return base, body
        return None

    def word_at(self, address: int) -> int | None:
        found = self.section_of(address)
        if found is None:
            return None
        base, body = found
        return struct.unpack_from(">I", body, address - base)[0]


def _is_lwz(instruction: int, rd: int, offset: int) -> bool:
    return (instruction >> 26) == 32 and ((instruction >> 21) & 0x1F) == rd and (instruction & 0xFFFF) == offset


def _is_cmpwi(instruction: int, ra: int, value: int) -> bool:
    return (
        (instruction >> 26) == 11
        and ((instruction >> 16) & 0x1F) == ra
        and (instruction & 0xFFFF) == value
    )


def _branch_target(address: int, instruction: int) -> int | None:
    """Target of an absolute-form-free ``bl``, or None if not a ``bl``."""
    if (instruction >> 26) != 18 or not (instruction & 1) or (instruction & 2):
        return None
    displacement = instruction & 0x03FFFFFC
    if displacement & 0x02000000:
        displacement -= 0x04000000
    return address + displacement


def _loads_fourcc_into_r4(text: DolText, call_address: int, fourcc: int, lookback: int = 14) -> bool:
    """True if r4 is materialised with ``fourcc`` shortly before ``call_address``.

    Echoes builds script-state fourccs inline as ``lis rX, hi16`` plus
    ``addi r4, rX, lo16`` (the halves are often scheduled several
    instructions apart, and the ``lis`` frequently targets a scratch
    register rather than r4 itself).
    """
    high = 0xFFFF & (fourcc >> 16)
    low = fourcc & 0xFFFF
    addi_source: int | None = None
    for address in range(call_address - 4, call_address - 4 * lookback, -4):
        instruction = text.word_at(address)
        if instruction is None:
            return False
        opcode = instruction >> 26
        destination = (instruction >> 21) & 0x1F
        source = (instruction >> 16) & 0x1F
        if opcode == 14 and destination == 4 and (instruction & 0xFFFF) == low:
            addi_source = source
        elif opcode == 15 and source == 0 and (instruction & 0xFFFF) == high:
            if addi_source is not None and destination == addi_source:
                return True
    return False


def _function_start(text: DolText, address: int) -> int:
    """Walks back to the instruction after the previous ``blr``."""
    found = text.section_of(address)
    assert found is not None
    base, body = found
    for candidate in range(address - 4, base - 1, -4):
        if struct.unpack_from(">I", body, candidate - base)[0] == _BLR:
            return candidate + 4
    return base


def _function_end(text: DolText, address: int) -> int:
    found = text.section_of(address)
    assert found is not None
    base, body = found
    for candidate in range(address, base + len(body), 4):
        if struct.unpack_from(">I", body, candidate - base)[0] == _BLR:
            return candidate
    return base + len(body)


def find_warp_addresses(dol: bytes) -> WarpAddresses:
    """Locates the declined-save broadcast in ``dol``.

    Raises ValueError if the anchors don't match exactly once, rather than
    guessing -- a wrong hook address would corrupt unrelated code.
    """
    text = DolText(dol)

    anchors = [
        address
        for address, instruction in text.words()
        if _is_lwz(instruction, 0, _TRANSITION_OFFSET)
        and (following := text.word_at(address + 4)) is not None
        and _is_cmpwi(following, 0, _SAVE_TRANSITION)
    ]

    # Other code waits on the same transition; only the save-station Think
    # also reads the CScriptSpecialFunction flags byte.
    candidates = []
    for anchor in anchors:
        start = _function_start(text, anchor)
        end = _function_end(text, anchor)
        if any(
            (instruction := text.word_at(address)) is not None
            and (instruction >> 26) == 34
            and (instruction & 0xFFFF) == _FLAGS_OFFSET
            for address in range(start, end + 4, 4)
        ):
            candidates.append((start, end))

    if len(candidates) != 1:
        raise ValueError(
            f"expected exactly one save-station Think (lwz r0, 0x{_TRANSITION_OFFSET:X}(rX) / "
            f"cmpwi r0, {_SAVE_TRANSITION}, in a function reading +0x{_FLAGS_OFFSET:X}); "
            f"found {len(candidates)} of {len(anchors)} anchors: "
            f"{[hex(start) for start, _ in candidates]}"
        )

    start, end = candidates[0]

    calls = [
        (address, target)
        for address in range(start, end + 4, 4)
        if (instruction := text.word_at(address)) is not None
        and (target := _branch_target(address, instruction)) is not None
        and _loads_fourcc_into_r4(text, address, ZERO_FOURCC)
    ]
    if len(calls) != 1:
        raise ValueError(
            f"expected exactly one ZERO broadcast in the save-station Think at "
            f"0x{start:08X}, found {len(calls)}: {[hex(a) for a, _ in calls]}"
        )

    call_address, target = calls[0]
    return WarpAddresses(
        decline_broadcast_call=call_address,
        send_script_msgs=target,
        think_start=start,
    )


def _read_dol(path: Path) -> bytes:
    if path.suffix.lower() == ".dol":
        return path.read_bytes()

    from open_prime_rando.patcher_editor import IsoFileProvider

    return IsoFileProvider(path).get_dol()


def main(argv: list[str]) -> int:
    if not argv:
        print(__doc__)
        return 2

    for name in argv:
        path = Path(name)
        addresses = find_warp_addresses(_read_dol(path))
        print(f"{path.name}:")
        print(f"    save-station Think       0x{addresses.think_start:08X}")
        print(f"    decline broadcast (bl)   0x{addresses.decline_broadcast_call:08X}")
        print(f"    send_script_msgs         0x{addresses.send_script_msgs:08X}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
