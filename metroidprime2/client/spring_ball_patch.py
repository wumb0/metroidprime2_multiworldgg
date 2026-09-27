"""Spring ball: a bomb jump on a button press while in Morph Ball, without
laying a bomb, available once Morph Ball Bombs are collected.

A port of randomprime's ``patch_spring_ball`` (Metroid Prime 1), which
``open-prime-rando`` has no equivalent for. Both hook
``CMorphBall::ComputeBallMovement`` just before it calls
``CMorphBall::ComputeBoostBallMovement``: when the button is held and every
gate below passes, the cave calls ``CPlayer::BombJump`` with a fake bomb at
the player's own position, then lets vanilla movement run untouched.

Unlike randomprime, the hook replaces the ``fmr f1, f31`` in front of
``bl ComputeBoostBallMovement`` rather than the ``bl`` itself. The cave
performs that ``fmr`` on the way out and returns, and ComputeBallMovement
reloads the call's arguments from its own non-volatile registers. That
also lets the cave read those registers (ball, input, state manager)
directly instead of copying them. ``apply_dol_patches`` checks the whole
five-instruction sequence first, so a build laid out differently is
refused rather than patched.

Gates, in cave order (each mirrors one of randomprime's, re-derived against
the Echoes DOL -- see ``metroidprime2/tools/find_spring_ball_addresses.py``):

- a cooldown of ``COOLDOWN_FRAMES`` since the last spring (one counter for
  all players);
- the configured button (``BUTTONS``);
- the ball is in its Normal or Boost state (not Spider, Screw Attack or
  Projectile);
- the player is on the ground (``NPlayer::EPlayerMovementState`` OnGround)
  and ``CMorphBall::GetBombJumpState`` is ``BombJumpAvailable``;
- the surface restraint isn't Shrubbery (Prime 1's snakeweed);
- nothing is attached to the player and no energy-drain source is active;
- the player has Morph Ball Bombs;
- ``CMorphBall::IsMovementAllowed``.

There is no morph-state check: both callers of ComputeBallMovement (in
``CPlayer::ProcessInput``) only call it while Morphed.

Echoes' ``BombJump`` zeroes horizontal velocity, as Prime 1's does, so the
cave saves it beforehand and restores it through ``SetVelocityWR`` (which
also recomputes momentum; randomprime pokes the velocity floats directly).
It then divides the new vertical speed by ``HALF_PIPE_DIVISOR`` if a
half-pipe was touched recently, as randomprime does, and switches to the
``FallingMorphed`` movement state so the spring can't retrigger while the
ball is still on the ground.

Unlike randomprime, there are no hooks that reset the cooldown on morph and
unmorph. The cooldown only counts down while the ball is being simulated,
so a spring immediately followed by an unmorph can leave up to
``COOLDOWN_FRAMES`` of wait for the next time you morph.

The cave has to fit in the largest free region open-prime-rando registers
for Echoes (the error handler's 0x14C bytes); ``CodeCaveTracker`` places
the largest request first, and this is it.
"""

from __future__ import annotations

import dataclasses
import struct
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from open_prime_rando.dol_patching.code_cave_tracker import CodeCaveTracker
    from ppc_asm.assembler import BaseInstruction
    from ppc_asm.assembler.ppc import GeneralRegister

    from .versions import SpringBallAddresses


# --------------------------------------------------------------------------
# Struct offsets. Identical on NTSC-U and PAL (only code/data addresses
# move between the two builds; every function the cave reads these
# through was diffed between both DOLs).
# --------------------------------------------------------------------------

_MORPH_BALL_PLAYER = 0x0
"""``CMorphBall::mPlayer`` (``CPlayer&``), its first member."""

_MORPH_BALL_STATE = 0xC80
"""``CMorphBall::mBallState``; the switch in ``ComputeBallMovement``.
0 = Normal, 1 = Boost, 2/3 = Spider/SpiderBoost, 4-6 = Screw Attack
states, 7 = Projectile."""

