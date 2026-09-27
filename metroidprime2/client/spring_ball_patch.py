"""Spring ball: a bomb jump on a button press while in Morph Ball, without
laying a bomb, available once Morph Ball Bombs are collected.

A port of randomprime's ``patch_spring_ball`` (Metroid Prime 1), which
``open-prime-rando`` has no equivalent for. Both work the same way: the
``bl CMorphBall::ComputeBoostBallMovement`` inside
``CMorphBall::ComputeBallMovement`` is redirected through a code cave that,
when the button is held and every gate below passes, calls
``CPlayer::BombJump`` with a fake bomb position, then tail-branches into the
original ``ComputeBoostBallMovement`` so vanilla movement runs untouched.

Gates, in cave order (each mirrors one of randomprime's, re-derived against
the Echoes DOL -- see ``metroidprime2/tools/find_spring_ball_addresses.py``):

- a per-controller cooldown of ``COOLDOWN_FRAMES`` since the last spring;
- the configured button (``BUTTONS``);
- the ball is in its Normal or Boost state (not Spider, Screw Attack or
  Projectile);
- ``CMorphBall::GetBombJumpState`` is ``BombJumpAvailable``;
- the player is on the ground (``NPlayer::EPlayerMovementState`` OnGround);
- the surface restraint isn't Shrubbery (Prime 1's snakeweed);
- nothing is attached to the player and no energy-drain source is active;
- the player has Morph Ball Bombs;
- ``CMorphBall::IsMovementAllowed``.

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
``COOLDOWN_FRAMES`` of wait for the next time you morph. That saves two more
DOL hooks and code caves, which are in short supply in Echoes (see below).

**Code cave split.** The whole routine doesn't fit in any single free
region open-prime-rando registers for Echoes (the largest is 0x14C bytes),
so it is two caves. A *body* cave (checks, the jump itself, the epilogue and
the data words) is strictly the larger of the two, so ``CodeCaveTracker``
places it first. The *entry* cave (the hook target: frame setup, cooldown,
button and early checks) is placed after it, so it can reference the body's
address by symbol. The body never references the entry.
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
"""The player's world position (three floats), as ``BombJump`` reads it."""

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

_PLAYER_MORPH_STATE = 0x38C
"""``CPlayer::EPlayerMorphBallState``; 1 = Morphed. ``BombJump`` does
nothing unless it is 1."""

_PLAYER_STATE = 0x1314
"""``CPlayerState*``."""

_FINAL_INPUT_CONTROLLER = 0x4
"""``CFinalInput::mControllerIdx``, which indexes the cooldown array."""

_SURFACE_RESTRAINT_SHRUBBERY = 7
_MOVEMENT_STATE_ON_GROUND = 0
_MOVEMENT_STATE_FALLING_MORPHED = 4
_MORPHED = 1
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
# Caves
# --------------------------------------------------------------------------

BODY_SYMBOL = "AP::SpringBall::Body"
DONE_SYMBOL = "AP::SpringBall::Done"
COOLDOWNS_SYMBOL = "AP::SpringBall::Cooldowns"

_FRAME_SIZE = 0x40
_BOMB_POSITION = 0x10
_VELOCITY = 0x1C
_DELTA_TIME = 0x28
_SAVED_REGISTERS = 0x2C
"""Stack frame layout (both caves share the one frame the entry cave
builds): 0x10 fake bomb position, 0x1C new velocity, 0x28 ``dt``, and
r27-r31 saved at 0x2C-0x3F."""

# Registers, for the lifetime of the frame:
#   r31 CMorphBall*, r30 const CFinalInput*, r29 CStateManager*,
#   r28 CPlayer*, r27 this controller's cooldown word.


def _andi_dot(ra_rs: int, mask: int) -> BaseInstruction:
    """``andi. rA, rS, mask`` with rA == rS (not in ppc_asm)."""
    from ppc_asm.assembler.ppc import Instruction

    return Instruction((28 << 26) | (ra_rs << 21) | (ra_rs << 16) | mask)


def _clear_upper_bytes(register: GeneralRegister) -> BaseInstruction:
    """``clrlwi rN, rN, 24``: a returned ``bool`` is only defined in its low
    byte (the game's own callers do the same before testing it).

    Always the same register in and out: ppc_asm's ``rlwinm`` encodes its
    first argument in the source field and its second in the destination
    field, the reverse of the assembler operand order."""
    from ppc_asm.assembler.ppc import rlwinm

    return rlwinm(register, register, 0, 24, 31)


def _button_check(button: AnalogDirection | DigitalButton) -> list[BaseInstruction]:
    """Branches to the entry cave's exit unless ``button`` is held."""
    from ppc_asm.assembler.ppc import beq, ble, cmpw, lbz, lis, lwz, ori, r0, r12, r30, xoris

    if isinstance(button, DigitalButton):
        return [
            lbz(r0, button.offset, r30),
            _andi_dot(0, button.mask),
            beq("_entry_done"),
        ]
    return [
        lwz(r0, button.offset, r30),
        *([xoris(r0, r0, 0x8000)] if button.negative else []),
        lis(r12, ANALOG_THRESHOLD_BITS >> 16),
        ori(r12, r12, ANALOG_THRESHOLD_BITS & 0xFFFF),
        cmpw(0, r0, r12),
        ble("_entry_done"),
    ]


