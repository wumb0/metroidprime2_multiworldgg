"""NTSC/PAL DOL address tables for Metroid Prime 2: Echoes.

Values are copied verbatim from
``open_prime_rando.dol_patching.echoes.dol_versions.ALL_VERSIONS``
(open-prime-rando v0.20.1) and ``open_prime_rando.dol_patching.
all_prime_dol_patches`` (the CStateManager/CPlayerState field offsets --
PLAN.md Context facts). This module deliberately does NOT import
``open_prime_rando``: it exists so ``client/game_interface.py`` (and
anything else that only needs to know which versions/addresses exist) can
be imported without the patcher stack installed. ``game_interface.py``
constructs the real OPR ``StringDisplayPatchAddresses``/
``PowerupFunctionsAddresses`` dataclasses from these plain values lazily,
inside methods that need them.

See PLAN.md section J deliverable 1.
"""

from __future__ import annotations

from dataclasses import dataclass

from .. import constants


@dataclass(frozen=True)
class StringDisplayAddresses:
    update_hint_state: int
    message_receiver_string_ref: int
    wstring_constructor: int
    display_hud_memo: int
    max_message_size: int


@dataclass(frozen=True)
class PowerupFunctionAddresses:
    """add_power_up changes an item's capacity; incr_pickup/decr_pickup
    change its amount (open_prime_rando.dol_patching.all_prime_dol_patches.
    PowerupFunctionsAddresses)."""

    add_power_up: int
    incr_pickup: int
    decr_pickup: int


@dataclass(frozen=True)
class WarpToStartAddresses:
    """Addresses the warp-to-start DOL gate needs (``client/warp_patch.py``).

    Both are inside ``CScriptSpecialFunction``'s save-station Think, which
    broadcasts ``State.Zero`` when the player declines the save prompt.
    Recovered by pattern matching rather than by hand -- rerun
    ``python -m metroidprime2.tools.find_warp_addresses <iso>`` to confirm
    them against a disc, or to derive them for a build not listed here.
    """

    decline_broadcast_call: int
    """The ``bl`` that broadcasts ``Zero``; replaced with a ``bl`` to the gate
    code cave."""

    send_script_msgs: int
    """That ``bl``'s original target, the SCLY state-broadcast helper. The
    cave tail-branches to it so it returns straight to the Think."""


@dataclass(frozen=True)
class SpringBallAddresses:
    """Addresses the spring ball cave needs (``client/spring_ball_patch.py``).

    Names are PrimeDecomp/echoes symbols (``config/G2ME01/symbols.txt``);
    PAL was located by matching each NTSC function's code with branch
    targets and r2/r13 offsets masked out. Rerun
    ``python -m metroidprime2.tools.find_spring_ball_addresses <iso>`` to
    confirm them against a disc.
    """

    boost_ball_argument_setup: int
    """The ``fmr f1, f31`` that starts the argument setup for
    ``bl ComputeBoostBallMovement`` in ``CMorphBall::ComputeBallMovement``;
    replaced with a ``bl`` to the cave."""

    compute_boost_ball_movement: int
    """``CMorphBall::ComputeBoostBallMovement``. Not called by the cave;
    the hook guard checks the original ``bl`` to it is intact."""

    has_power_up: int
    """``CPlayerState::HasPowerUp``."""

    is_movement_allowed: int
    """``CMorphBall::IsMovementAllowed``."""

    bomb_jump: int
    """``CPlayer::BombJump``."""

    set_velocity_wr: int
    """``CPhysicsActor::SetVelocityWR``."""

    set_move_state: int
    """``CPlayer::SetMoveState``."""