_MORPH_BALL_HALF_PIPE_COOLDOWN = 0x185C
"""``CMorphBall::mTouchHalfPipeCooldown`` (float, clamped at 0), the first
field ``UpdateHalfPipeStatus`` decrements -- Prime 1's ``x1dfc``."""

_MORPH_BALL_BOMB_JUMP_STATE = 0x18F4
"""``CMorphBall::mBombJumpState``, returned by ``GetBombJumpState``;
``BombJump`` does nothing unless it is 0 (available)."""

_PLAYER_POSITION = 0x54
"""The player's world position (three floats), as ``BombJump`` reads it --
and, passed straight through, the cave's fake bomb position."""

_PLAYER_VELOCITY = 0x1A8
"""``CPhysicsActor`` velocity (three floats), as ``SetVelocityWR`` writes
it."""

_PLAYER_MOVEMENT_STATE = 0x2D0
"""``NPlayer::EPlayerMovementState``, written only by ``SetMoveState``.
0 = OnGround, 4 = FallingMorphed (same enum as Prime 1)."""

_PLAYER_ATTACHED_ACTOR = 0x2E4
"""``TUniqueId`` of whatever is attached to the player (u16), set by
``AttachActorToPlayer``. ``kInvalidUniqueId`` (0xFFFF) when free."""

_PLAYER_ENERGY_DRAIN_SOURCE_COUNT = 0x2F0
"""Element count of the ``CPlayerEnergyDrain`` source vector at +0x2EC;
nonzero while something is draining energy. Echoes has no out-of-line
``GetEnergyDrainIntensity``, so this is what the cave tests instead."""

_PLAYER_SURFACE_RESTRAINT = 0x344
"""``CPlayer::ESurfaceRestraints`` (``Get/SetSurfaceRestraint``)."""

_PLAYER_STATE = 0x1314
"""``CPlayerState*``."""

_SURFACE_RESTRAINT_SHRUBBERY = 7
_MOVEMENT_STATE_ON_GROUND = 0
_MOVEMENT_STATE_FALLING_MORPHED = 4
_INVALID_UNIQUE_ID = 0xFFFF
_BALL_STATE_BOOST = 1

MORPH_BALL_BOMB = 18
"""``PlayerItemEnum.MorphBallBomb``, the item spring ball is gated on."""

COOLDOWN_FRAMES = 40
"""Frames before another spring can fire, as in randomprime."""

HALF_PIPE_DIVISOR = 1.5
"""Vertical speed divisor after a recent half-pipe touch, as in randomprime."""


# --------------------------------------------------------------------------
# Buttons
# --------------------------------------------------------------------------


@dataclasses.dataclass(frozen=True)
class AnalogDirection:
    """One direction of an analog stick: a float in [-1, 1] in
    ``CFinalInput``, pressed past ``ANALOG_THRESHOLD_BITS`` in the given
    direction."""

    offset: int
    negative: bool


@dataclasses.dataclass(frozen=True)
class DigitalButton:
    """A digital button: one bit of the held-button bytes in
    ``CFinalInput``."""

    offset: int
    mask: int


ANALOG_THRESHOLD_BITS = 0x3F333333
"""``0.7f``, ``CFinalInput::kInput_AnalogOnThreshhold`` -- the same cutoff
the game's own digital stick accessors use. A float in [-1, 1] and its bits
order the same way under a signed-integer compare when the float is
non-negative, and a negative float is a negative integer, so the cave
compares raw bits with ``cmpw`` (a direction on the negative side flips the
sign bit first)."""

_RIGHT_STICK_X = 0x10
_RIGHT_STICK_Y = 0x14
_BUTTONS_2 = 0x29
"""``CFinalInput`` layout (decomp-matched ``Kyoto/Input/CFinalInput.hpp``).
The second held-button byte packs, MSB first: Z, L, R, D-Pad Up, D-Pad
Right, D-Pad Down, D-Pad Left, Start (bit order confirmed against the
compiled constructor's ``rlwimi`` masks)."""