def build_entry_cave(button: AnalogDirection | DigitalButton) -> list[BaseInstruction]:
    """The hook target, called in place of ``ComputeBoostBallMovement`` with
    its arguments: r3 = CMorphBall*, r4 = const CFinalInput*,
    r5 = CStateManager*, f1 = dt. Builds the frame both caves share, then
    either branches into the body or straight to its epilogue."""
    from ppc_asm.assembler import custom_ppc
    from ppc_asm.assembler.ppc import (
        LR,
        add,
        addi,
        b,
        bgt,
        ble,
        bne,
        cmplwi,
        cmpwi,
        f1,
        lwz,
        mfspr,
        mr,
        r0,
        r1,
        r3,
        r4,
        r5,
        r12,
        r27,
        r28,
        r29,
        r30,
        r31,
        rlwinm,
        stfs,
        stmw,
        stw,
        stwu,
    )

    button_check = _button_check(button)
    button_check[0].with_label("_spring_ball_check")

    return [
        stwu(r1, -_FRAME_SIZE, r1),
        mfspr(r0, LR),
        stw(r0, _FRAME_SIZE + 4, r1),
        stmw(r27, _SAVED_REGISTERS, r1),
        stfs(f1, _DELTA_TIME, r1),
        mr(r31, r3),
        mr(r30, r4),
        mr(r29, r5),
        lwz(r28, _MORPH_BALL_PLAYER, r31),
        # r27 = &cooldowns[controller & 3]
        custom_ppc.load_address(r27, COOLDOWNS_SYMBOL),
        lwz(r0, _FINAL_INPUT_CONTROLLER, r30),
        rlwinm(r0, r0, 2, 28, 29),
        add(r27, r27, r0),
        # While cooling down, count down and skip everything else. (Not in
        # r0: as addi's base register, r0 reads as a literal 0.)
        lwz(r12, 0, r27),
        cmpwi(r12, 0),
        ble("_spring_ball_check"),
        addi(r12, r12, -1),
        stw(r12, 0, r27),
        b("_entry_done"),
        *button_check,
        lwz(r0, _MORPH_BALL_STATE, r31),
        cmplwi(r0, _BALL_STATE_BOOST),
        bgt("_entry_done"),
        lwz(r0, _MORPH_BALL_BOMB_JUMP_STATE, r31),
        cmpwi(r0, 0),
        bne("_entry_done"),
        lwz(r0, _PLAYER_MORPH_STATE, r28),
        cmpwi(r0, _MORPHED),
        bne("_entry_done"),
        lwz(r0, _PLAYER_MOVEMENT_STATE, r28),
        cmpwi(r0, _MOVEMENT_STATE_ON_GROUND),
        bne("_entry_done"),
        b(BODY_SYMBOL),
        # Conditional branches only reach +-32 KiB, and the body cave can be
        # megabytes away, so every early exit funnels through here.
        b(DONE_SYMBOL).with_label("_entry_done"),
    ]


