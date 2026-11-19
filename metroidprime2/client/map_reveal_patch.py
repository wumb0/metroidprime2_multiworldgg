"""Unvisited room names that work where vanilla's map can't show them.

``unvisited_room_names`` (open-prime-rando's ``apply_unvisited_room_names``)
makes the map screen name whichever room the cursor is on, visited or not.
That only helps for rooms the map draws and lets the cursor select, and in
vanilla two kinds of room never qualify without a visit:

* **Dark world rooms.** ``CMapWorldInfo::IsWorldVisible`` is "mapped, or the
  map station was used and the room is *not* in the dark world", so a map
  station never reveals one. Temple Grounds has about twenty of them (the
  whole Sky Temple Grounds / Ing half), the other worlds a dozen or more each.
  ``reveal_dark_rooms_on_map_station`` drops that clause so the station
  covers its whole world.
* **Great Temple.** It has no map station of its own (Temple Grounds' two
  stations set Temple Grounds' flag; each world has its own
  ``CMapWorldInfo``), so nothing but a visit ever draws its twelve rooms.
  ``great_temple_always_mapped`` marks them always drawn.

The first is the ``map_rooms_reveal_dark_world_map`` option, the second is
gated on ``unvisited_room_names``; with both off the map keeps vanilla
behaviour.

There is a third thing, and it is why the first alone never worked in
Temple Grounds. ``CScriptSpecialFunction::AcceptMapStation`` maps what the
station is *connected* to: each ``Play -> Activate`` target is a ``Teleporter``
(TEL1) whose destination area is marked mapped one by one. Only when the
station has no such connection does it set the world-wide
``CMapWorldInfo::mMapStationUsed`` flag, the one ``IsWorldVisible`` (and so
the first fix) looks at. Agon, Torvus and Sanctuary's stations have none, so
they set the flag. Temple Grounds' Hive Chamber A station has fifteen (the
``Map to Temple 0d`` ... ``Map to Hive Save 04`` teleporters, all light-world
rooms), so it never sets the flag, and the dark rooms stayed hidden however
``IsWorldVisible`` was patched. ``station_always_marks_world`` makes the
flag unconditional.
"""

from __future__ import annotations

import contextlib
import struct
from typing import TYPE_CHECKING

from .. import constants

if TYPE_CHECKING:
    from collections.abc import Iterator

    from ppc_asm.dol_file import DolEditor

    from .versions import MapRevealAddresses

_VANILLA_DARK_WORLD_CHECK = (0x57E0063E, 0x7C000034, 0x5403D97E)
"""``clrlwi r0, r31, 24; cntlzw r0, r0; srwi r3, r0, 5``: ``!inDarkWorld``."""

_VANILLA_STATION_FLAG_SITE = (
    0x57A0063F,  # clrlwi. r0, r29, 24   (r29: did any connected teleporter resolve?)
    0x40820010,  # bne     +0x10         (skip the flag if one did)
    0x807F1684,  # lwz     r3, 0x1684(r31)   (r3 = world CMapWorldInfo)
    0x38000001,  # li      r0, 1
    0x98030048,  # stb     r0, 0x48(r3)  (mMapStationUsed = true)
)
"""``AcceptMapStation``'s tail, from the test through the flag store. The
``bne`` is the second word; ``station_flag_branch`` points at it."""


def reveal_dark_rooms_on_map_station(dol_editor: DolEditor, addresses: MapRevealAddresses) -> None:
    """Makes ``IsWorldVisible`` answer true for every room of a world whose
    map station has been used, dark or not.

    The three instructions that compute ``!inDarkWorld`` become ``li r3, 1``
    and two nops; the ``b`` to the epilogue after them is untouched. Refuses a
    DOL whose three instructions aren't exactly the vanilla ones.
    """
    from ppc_asm import assembler
    from ppc_asm.assembler.ppc import li, nop, r3

    address = addresses.dark_world_check
    actual = struct.unpack(">3I", dol_editor.read(address, 12))
    if actual != _VANILLA_DARK_WORLD_CHECK:
        raise ValueError(
            f"Map reveal: 0x{address:08X} holds {dol_editor.read(address, 12).hex()}, "
            f"expected the vanilla dark world check; this DOL isn't a supported build."
        )
    dol_editor.write(address, bytes(assembler.assemble_instructions(address, [li(r3, 1), nop(), nop()])))


@contextlib.contextmanager
def great_temple_always_mapped() -> Iterator[None]:
    """For its duration, every Great Temple room (that vanilla doesn't hide
    outright) is drawn from the start.

    ``general_changes.change_map_visibility`` is registered as a global area
    function by ``_apply_patches`` through a module attribute lookup, so
    replacing the attribute covers every area.
    """
    from open_prime_rando.echoes import general_changes
    from retro_data_structures.formats.mapa import AreaVisibility

    original = general_changes.change_map_visibility

    def change_map_visibility(editor, mlvl, area, map_visibility) -> None:
        original(editor, mlvl, area, map_visibility)
        in_great_temple = mlvl is editor.get_mlvl(constants.GREAT_TEMPLE_SKY_TEMPLE_MLVL)
        if in_great_temple and area.mapa.visibility_mode != AreaVisibility.Never:
            area.mapa.visibility_mode = AreaVisibility.Always

    general_changes.change_map_visibility = change_map_visibility
    try:
        yield
    finally:
        general_changes.change_map_visibility = original


def station_always_marks_world(dol_editor: DolEditor, addresses: MapRevealAddresses) -> None:
    """Makes every map station set ``CMapWorldInfo::mMapStationUsed``, not
    only the ones with nothing connected to them (see the module docstring).

    The ``bne`` that jumps over the flag store becomes a ``nop``. Everything
    the station did before (mapping its connected teleporters' areas) still
    happens; the world flag is added on top, which is what ``IsWorldVisible``
    and ``item_map_dots: map_station`` read. Refuses a DOL whose five
    instructions around the branch aren't exactly the vanilla ones.
    """
    from ppc_asm import assembler
    from ppc_asm.assembler.ppc import nop

    first = addresses.station_flag_branch - 4
    expected = struct.pack(f">{len(_VANILLA_STATION_FLAG_SITE)}I", *_VANILLA_STATION_FLAG_SITE)
    actual = dol_editor.read(first, len(expected))
    if actual != expected:
        raise ValueError(
            f"Map station: 0x{first:08X} holds {actual.hex()}, expected {expected.hex()}; "
            f"this DOL isn't a supported build."
        )
    dol_editor.write(
        addresses.station_flag_branch,
        bytes(assembler.assemble_instructions(addresses.station_flag_branch, [nop()])),
    )