BUTTONS: dict[str, AnalogDirection | DigitalButton] = {
    "c_stick_up": AnalogDirection(_RIGHT_STICK_Y, negative=False),
    "c_stick_down": AnalogDirection(_RIGHT_STICK_Y, negative=True),
    "c_stick_left": AnalogDirection(_RIGHT_STICK_X, negative=True),
    "c_stick_right": AnalogDirection(_RIGHT_STICK_X, negative=False),
    "d_pad_up": DigitalButton(_BUTTONS_2, 0x10),
    "l_trigger": DigitalButton(_BUTTONS_2, 0x40),
}
"""Keyed by the ``SpringBallButton`` option's names. Visor switching (D-Pad)
is confirmed gated on being unmorphed (``CPlayer::UpdateVisorState`` tests
the morph state first). C-Stick beam switching is assumed not to happen in
Morph Ball, as in Prime 1, where randomprime also uses C-Stick up -- that
one was not traced through the DOL (``CPlayerGun::ProcessInput`` is only
reached indirectly)."""


# --------------------------------------------------------------------------
# Cave
# --------------------------------------------------------------------------

_FRAME_SIZE = 0x28
_VELOCITY = 0x08
_SAVED_REGISTERS = 0x14
"""Stack frame layout: 0x08 the new velocity vector (its z slot doubles as
scratch for loading ``HALF_PIPE_DIVISOR``), r27-r31 saved at 0x14-0x27."""

# Registers. Borrowed from ComputeBallMovement, which keeps its arguments
# in non-volatile registers across the hooked instruction (the cave only
# reads these, and lmw restores them regardless):
#   r29 CMorphBall*, r30 const CFinalInput*, r31 CStateManager*, f31 dt.
# Owned by the cave: r28 CPlayer*, r27 &cooldown.

HOOK_SITE_WORDS = (0xFC20F890, 0x7FA3EB78, 0x7FC4F378, 0x7FE5FB78)
"""``fmr f1, f31; mr r3, r29; mr r4, r30; mr r5, r31`` -- the argument setup
for ``bl ComputeBoostBallMovement``, which immediately follows. The first
word is replaced with the ``bl`` to the cave; the cave's register
assumptions above hold only while all of these are in place."""

_FMR_F1_F31 = HOOK_SITE_WORDS[0]


def _raw(value: int) -> BaseInstruction:
    from ppc_asm.assembler.ppc import Instruction

    return Instruction(value)


def _andi_dot(ra_rs: int, mask: int) -> BaseInstruction:
    """``andi. rA, rS, mask`` with rA == rS (not in ppc_asm)."""
    return _raw((28 << 26) | (ra_rs << 21) | (ra_rs << 16) | mask)


def _xori(ra_rs: int, mask: int) -> BaseInstruction:
    """``xori rA, rS, mask`` with rA == rS (not in ppc_asm)."""
    return _raw((26 << 26) | (ra_rs << 21) | (ra_rs << 16) | mask)


def _or_dot(ra_rs: int, rb: int) -> BaseInstruction:
    """``or. rA, rS, rB`` with rA == rS (not in ppc_asm): sets cr0 eq when
    both are zero."""
    return _raw((31 << 26) | (ra_rs << 21) | (ra_rs << 16) | (rb << 11) | (444 << 1) | 1)


def _clear_upper_bytes(register: GeneralRegister) -> BaseInstruction:
    """``clrlwi rN, rN, 24``: a returned ``bool`` is only defined in its low
    byte (the game's own callers do the same before testing it).

    Always the same register in and out: ppc_asm's ``rlwinm`` encodes its
    first argument in the source field and its second in the destination
    field, the reverse of the assembler operand order."""
    from ppc_asm.assembler.ppc import rlwinm

    return rlwinm(register, register, 0, 24, 31)


