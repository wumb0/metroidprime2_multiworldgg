"""Item map dots: a dot on the map (and minimap) at every item location,
shown once its room has been visited or a map station has revealed it (or,
for ``map_station``, only once the map station has been used), and hidden
once the item is collected.

open-prime-rando 0.20.1 already does most of this, but no dot has ever
been drawn. For every pickup it patches, ``pickup_editing._add_map_icon``
appends a MAPA ``MappableObject`` of custom ``object_type`` 0x12, whose
editor id is a new ``TranslatorDoorLocation`` SpecialFunction that the
pickup sends ``DECR`` on collection. It also ships the dot texture
(``pickup_map_icon.TXTR``, added to every pak holding the translator gate
icon) and rebuilds each world's SAVW, which lists those SpecialFunctions
as ``unmappable_objects`` so the collected flag survives a save. The
missing piece is the renderer. ``CMappableObject::Draw`` picks an icon
texture with a switch over types 0x10..0x19, and 0x12 falls into a case
with texture -1, which draws nothing. (OPR lists the switch's jump table
as ``map_icon_jumptable`` but never uses it.)

This patch is randomprime's ``patch_set_pickup_icon_txtr`` (Metroid Prime
1) re-derived for Echoes. It points the jump table entry for 0x12 at a
small cave that loads the dot texture and then joins the translator gate
case. Translator gate icons hide themselves the same way pickups need to:
``TranslatorDoorLocation``'s ``DECR`` handler sets a per-editor-id flag in
``CMapWorldInfo``, and the translator case skips drawing when that flag is
set. The cave sets up that case's lookup arguments for the pickup's own
editor id and branches to the case's ``bl``, so the vanilla code that
follows handles the "collected" check.

Visibility is the MAPA object's ``visibility_mode``, which
``pickup_icon_visibility_installed`` sets for every pickup icon:
``MAP_STATION_OR_VISIT`` (the mode every vanilla door uses) for
``item_map_dots: on``, ``ALWAYS`` for ``always``, and a mode of our own,
``MAP_STATION``, for ``map_station``. No vanilla mode means "only once the
world's map station has been used" (``MAP_STATION_OR_VISIT`` also lets a
visited room through), so ``apply_map_station_dol_patch`` teaches
``CMappableObject::GetIsVisibleToAutoMapper`` one. Whichever mode, the game
only draws a room's icons while it draws the room itself.
"""

from __future__ import annotations

import contextlib
import struct
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterator

    from open_prime_rando.dol_patching.code_cave_tracker import CodeCaveTracker
    from ppc_asm.assembler import BaseInstruction

    from .versions import ItemMapDotAddresses


PICKUP_OBJECT_TYPE = 0x12
"""open-prime-rando's custom MAPA object type for pickups."""

ICON_JUMP_TABLE_FIRST_TYPE = 0x10
"""The object type of the icon jump table's first entry."""

PICKUP_ICON_TEXTURE = "pickup_map_icon.TXTR"
"""open-prime-rando's dot texture: 64x64 IA4, added by its
``echoes.patcher.add_pickup_map_icon``. ``resolve_asset_id`` turns the name
into the same id OPR registers it under."""

# Echoes ``CMappableObject::EVisMode`` values, read off
# ``CMappableObject::GetIsVisibleToAutoMapper`` (NTSC ``fn_800BB53C``): 0 never,
# 1 always, 2 visited/mapped/map station, 3 door visited, 4 visited.
# retro-data-structures' ``ObjectVisibility`` uses Prime 1's names for these
# values, so 2 is ``ObjectVisibility.DoorVisit`` there and OPR's hardcoded
# ``AreaVisitOrMapStation`` is actually 1 (always).

ALWAYS = 1
"""Visible whenever the room is drawn."""

MAP_STATION_OR_VISIT = 2
"""Visible once the room is visited or mapped, or (light world only) once
the world's map station has been used."""