@dataclass(frozen=True)
class ItemMapDotAddresses:
    """Addresses the item map dot patch needs (``client/item_map_dots_patch.py``).

    Everything here is inside ``CMappableObject::Draw`` (unnamed in
    PrimeDecomp/echoes: NTSC ``fn_800BB924``, PAL 0x800BB9B8), whose icon
    switch covers object types 0x10..0x19 through a 10-entry jump table.
    NTSC was read off the disassembly; PAL was found through the jump table
    open-prime-rando already lists for it (``map_icon_jumptable``) and checked
    case by case against NTSC. Same code, but a different register allocation.
    """

    icon_jump_table: int
    """The icon switch's jump table, indexed by ``object_type - 0x10``."""

    no_icon_case: int
    """Where the table sends the types with no icon (0x12, 0x13, 0x16):
    texture -1, so nothing is drawn. The table entry for open-prime-rando's
    pickup type 0x12 must still point here before it's patched."""

    flag_lookup_call: int
    """The translator gate case's ``bl`` to ``object_flag_lookup``, followed
    by the case's own tail: skip drawing if the flag is set. The cave
    branches here."""

    object_flag_lookup: int
    """``CMapWorldInfo``'s per-editor-id flag lookup (NTSC ``fn_8010F654``),
    set by a ``TranslatorDoorLocation`` SpecialFunction on ``DECR``."""

    object_register: int
    """The GPR holding ``this`` (the ``CMappableObject*``) inside Draw."""

    map_world_info_register: int
    """The GPR holding the ``CMapWorldInfo&`` inside Draw; the lookup's first
    argument."""

    # ``CMappableObject::GetIsVisibleToAutoMapper`` (NTSC ``fn_800BB53C``, PAL
    # 0x800BB5D0), which Draw's caller asks about each object. It switches on
    # the object's visibility mode with a compare ladder; the ``item_map_dots:
    # map_station`` mode patch hooks the ladder's "mode above 4" exit. Same
    # code and registers on both versions, 0x94 apart.

    visibility_above_four_branch: int
    """The ladder's ``bge`` that sends every mode above 4 to
    ``visibility_always`` (vanilla uses none of them)."""

    visibility_always: int
    """The ``li r3, 1`` tail that ``visibility_above_four_branch`` targets."""

    visibility_unused_branch: int
    """A ``b visibility_return`` the compiler left unreachable, right after
    the mode-1 case. Free to take a jump."""

    visibility_return: int
    """The function's epilogue, entered with the result in r3."""


@dataclass(frozen=True)
class EchoesVersionInfo:
    name: str
    game_id: bytes
    build_string_address: int
    build_string: bytes
    game_state_pointer: int
    cplayer_vtable: int
    cstate_manager_global: int
    string_display: StringDisplayAddresses
    powerup_functions: PowerupFunctionAddresses
    powerup_should_persist: int
    powerup_max: int
    warp_to_start: WarpToStartAddresses
    spring_ball: SpringBallAddresses
    item_map_dots: ItemMapDotAddresses
    player_freeze: int
    """``CPlayer::Freeze(float timeout, CStateManager&, CAssetId steamTexture,
    uint sfx, CAssetId iceTexture)`` (NTSC symbol ``Freeze__7CPlayerFfR13
    CStateManagerUiUiUi``). Both vanilla callers pass ``-1`` for the two
    textures and the 16-bit "no sfx" constant (``0xFFFF``) for the sound, which
    selects the player's built-in resources. PAL was found by matching the
    NTSC function with SDA/branch operands masked (only the two string-table
    ``addi`` immediates differ)."""


# --------------------------------------------------------------------------
# CStateManager / CPlayerState field offsets (PLAN.md Context facts /
# section J). Constant across NTSC and PAL.
# --------------------------------------------------------------------------
PENDING_OP_OFFSET = 0x2
"""Offset of the "pending remote-execution op" flag byte from
cstate_manager_global. Non-zero means the game hasn't consumed/cleared the
last remote-execution body yet."""

FROZEN_TIMEOUT_OFFSET = 0x1158
"""Offset from a CPlayer pointer of ``mFrozenTimeout`` (float seconds left;
``CPlayer::GetFrozenState`` is ``> 0``). ``UpdateFrozenState`` subtracts the
frame delta from it each frame and breaks the freeze at 0, or earlier if the
player mashes jump. Identical on NTSC and PAL."""

CPLAYER_OFFSET = 0x14FC
"""Offset from cstate_manager_global of the (possibly null) pointer to the
current CPlayer; its first 4 bytes are the CPlayer vtable pointer."""

PLAYER_STATE_OFFSET = 0x150C
"""Offset from cstate_manager_global of the (possibly null) pointer to the
current CPlayerState, whose inventory lives at +INVENTORY_OFFSET."""

AREA_ID_OFFSET = 0x16A0
"""Offset from cstate_manager_global of the current area's TAreaId
(CStateManager::m_nextAreaId), an *index* into the current MLVL's area list
rather than the MREA asset id. Set by CStateManager::SetCurrentAreaId, whose
shipped NTSC DOL body (0x80041728) moves the previous value to +0x16A4 and
stores the new id at +0x16A0. Used for goal detection
(constants.GAME_END_AREA_INDICES)."""

INVENTORY_OFFSET = 0x5C
"""Offset from a CPlayerState pointer of its 109-entry inventory array
(0x58 rstl::vector header + 0x4 vector data pointer offset, per
randovania's EchoesRemoteConnector.powerup_offset(0))."""

INVENTORY_ITEM_SIZE = 0xC
"""Bytes per inventory entry: amount (u32), capacity (u32), padding (u32)."""