def _button_check(button: AnalogDirection | DigitalButton) -> list[BaseInstruction]:
    """Branches to ``_done`` unless ``button`` is held."""
    from ppc_asm.assembler.ppc import beq, ble, cmpw, lbz, lis, lwz, ori, r0, r12, r30, xoris

    if isinstance(button, DigitalButton):
        return [
            lbz(r0, button.offset, r30),
            _andi_dot(0, button.mask),
            beq("_done"),
        ]
    return [
        lwz(r0, button.offset, r30),
        *([xoris(r0, r0, 0x8000)] if button.negative else []),
        lis(r12, ANALOG_THRESHOLD_BITS >> 16),
        ori(r12, r12, ANALOG_THRESHOLD_BITS & 0xFFFF),
        cmpw(0, r0, r12),
        ble("_done"),
    ]


def build_cave(addresses: SpringBallAddresses, button: AnalogDirection | DigitalButton) -> list[BaseInstruction]:
    """The whole routine, called in place of the ``fmr f1, f31`` in front of
    ``bl ComputeBoostBallMovement``. Ends by doing that ``fmr`` itself, so
    ComputeBallMovement goes on to set up and make the call as in vanilla."""
    from ppc_asm.assembler import custom_ppc
    from ppc_asm.assembler.ppc import (
        LR,
        addi,
        b,
        beq,
        bgt,
        bl,
        ble,
        blr,
        bne,
        cmplwi,
        cmpwi,
        f0,
        f2,
        fdivs,
        lfs,
        lhz,
        li,
        lis,
        lmw,
        lwz,
        mfspr,
        mr,
        mtspr,
        r0,
        r1,
        r3,
        r4,
        r5,
        r12,
        r27,
        r28,
        r29,
        r31,
        stfs,
        stmw,
        stw,
        stwu,
    )

    half_pipe_divisor_bits = struct.unpack(">I", struct.pack(">f", HALF_PIPE_DIVISOR))[0]
    assert half_pipe_divisor_bits & 0xFFFF == 0, "loaded with a single lis"

    button_check = _button_check(button)
    button_check[0].with_label("_check")

    return [
        stwu(r1, -_FRAME_SIZE, r1),
        mfspr(r0, LR),
        stw(r0, _FRAME_SIZE + 4, r1),
        stmw(r27, _SAVED_REGISTERS, r1),
        lwz(r28, _MORPH_BALL_PLAYER, r29),
        custom_ppc.load_address(r27, "_cooldown"),
        # While cooling down, count down and skip everything else. (Not in
        # r0: as addi's base register, r0 reads as a literal 0.)
        lwz(r12, 0, r27),
        cmpwi(r12, 0),
        ble("_check"),
        addi(r12, r12, -1),
        stw(r12, 0, r27),
        b("_done"),
        *button_check,
        lwz(r0, _MORPH_BALL_STATE, r29),
        cmplwi(r0, _BALL_STATE_BOOST),
        bgt("_done"),
        # On the ground (OnGround == 0) and bomb jumps available (== 0).
        lwz(r0, _PLAYER_MOVEMENT_STATE, r28),
        lwz(r12, _MORPH_BALL_BOMB_JUMP_STATE, r29),
        _or_dot(0, 12),
        bne("_done"),
        lwz(r0, _PLAYER_SURFACE_RESTRAINT, r28),
        cmpwi(r0, _SURFACE_RESTRAINT_SHRUBBERY),
        beq("_done"),
        # Nothing attached (id == 0xFFFF) and nothing draining (count == 0).
        lhz(r12, _PLAYER_ATTACHED_ACTOR, r28),
        _xori(12, _INVALID_UNIQUE_ID),
        lwz(r0, _PLAYER_ENERGY_DRAIN_SOURCE_COUNT, r28),
        _or_dot(0, 12),
        bne("_done"),
        lwz(r3, _PLAYER_STATE, r28),
        li(r4, MORPH_BALL_BOMB),
        bl(addresses.has_power_up),
        _clear_upper_bytes(r3),
        cmplwi(r3, 0),
        beq("_done"),
        mr(r3, r29),
        bl(addresses.is_movement_allowed),
        _clear_upper_bytes(r3),
        cmplwi(r3, 0),
        beq("_done"),
        # BombJump zeroes horizontal velocity; keep it.
        lfs(f0, _PLAYER_VELOCITY, r28),
        stfs(f0, _VELOCITY, r1),
        lfs(f0, _PLAYER_VELOCITY + 4, r28),
        stfs(f0, _VELOCITY + 4, r1),
        # A "bomb" at the player's own position: BombJump measures from
        # position + (0, 0, half-extent), so it sees a bomb half-extent
        # below the ball -- inside the 1.5 bomb jump radius (ball radius
        # is 0.7 on both builds), and below the ball, as it requires.
        mr(r3, r28),
        addi(r4, r28, _PLAYER_POSITION),
        mr(r5, r31),
        bl(addresses.bomb_jump),
        # The half-pipe cooldown is a non-negative float, so its raw bits
        # are > 0 exactly when the float is.
        lfs(f0, _PLAYER_VELOCITY + 8, r28),
        lwz(r0, _MORPH_BALL_HALF_PIPE_COOLDOWN, r29),
        cmpwi(r0, 0),
        ble("_store_vertical"),
        lis(r0, half_pipe_divisor_bits >> 16),
        stw(r0, _VELOCITY + 8, r1),
        lfs(f2, _VELOCITY + 8, r1),
        fdivs(f0, f0, f2),
        stfs(f0, _VELOCITY + 8, r1).with_label("_store_vertical"),
        mr(r3, r28),
        addi(r4, r1, _VELOCITY),
        bl(addresses.set_velocity_wr),
        mr(r3, r28),
        li(r4, _MOVEMENT_STATE_FALLING_MORPHED),
        mr(r5, r31),
        bl(addresses.set_move_state),
        li(r0, COOLDOWN_FRAMES),
        stw(r0, 0, r27),
        lmw(r27, _SAVED_REGISTERS, r1).with_label("_done"),
        lwz(r0, _FRAME_SIZE + 4, r1),
        mtspr(LR, r0),
        addi(r1, r1, _FRAME_SIZE),
        _raw(_FMR_F1_F31),
        blr(),
        _raw(0).with_label("_cooldown"),
    ]


