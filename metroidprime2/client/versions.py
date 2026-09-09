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


# --------------------------------------------------------------------------
# CStateManager / CPlayerState field offsets (PLAN.md Context facts /
# section J). Constant across NTSC and PAL.
# --------------------------------------------------------------------------
PENDING_OP_OFFSET = 0x2
"""Offset of the "pending remote-execution op" flag byte from
cstate_manager_global. Non-zero means the game hasn't consumed/cleared the
last remote-execution body yet."""

CPLAYER_OFFSET = 0x14FC
"""Offset from cstate_manager_global of the (possibly null) pointer to the
current CPlayer; its first 4 bytes are the CPlayer vtable pointer."""

PLAYER_STATE_OFFSET = 0x150C
"""Offset from cstate_manager_global of the (possibly null) pointer to the
current CPlayerState, whose inventory lives at +INVENTORY_OFFSET."""

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


NTSC = EchoesVersionInfo(
    name="NTSC",
    game_id=b"G2ME01",
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
)

PAL = EchoesVersionInfo(
    name="PAL",
    game_id=b"G2MP01",
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
