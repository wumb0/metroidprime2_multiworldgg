"""Locates the DOL addresses the spring ball patch needs, for an Echoes ISO.

The spring ball caves (``client/spring_ball_patch.py``) hook one ``bl`` and
call seven game functions, all of which move between NTSC-U and PAL. Like
``find_warp_addresses.py``, this recovers them by pattern matching instead
of trusting a hardcoded table, anchoring on struct offsets that are the same
in both builds:

- ``CMorphBall::ComputeBallMovement`` switches on ``mBallState``
  (``lwz r0, 0xC80(r3)`` / ``cmpwi r0, 6`` / ``beq`` / ``bge`` /
  ``cmpwi r0, 4``); its first ``bl`` is the hooked
  call to ``ComputeBoostBallMovement``, whose own first ``bl`` is
  ``IsMovementAllowed``.
- ``CPlayer::BombJump`` opens by testing the morph state and
  ``GetBombJumpState`` (``lwz r0, 0x38C(r3)`` / ``cmpwi r0, 1`` /
  ``bne`` / ``lwz r3, 0x1174(r31)`` / ``bl`` / ``cmpwi r3, 1``). Its next
  two calls are ``GetTweakPlayer`` and the ball half-extent getter; the
  call after ``li r4, 0x19`` (Gravity Boost) is ``HasPowerUp``; the call
  after ``addi r4, r1, 0x10`` is ``SetVelocityWR``.
- ``CPlayer::SetMoveState`` is the target of the ``li r4, 4`` call that
  ``CPlayer::AcceptScriptMsg`` makes right after testing
  ``lwz r0, 0x2D0(rX)`` / ``cmpwi r0, 0`` (Falling while OnGround and
  morphed -> FallingMorphed).

Usage::

    python -m metroidprime2.tools.find_spring_ball_addresses /path/to/echoes.iso ...

Accepts ISO paths or raw ``.dol`` files, and prints each address next to
the value in ``client/versions.py`` for the matching build.
"""

from __future__ import annotations

import dataclasses
import sys
from pathlib import Path

from .find_warp_addresses import DolText, _branch_target, _function_end, _function_start, _read_dol


def _lwz(rd: int, offset: int, ra: int) -> int:
    return (32 << 26) | (rd << 21) | (ra << 16) | offset


def _cmpwi(ra: int, value: int) -> int:
    return (11 << 26) | (ra << 16) | (value & 0xFFFF)


def _li(rd: int, value: int) -> int:
    return (14 << 26) | (rd << 21) | (value & 0xFFFF)


def _addi(rd: int, ra: int, value: int) -> int:
    return (14 << 26) | (rd << 21) | (ra << 16) | (value & 0xFFFF)


def _is_bne(instruction: int) -> bool:
    return (instruction >> 26) == 16 and ((instruction >> 21) & 0x1F) == 4 and ((instruction >> 16) & 0x1F) == 2


@dataclasses.dataclass(frozen=True)
class FoundSpringBallAddresses:
    """Same fields as ``client.versions.SpringBallAddresses``."""

    boost_ball_movement_call: int
    compute_boost_ball_movement: int
    has_power_up: int
    is_movement_allowed: int
    get_tweak_player: int
    get_player_ball_half_extent: int
    bomb_jump: int
    set_velocity_wr: int
    set_move_state: int


def _single(what: str, found: list[int]) -> int:
    if len(found) != 1:
        raise ValueError(f"expected exactly one {what}, found {len(found)}: {[hex(a) for a in found]}")
    return found[0]


def _matches(text: DolText, address: int, words: list[int | None]) -> bool:
    """``words`` must appear at ``address``; ``None`` matches anything."""
    for index, expected in enumerate(words):
        actual = text.word_at(address + 4 * index)
        if actual is None or (expected is not None and actual != expected):
            return False
    return True


def _calls(text: DolText, start: int, end: int) -> list[tuple[int, int]]:
    """(address, target) of every ``bl`` in [start, end]."""
    return [
        (address, target)
        for address in range(start, end + 4, 4)
        if (instruction := text.word_at(address)) is not None
        and (target := _branch_target(address, instruction)) is not None
    ]


def _first_call_after(text: DolText, address: int, limit: int = 8) -> tuple[int, int]:
    for candidate in range(address, address + 4 * limit, 4):
        instruction = text.word_at(candidate)
        if instruction is not None and (target := _branch_target(candidate, instruction)) is not None:
            return candidate, target
    raise ValueError(f"no bl within {limit} instructions of 0x{address:08X}")