MAP_STATION = 5
"""Our own mode, visible once the world's map station has been used and
not before, whatever has been visited. ``GetIsVisibleToAutoMapper`` answers
"always" for every mode above 4 (the end of its compare ladder), and no
vanilla MAPA object uses one (checked over both ISOs), until
``apply_map_station_dol_patch`` redirects that exit. Not a member of
retro-data-structures' ``ObjectVisibility``."""

_MAP_STATION_USED_OFFSET = 0x48
"""``CMapWorldInfo::mMapStationUsed``, a bool. It is per world, dark rooms
included: ``IsWorldVisible`` only withholds it from dark rooms for its own
purposes."""

_VISIBILITY_INFO_REGISTER = 30
"""The GPR holding the ``CMapWorldInfo&`` inside ``GetIsVisibleToAutoMapper``
(its third argument, saved to r30 on both versions)."""

_EDITOR_ID_OFFSET = 0x8
"""``CMappableObject::mObjId``."""

_LOOKUP_KEY_STACK_SLOT = 0x10
"""The Draw stack slot the translator case passes the editor id through
(the lookup's second argument is a pointer to it). The same on NTSC and PAL."""


def build_cave(addresses: ItemMapDotAddresses, texture_id: int) -> list[BaseInstruction]:
    """The jump table target for type 0x12: the translator gate case's
    argument setup with our texture in place of its own, then a branch to
    its ``bl`` so its tail decides whether to draw."""
    from ppc_asm.assembler import custom_ppc
    from ppc_asm.assembler.ppc import GeneralRegister, addi, b, lwz, or_, r0, r1, r3, r4, r30, stw

    obj = GeneralRegister(addresses.object_register)
    map_world_info = GeneralRegister(addresses.map_world_info_register)

    instructions: list[BaseInstruction] = [
        lwz(r0, _EDITOR_ID_OFFSET, obj),
        stw(r0, _LOOKUP_KEY_STACK_SLOT, r1),
        custom_ppc.load_unsigned_32bit(r30, texture_id),  # the texture Draw loads
    ]
    if addresses.map_world_info_register != 3:
        instructions.append(or_(r3, map_world_info, map_world_info))  # mr r3, map_world_info
    instructions += [
        addi(r4, r1, _LOOKUP_KEY_STACK_SLOT),
        b(addresses.flag_lookup_call),
    ]
    return instructions


def _jump_table_entry(addresses: ItemMapDotAddresses) -> int:
    return addresses.icon_jump_table + 4 * (PICKUP_OBJECT_TYPE - ICON_JUMP_TABLE_FIRST_TYPE)


def apply_dol_patches(cave: CodeCaveTracker, addresses: ItemMapDotAddresses, texture_id: int) -> None:
    """Requests the cave and points the jump table entry for type 0x12 at it.

    Must run before ``CodeCaveTracker.fulfill_requests()``. Refuses a DOL
    whose table entry or translator ``bl`` isn't exactly what's expected,
    rather than corrupting an unknown build.
    """
    from ppc_asm import assembler
    from ppc_asm.assembler.ppc import bl

    entry = _jump_table_entry(addresses)
    expected_entry = struct.pack(">I", addresses.no_icon_case)
    actual_entry = cave.dol_editor.read(entry, 4)
    if actual_entry != expected_entry:
        raise ValueError(
            f"Item map dots: jump table entry 0x{entry:08X} holds {actual_entry.hex()}, "
            f"expected {expected_entry.hex()}; this DOL isn't a supported build."
        )
    call = addresses.flag_lookup_call
    expected_call = bytes(assembler.assemble_instructions(call, [bl(addresses.object_flag_lookup)]))
    actual_call = cave.dol_editor.read(call, 4)
    if actual_call != expected_call:
        raise ValueError(
            f"Item map dots: 0x{call:08X} holds {actual_call.hex()}, expected {expected_call.hex()}; "
            f"this DOL isn't a supported build."
        )

    def _with_cave(address: int) -> None:
        cave.dol_editor.write(entry, struct.pack(">I", address))

    cave.request_code_cave(build_cave(addresses, texture_id), _with_cave)