INVENTORY_ITEM_COUNT = 109
"""Number of PlayerItemEnum inventory slots."""

HEALTH_OFFSET = 0x14
"""Offset from a CPlayerState pointer of the current-health float
(CHealthInfo::healthB, read by ``CPlayerState::CalculateHealth``/written by
``CHealthInfo::SetHP``). Constant across NTSC and PAL -- struct layout
doesn't change between regions, only absolute code/data addresses do.
Verified against a real shipped patch, not derived: open_prime_rando's
``all_prime_dol_patches.apply_reverse_energy_tank_heal_patch`` hardcodes
``health_offset = 0x14`` for ``Game.ECHOES`` to directly ``stfs`` into this
same field from inside ``incr_pickup``'s own compiled code (PLAN.md
Context; see also PrimeDecomp/echoes's CPlayerState.hpp/CHealthInfo.hpp,
which place ``healthInfo`` at CPlayerState+0x10 and ``healthB`` at
HealthInfo+0x4, the same 0x14 total)."""

ALIVE_OFFSET = 0x4
"""Offset from a CPlayerState pointer of the byte holding the
``bool alive : 1`` bitfield (``CPlayerState::IsPlayerAlive()``) -- a flag
distinct from ``HEALTH_OFFSET``'s health float. Per PrimeDecomp/echoes's
CPlayerState.hpp, ``alive`` and the adjacent ``bool firingComboBeam : 1``
are the only members between ``int playerIndex`` (0x0-0x4) and
``uint enabledItems`` (verified at CPlayerState+0x8, since ``EBeamId
currentBeam`` at +0xC and ``CHealthInfo healthInfo`` at +0x10 must hold for
``HEALTH_OFFSET`` (healthInfo+0x4) to land on 0x14), so they're packed into
a single byte at +0x4. ``ALIVE_BIT_MASK`` assumes CodeWarrior packs the
first-declared bitfield into the storage unit's high bit (matching
``worlds/metroidprime``'s Prime 1 alive-bit convention, bit 31 of its
4-byte storage unit) -- NOT confirmed against a live game, since no
decompiled function in PrimeDecomp/echoes yet sets this field to false to
check against. If DeathLink still doesn't trigger a real death after this
change, this bit position is the first thing to re-derive empirically."""

ALIVE_BIT_MASK = 0x80
"""High bit of the ``ALIVE_OFFSET`` byte; see ``ALIVE_OFFSET`` docstring
for the (unconfirmed) reasoning."""

SCAN_STATES_OFFSET = 0x5A0
"""Offset from a CPlayerState pointer of its scan-state vector header
(PLAN.md section Q.1, disassembled from both retail NTSC and PAL DOLs):
``CPlayerState::ScanStates()`` is ``addi r3,r3,0x59C; blr`` (NTSC
0x800851DC, PAL 0x80085318) -- the ``rstl::vector<SScanState>`` itself, at
CPlayerState+0x59C -- and ``GetScanTime`` (NTSC 0x80085068, PAL 0x800851A4)
reads the element count from +0x5A0 and the data pointer from +0x5A8,
indexing with a stride-8 (``slwi 3``) multiply and reading ``SScanState``'s
u8 progress field at element+4. So, from a CPlayerState pointer: count at
``SCAN_STATES_OFFSET`` (+0x5A0), capacity at +0x5A4, data pointer at +0x5A8.
Each ``SScanState`` is 8 bytes: ``u32 scan_asset_id; u8 progress; u8 flag;
pad[2]``, sorted ascending by id. ``progress == 255`` means the scan is
complete (``SetScanTime`` stores ``255*t``; loading a save restores
complete scans as 255) -- see ``hint_scans.SCAN_COMPLETE``."""

SCAN_STATE_SIZE = 8
"""Bytes per ``SScanState`` entry -- see ``SCAN_STATES_OFFSET``."""

SCAN_STATES_MAX_COUNT = 2048
"""Sanity cap on the scan-state vector's element count (retail has ~820
entries fully unlocked); a count above this from
``read_scan_progress`` means the pointer/offsets are wrong, not a
legitimately huge save."""