def build_body_cave(addresses: SpringBallAddresses) -> list[BaseInstruction]:
    """The rest of the gates, the jump, the shared epilogue (labelled
    ``_done``) and the data words (``_cooldowns``, then the half-pipe
    divisor). Entered from the entry cave with its frame and registers
    live. Every branch out of here is to a fixed game address, so this can
    be assembled before the entry cave is placed."""
    from ppc_asm.assembler import custom_ppc
    from ppc_asm.assembler.ppc import (
        LR,
        Instruction,
        addi,
        b,
        beq,
        bl,
        ble,
        bne,
        cmplwi,
        cmpwi,
        f0,
        f1,
        f2,
        fadds,
        fdivs,
        lfs,
        lhz,
        li,
        lmw,
        lwz,
        mr,
        mtspr,
        r0,
        r1,
        r3,
        r4,
        r5,
        r27,
        r28,
        r29,
        r30,
        r31,
        stfs,
        stw,
    )

    return [
        lwz(r0, _PLAYER_SURFACE_RESTRAINT, r28),
        cmpwi(r0, _SURFACE_RESTRAINT_SHRUBBERY),
        beq("_done"),
        lhz(r0, _PLAYER_ATTACHED_ACTOR, r28),
        cmplwi(r0, _INVALID_UNIQUE_ID),
        bne("_done"),
        lwz(r0, _PLAYER_ENERGY_DRAIN_SOURCE_COUNT, r28),
        cmpwi(r0, 0),
        bne("_done"),
        lwz(r3, _PLAYER_STATE, r28),
        li(r4, MORPH_BALL_BOMB),
        bl(addresses.has_power_up),
        _clear_upper_bytes(r3),
        cmplwi(r3, 0),
        beq("_done"),
        mr(r3, r31),
        bl(addresses.is_movement_allowed),
        _clear_upper_bytes(r3),
        cmplwi(r3, 0),
        beq("_done"),
        # Fake bomb at exactly the point BombJump measures the ball from
        # (position + (0, 0, ball half-extent)), so the distance and
        # "bomb below the ball" checks pass whatever the tweak values are.
        mr(r3, r28),
        bl(addresses.get_tweak_player),
        bl(addresses.get_player_ball_half_extent),
        lfs(f0, _PLAYER_POSITION + 8, r28),
        fadds(f0, f0, f1),
        stfs(f0, _BOMB_POSITION + 8, r1),
        lfs(f0, _PLAYER_POSITION, r28),
        stfs(f0, _BOMB_POSITION, r1),
        lfs(f0, _PLAYER_POSITION + 4, r28),
        stfs(f0, _BOMB_POSITION + 4, r1),
        # BombJump zeroes horizontal velocity; keep it.
        lfs(f0, _PLAYER_VELOCITY, r28),
        stfs(f0, _VELOCITY, r1),
        lfs(f0, _PLAYER_VELOCITY + 4, r28),
        stfs(f0, _VELOCITY + 4, r1),
        mr(r3, r28),
        addi(r4, r1, _BOMB_POSITION),
        mr(r5, r29),
        bl(addresses.bomb_jump),
        # The half-pipe cooldown is a non-negative float, so its raw bits
        # are > 0 exactly when the float is.
        lfs(f0, _PLAYER_VELOCITY + 8, r28),
        lwz(r0, _MORPH_BALL_HALF_PIPE_COOLDOWN, r31),
        cmpwi(r0, 0),
        ble("_store_vertical"),
        custom_ppc.load_address(r3, "_half_pipe_divisor"),
        lfs(f2, 0, r3),
        fdivs(f0, f0, f2),
        stfs(f0, _VELOCITY + 8, r1).with_label("_store_vertical"),
        mr(r3, r28),
        addi(r4, r1, _VELOCITY),
        bl(addresses.set_velocity_wr),
        mr(r3, r28),
        li(r4, _MOVEMENT_STATE_FALLING_MORPHED),
        mr(r5, r29),
        bl(addresses.set_move_state),
        li(r0, COOLDOWN_FRAMES),
        stw(r0, 0, r27),
        # Epilogue: restore the hooked call's arguments and tail-branch into
        # it, so it returns straight to ComputeBallMovement.
        mr(r3, r31).with_label("_done"),
        mr(r4, r30),
        mr(r5, r29),
        lfs(f1, _DELTA_TIME, r1),
        lmw(r27, _SAVED_REGISTERS, r1),
        lwz(r0, _FRAME_SIZE + 4, r1),
        mtspr(LR, r0),
        addi(r1, r1, _FRAME_SIZE),
        b(addresses.compute_boost_ball_movement),
        Instruction(0).with_label("_cooldowns"),
        Instruction(0),
        Instruction(0),
        Instruction(0),
        Instruction(struct.unpack(">I", struct.pack(">f", HALF_PIPE_DIVISOR))[0]).with_label("_half_pipe_divisor"),
    ]


def label_offset(instructions: list[BaseInstruction], label: str) -> int:
    """Byte offset of ``label`` within ``instructions``."""
    offset = 0
    for instruction in instructions:
        if instruction.label == label:
            return offset
        offset += instruction.byte_count
    raise KeyError(label)


def apply_dol_patches(cave: CodeCaveTracker, addresses: SpringBallAddresses, button: str) -> None:
    """Requests both caves and points the hooked ``bl`` at the entry cave.

    Must run before ``CodeCaveTracker.fulfill_requests()``, i.e. from inside
    open-prime-rando's ``_apply_patches``. Refuses to patch a DOL whose hook
    site isn't the expected ``bl ComputeBoostBallMovement``, rather than
    corrupting an unknown build.
    """
    from ppc_asm import assembler
    from ppc_asm.assembler.ppc import bl

    expected = bytes(
        assembler.assemble_instructions(addresses.boost_ball_movement_call, [bl(addresses.compute_boost_ball_movement)])
    )
    actual = cave.dol_editor.read(addresses.boost_ball_movement_call, 4)
    if actual != expected:
        raise ValueError(
            f"Spring Ball hook site 0x{addresses.boost_ball_movement_call:08X} holds "
            f"{actual.hex()}, expected {expected.hex()}; this DOL isn't a supported build."
        )

    if button not in BUTTONS:
        raise ValueError(f"Unknown spring ball button {button!r}; expected one of {sorted(BUTTONS)}")

    entry = build_entry_cave(BUTTONS[button])
    body = build_body_cave(addresses)
    if assembler.byte_count(body) <= assembler.byte_count(entry):
        raise AssertionError("the spring ball body cave must be placed before the entry cave")

    symbols = cave.dol_editor.symbols

    def _with_body(address: int) -> None:
        symbols[BODY_SYMBOL] = address
        symbols[DONE_SYMBOL] = address + label_offset(body, "_done")
        symbols[COOLDOWNS_SYMBOL] = address + label_offset(body, "_cooldowns")

    def _with_entry(address: int) -> None:
        cave.dol_editor.write_instructions(addresses.boost_ball_movement_call, [bl(address)])

    cave.request_code_cave(body, _with_body)
    cave.request_code_cave(entry, _with_entry)
