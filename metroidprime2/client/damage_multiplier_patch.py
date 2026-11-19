"""Base damage multipliers: ``incoming_damage_multiplier`` (what hurts you)
and ``outgoing_damage_multiplier`` (what you hurt enemies with).

Both are one hook and one small cave each; neither has a counterpart in
open-prime-rando, whose ``DamageChanges`` only knows energy per tank, the
safe zone heal rate, dangerous energy tanks and the dark world damage.

**Incoming.** ``CStateManager::ApplyLocalDamage`` (NTSC 0x8003D838) is where
every hit on Samus -- enemies, hazards, Dark Aether (``kWT_AreaDark``) --
ends up. Its first act on the player is the vanilla hard mode scaling: if
``CGameState`` says hard mode is on, the damage in ``f29`` is multiplied by
``GetHardModeDamageMultiplier`` for a list of weapon types. Both outcomes of
that test join at ``lhz r0, 0(r20)`` (the weapon type, reloaded right after),
which is where the cave goes: it multiplies ``f29`` by the configured factor
and carries on. Suit damage reduction, Defense Up and the energy tanks all
come after, so the multiplier applies to the raw hit before any of them
(``damage * multiplier * (1 - reduction)``). Hard mode itself is left alone.

**Outgoing.** ``CDamageInfo::ApplyDoubleDamage`` (NTSC 0x8018A098) returns a
copy of a weapon's ``CDamageInfo`` with damage, radius damage and knockback
(offsets 4, 8 and 0x10) scaled by Double Damage when the player has it, and
an unscaled copy otherwise. Both outcomes join at the epilogue
(``lwz r0, 0x14(r1)``), where the cave scales those same three fields of the
returned struct (``r30``) by the factor. So the multiplier reaches exactly
the damage sources Double Damage reaches (the function has eight callers in
the DOL: the beams, missiles and bombs), and stacks with Double Damage
(``base * (1 + copies * double_damage_bonus)``).

The factor is a single-precision float, built in ``r0`` with ``lis``/``ori``
and moved to an FPR through the red zone below ``r1`` (the same trick
open-prime-rando's own Massive Damage cave uses), so the caves need no data
word and no free register beyond ``r0`` and ``f0``/``f1``, which are scratch
at both sites. ``f29`` is a callee-saved register ``ApplyLocalDamage``
already holds the damage in for its whole length.

Everything is verified against the NTSC-U and PAL disassembly; neither
has been run in game.
"""

from __future__ import annotations

import struct
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from open_prime_rando.dol_patching.code_cave_tracker import CodeCaveTracker
    from ppc_asm.assembler import BaseInstruction

    from .versions import DamageMultiplierAddresses

# --------------------------------------------------------------------------
# What the hook sites must look like (identical on NTSC-U and PAL).
# --------------------------------------------------------------------------

LOCAL_DAMAGE_HOOK_WORDS = (
    0xEFBD0072,  # fmuls f29, f29, f1   (end of the hard mode branch; hook - 4)
    0xA0140000,  # lhz   r0, 0(r20)     (the hook: weapon type of the CDamageInfo)
    0x7F63DB78,  # mr    r3, r27        (hook + 4: the cave returns here)
)
"""``ApplyLocalDamage`` around the hook, as ``(hook - 4, hook, hook + 4)``."""

APPLY_DOUBLE_DAMAGE_HOOK_WORDS = (
    0x981E001A,  # stb   r0, 0x1a(r30)  (last field copied; hook - 4)
    0x80010014,  # lwz   r0, 0x14(r1)   (the hook: epilogue)
    0x83E1000C,  # lwz   r31, 0xc(r1)   (hook + 4: the cave returns here)
)
"""``ApplyDoubleDamage`` around the hook, as ``(hook - 4, hook, hook + 4)``."""

_DAMAGE_OFFSETS = (0x4, 0x8, 0x10)
"""``CDamageInfo`` damage, radius damage and knockback: what Double Damage
scales."""

_RED_ZONE = -8
"""Scratch word below ``r1`` the factor is moved through."""

MIN_PERCENT = 1
MAX_PERCENT = 1000