def apply_dol_patches(cave: CodeCaveTracker, addresses: SpringBallAddresses, button: str) -> None:
    """Requests the cave and points the hooked instruction at it.

    Must run before ``CodeCaveTracker.fulfill_requests()``, i.e. from inside
    open-prime-rando's ``_apply_patches``. Refuses to patch a DOL whose hook
    site isn't exactly the expected argument setup and call, rather than
    corrupting an unknown build.
    """
    from ppc_asm import assembler
    from ppc_asm.assembler.ppc import bl

    site = addresses.boost_ball_argument_setup
    call = site + 4 * len(HOOK_SITE_WORDS)
    expected = b"".join(struct.pack(">I", word) for word in HOOK_SITE_WORDS) + bytes(
        assembler.assemble_instructions(call, [bl(addresses.compute_boost_ball_movement)])
    )
    actual = cave.dol_editor.read(site, len(expected))
    if actual != expected:
        raise ValueError(
            f"Spring Ball hook site 0x{site:08X} holds {actual.hex()}, expected {expected.hex()}; "
            f"this DOL isn't a supported build."
        )
    if button not in BUTTONS:
        raise ValueError(f"Unknown spring ball button {button!r}; expected one of {sorted(BUTTONS)}")

    def _with_cave(address: int) -> None:
        cave.dol_editor.write_instructions(site, [bl(address)])

    cave.request_code_cave(build_cave(addresses, BUTTONS[button]), _with_cave)