def _call_preceded_by(text: DolText, calls: list[tuple[int, int]], setup: int, lookback: int, what: str) -> int:
    """Target of the one call with ``setup`` among the ``lookback``
    instructions before it."""
    return _single(
        what,
        [
            target
            for address, target in calls
            if any(text.word_at(address - 4 * back) == setup for back in range(1, lookback + 1))
        ],
    )


def find_spring_ball_addresses(dol: bytes) -> FoundSpringBallAddresses:
    """Raises ValueError if any anchor doesn't match exactly once, rather
    than guessing -- a wrong hook address would corrupt unrelated code."""
    text = DolText(dol)

    # ComputeBallMovement -> ComputeBoostBallMovement -> IsMovementAllowed
    switch = _single(
        "ComputeBallMovement ball-state switch",
        [
            address
            for address, instruction in text.words()
            if instruction == _lwz(0, 0xC80, 3)
            and _matches(text, address + 4, [_cmpwi(0, 6), None, None, _cmpwi(0, 4)])
        ],
    )
    boost_call, compute_boost = _first_call_after(text, switch, limit=16)
    _, is_movement_allowed = _first_call_after(text, compute_boost, limit=32)

    # BombJump and the calls inside it
    bomb_jump_anchor = _single(
        "BombJump morph-state/bomb-jump-state test",
        [
            address
            for address, instruction in text.words()
            if instruction == _lwz(0, 0x38C, 3)
            and _matches(text, address + 4, [None, _cmpwi(0, 1)])
            and _is_bne(text.word_at(address + 12) or 0)
            and _matches(text, address + 16, [_lwz(3, 0x1174, 31), None, _cmpwi(3, 1)])
        ],
    )
    bomb_jump = _function_start(text, bomb_jump_anchor)
    calls = _calls(text, bomb_jump, _function_end(text, bomb_jump_anchor))
    if len(calls) < 3:
        raise ValueError(f"BombJump at 0x{bomb_jump:08X} makes only {len(calls)} calls")
    get_tweak_player = calls[1][1]
    get_player_ball_half_extent = calls[2][1]
    has_power_up = _call_preceded_by(text, calls, _li(4, 0x19), 1, "HasPowerUp(GravityBoost) in BombJump")
    set_velocity_wr = _call_preceded_by(text, calls, _addi(4, 1, 0x10), 6, "SetVelocityWR in BombJump")

    # SetMoveState, via AcceptScriptMsg's OnGround -> FallingMorphed call
    set_move_state = _single(
        "SetMoveState(FallingMorphed) after an OnGround test",
        sorted(
            {
                target
                for address, instruction in text.words()
                if instruction == _li(4, 4)
                and (call := text.word_at(address + 4)) is not None
                and (target := _branch_target(address + 4, call)) is not None
                and any(
                    (word := text.word_at(address - 4 * back)) is not None
                    and (word & 0xFFE0FFFF) == _lwz(0, 0x2D0, 0)
                    and text.word_at(address - 4 * back + 4) == _cmpwi(0, 0)
                    for back in range(1, 7)
                )
            }
        ),
    )

    return FoundSpringBallAddresses(
        boost_ball_movement_call=boost_call,
        compute_boost_ball_movement=compute_boost,
        has_power_up=has_power_up,
        is_movement_allowed=is_movement_allowed,
        get_tweak_player=get_tweak_player,
        get_player_ball_half_extent=get_player_ball_half_extent,
        bomb_jump=bomb_jump,
        set_velocity_wr=set_velocity_wr,
        set_move_state=set_move_state,
    )


def _known_table(dol: bytes) -> tuple[str, object] | None:
    """The ``client/versions.py`` entry whose build string is in ``dol``."""
    from ..client import versions

    for version in versions.VERSIONS:
        if version.build_string in dol:
            return version.name, version.spring_ball
    return None


def main(argv: list[str]) -> int:
    if not argv:
        print(__doc__)
        return 2

    for name in argv:
        path = Path(name)
        dol = _read_dol(path)
        found = find_spring_ball_addresses(dol)
        known = _known_table(dol)
        print(f"{path.name} ({known[0] if known else 'unknown build'}):")
        for field in dataclasses.fields(found):
            value = getattr(found, field.name)
            note = ""
            if known is not None:
                expected = getattr(known[1], field.name)
                note = "  ok" if expected == value else f"  MISMATCH: versions.py has 0x{expected:08X}"
            print(f"    {field.name:<30} 0x{value:08X}{note}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