def multiplier_bits(percent: int) -> int:
    """The single-precision float bits of ``percent / 100``."""
    if not MIN_PERCENT <= percent <= MAX_PERCENT:
        raise ValueError(f"damage multiplier {percent}% outside {MIN_PERCENT}-{MAX_PERCENT}")
    return struct.unpack(">I", struct.pack(">f", percent / 100))[0]


def _load_factor(percent: int) -> list[BaseInstruction]:
    """``f0 = percent / 100`` (clobbers ``r0``)."""
    from ppc_asm.assembler.ppc import f0, lfs, lis, ori, r0, r1, stw

    bits = multiplier_bits(percent)
    instructions = [lis(r0, bits >> 16)]
    if bits & 0xFFFF:
        instructions.append(ori(r0, r0, bits & 0xFFFF))
    instructions += [stw(r0, _RED_ZONE, r1), lfs(f0, _RED_ZONE, r1)]
    return instructions


def build_incoming_cave(percent: int, return_address: int) -> list[BaseInstruction]:
    """Scales ``ApplyLocalDamage``'s damage (``f29``), runs the replaced
    ``lhz r0, 0(r20)`` and goes back."""
    from ppc_asm.assembler.ppc import GeneralRegister, b, f0, f29, fmuls, lhz, r0

    r20 = GeneralRegister(20)  # ppc_asm only exports the few registers its own patches use

    return [
        *_load_factor(percent),
        fmuls(f29, f29, f0),
        lhz(r0, 0, r20),
        b(return_address),
    ]


def build_outgoing_cave(percent: int, return_address: int) -> list[BaseInstruction]:
    """Scales the returned ``CDamageInfo``'s damage, radius damage and
    knockback (``r30`` points at it), runs the replaced ``lwz r0, 0x14(r1)``
    and goes back."""
    from ppc_asm.assembler.ppc import b, f0, f1, fmuls, lfs, lwz, r0, r1, r30, stfs

    scale = []
    for offset in _DAMAGE_OFFSETS:
        scale += [lfs(f1, offset, r30), fmuls(f1, f1, f0), stfs(f1, offset, r30)]
    return [
        *_load_factor(percent),
        *scale,
        lwz(r0, 0x14, r1),
        b(return_address),
    ]


def _check_site(cave: CodeCaveTracker, hook: int, expected: tuple[int, int, int], what: str) -> None:
    wanted = struct.pack(">3I", *expected)
    actual = cave.dol_editor.read(hook - 4, 12)
    if actual != wanted:
        raise ValueError(
            f"{what} hook site 0x{hook:08X} holds {actual.hex()}, expected {wanted.hex()}; "
            f"this DOL isn't a supported build."
        )


def _hook(cave: CodeCaveTracker, hook: int, cave_instructions: list[BaseInstruction]) -> None:
    from ppc_asm.assembler.ppc import b

    def _with_cave(address: int) -> None:
        cave.dol_editor.write_instructions(hook, [b(address)])

    cave.request_code_cave(cave_instructions, _with_cave)


def apply_dol_patches(
    cave: CodeCaveTracker,
    addresses: DamageMultiplierAddresses,
    *,
    incoming_percent: int = 100,
    outgoing_percent: int = 100,
) -> None:
    """Requests the caves for every multiplier that isn't 100%.

    Must run before ``CodeCaveTracker.fulfill_requests()``, i.e. from inside
    open-prime-rando's ``_apply_patches``. Refuses a DOL whose hook sites
    aren't exactly the expected instructions.
    """
    if incoming_percent != 100:
        hook = addresses.local_damage_hook
        _check_site(cave, hook, LOCAL_DAMAGE_HOOK_WORDS, "Incoming damage multiplier")
        _hook(cave, hook, build_incoming_cave(incoming_percent, hook + 4))
    if outgoing_percent != 100:
        hook = addresses.double_damage_epilogue_hook
        _check_site(cave, hook, APPLY_DOUBLE_DAMAGE_HOOK_WORDS, "Outgoing damage multiplier")
        _hook(cave, hook, build_outgoing_cave(outgoing_percent, hook + 4))