NTSC = EchoesVersionInfo(
    name="NTSC",
    # open_prime_rando.echoes.patcher.patch_game_name_and_id unconditionally
    # overwrites the disc header's maker code with "NR" (giving the
    # randomized build its own save slot, distinct from vanilla), so a
    # patched disc's in-memory game id is "G2MENR", not the unpatched
    # "G2ME01".
    game_id=b"G2MENR",
    build_string_address=0x803AC3B0,
    build_string=b"!#$MetroidBuildInfo!#$Build v1.028 10/18/2004 10:44:32",
    game_state_pointer=0x80418EB8,
    cplayer_vtable=0x803B15D0,
    cstate_manager_global=0x803DB6E0,
    string_display=StringDisplayAddresses(
        update_hint_state=0x80038020,
        message_receiver_string_ref=0x803BD118,
        wstring_constructor=0x802FF3DC,
        display_hud_memo=0x8006B3C8,
        max_message_size=200,
    ),
    powerup_functions=PowerupFunctionAddresses(
        add_power_up=0x800858F0,
        incr_pickup=0x80085760,
        decr_pickup=0x800856C4,
    ),
    powerup_should_persist=0x803A743C,
    powerup_max=0x803A7288,
    warp_to_start=WarpToStartAddresses(
        decline_broadcast_call=0x80105ABC,
        send_script_msgs=0x80047FF0,
    ),
    spring_ball=SpringBallAddresses(
        boost_ball_argument_setup=0x800CE8BC,
        compute_boost_ball_movement=0x800C6B78,
        has_power_up=0x80085480,
        is_movement_allowed=0x800CE7D0,
        bomb_jump=0x80186838,
        set_velocity_wr=0x800EA404,
        set_move_state=0x80187370,
    ),
    item_map_dots=ItemMapDotAddresses(
        icon_jump_table=0x803B3638,
        no_icon_case=0x800BBAE0,
        flag_lookup_call=0x800BBACC,
        object_flag_lookup=0x8010F654,
        object_register=9,
        map_world_info_register=3,
        visibility_above_four_branch=0x800BB5C8,
        visibility_always=0x800BB644,
        visibility_unused_branch=0x800BB5D8,
        visibility_return=0x800BB648,
    ),
    player_freeze=0x800144A4,
)

PAL = EchoesVersionInfo(
    name="PAL",
    # See NTSC's game_id comment above -- same "NR" maker-code rewrite.
    game_id=b"G2MPNR",
    build_string_address=0x803AD710,
    build_string=b"!#$MetroidBuildInfo!#$Build v1.035 10/27/2004 19:48:17",
    game_state_pointer=0x8041A19C,
    cplayer_vtable=0x803B2950,
    cstate_manager_global=0x803DC900,
    string_display=StringDisplayAddresses(
        update_hint_state=0x80038194,
        message_receiver_string_ref=0x803BE378,
        wstring_constructor=0x802FF734,
        display_hud_memo=0x8006B504,
        max_message_size=200,
    ),
    powerup_functions=PowerupFunctionAddresses(
        add_power_up=0x80085A2C,
        incr_pickup=0x8008589C,
        decr_pickup=0x80085800,
    ),
    powerup_should_persist=0x803A7B94,
    powerup_max=0x803A79E0,
    warp_to_start=WarpToStartAddresses(
        decline_broadcast_call=0x80105C70,
        send_script_msgs=0x80048160,
    ),
    spring_ball=SpringBallAddresses(
        boost_ball_argument_setup=0x800CE994,
        compute_boost_ball_movement=0x800C6C50,
        has_power_up=0x800855BC,
        is_movement_allowed=0x800CE8A8,
        bomb_jump=0x80186B1C,
        set_velocity_wr=0x800EA4EC,
        set_move_state=0x80187658,
    ),
    item_map_dots=ItemMapDotAddresses(
        icon_jump_table=0x803B4A80,
        no_icon_case=0x800BBB70,
        flag_lookup_call=0x800BBB5C,
        object_flag_lookup=0x8010F808,
        object_register=28,
        map_world_info_register=29,
        visibility_above_four_branch=0x800BB65C,
        visibility_always=0x800BB6D8,
        visibility_unused_branch=0x800BB66C,
        visibility_return=0x800BB6DC,
    ),
    player_freeze=0x80014540,
)

VERSIONS: tuple[EchoesVersionInfo, ...] = (NTSC, PAL)


# --------------------------------------------------------------------------
# Known MLVL ids: the 5 world MLVLs (already vendored as
# constants.REGION_MLVL_IDS) plus the two FrontEnd (title screen / main
# menu) MLVLs, so EchoesInterface.is_in_game() can tell "actually playing"
# apart from "sitting at the menu" using only the current MLVL id.
# --------------------------------------------------------------------------
_FRONTEND_MLVL_NTSC = 0x69802220
_FRONTEND_MLVL_PAL = 0x7B6EAA68

KNOWN_MLVLS: dict[int, str] = {
    **dict.fromkeys(constants.REGION_MLVL_IDS, "world"),
    _FRONTEND_MLVL_NTSC: "menu",
    _FRONTEND_MLVL_PAL: "menu",
}