def build_map_station_cave(addresses: ItemMapDotAddresses) -> list[BaseInstruction]:
    """The target for ``MAP_STATION``: the map station flag is the answer."""
    from ppc_asm.assembler.ppc import GeneralRegister, b, lbz, r3

    info = GeneralRegister(_VISIBILITY_INFO_REGISTER)
    return [
        lbz(r3, _MAP_STATION_USED_OFFSET, info),
        b(addresses.visibility_return),
    ]


def apply_map_station_dol_patch(cave: CodeCaveTracker, addresses: ItemMapDotAddresses) -> None:
    """Teaches ``GetIsVisibleToAutoMapper`` the ``MAP_STATION`` mode.

    The ladder's ``bge`` for modes above 4 is pointed at an unreachable
    ``b`` just after the mode-1 case (a conditional branch only reaches
    +-32 KiB, a ``b`` anywhere), and that ``b`` at a two-instruction cave.
    Every other mode takes the same path as before, so doors and the other
    two dot modes are untouched.

    Must run before ``CodeCaveTracker.fulfill_requests()``. Refuses a DOL
    whose two instructions aren't exactly what's expected.
    """
    from ppc_asm import assembler
    from ppc_asm.assembler.ppc import b, bge

    bge_address = addresses.visibility_above_four_branch
    expected_bge = bytes(assembler.assemble_instructions(bge_address, [bge(addresses.visibility_always)]))
    unused_address = addresses.visibility_unused_branch
    expected_unused = bytes(assembler.assemble_instructions(unused_address, [b(addresses.visibility_return)]))
    for address, expected in ((bge_address, expected_bge), (unused_address, expected_unused)):
        actual = cave.dol_editor.read(address, 4)
        if actual != expected:
            raise ValueError(
                f"Item map dots: 0x{address:08X} holds {actual.hex()}, expected {expected.hex()}; "
                f"this DOL isn't a supported build."
            )

    cave.dol_editor.write(bge_address, bytes(assembler.assemble_instructions(bge_address, [bge(unused_address)])))

    def _with_cave(address: int) -> None:
        cave.dol_editor.write(unused_address, bytes(assembler.assemble_instructions(unused_address, [b(address)])))

    cave.request_code_cave(build_map_station_cave(addresses), _with_cave)


@contextlib.contextmanager
def pickup_icon_visibility_installed(visibility_mode: int) -> Iterator[None]:
    """For its duration, every pickup map icon open-prime-rando adds gets
    ``visibility_mode`` (``ALWAYS``, ``MAP_STATION_OR_VISIT`` or
    ``MAP_STATION``) instead of OPR's hardcoded value.

    ``_add_map_icon`` has one call site, ``patch_simple_pickup``, which
    ``patch_complex_pickup`` delegates to. The call is an unqualified
    module-global lookup, so replacing the module attribute covers every
    pickup. Appending is the only change ``_add_map_icon`` makes to
    ``area.mapa.mappable_objects``, so everything past the old length is
    the new icon.
    """
    from open_prime_rando.echoes.pickups import pickup_editing
    from retro_data_structures.formats.mapa import ObjectVisibility

    # ``MAP_STATION`` isn't an ObjectVisibility member; the field's adapter
    # is non-strict, so the raw int round-trips.
    try:
        mode: ObjectVisibility | int = ObjectVisibility(visibility_mode)
    except ValueError:
        mode = visibility_mode

    original_add_map_icon = pickup_editing._add_map_icon

    def _add_map_icon(editor, mlvl, area, instances) -> None:
        before = len(area.mapa.mappable_objects)
        original_add_map_icon(editor, mlvl, area, instances)
        for mappable in area.mapa.mappable_objects[before:]:
            mappable.visibility_mode = mode

    pickup_editing._add_map_icon = _add_map_icon
    try:
        yield
    finally:
        pickup_editing._add_map_icon = original_add_map_icon
