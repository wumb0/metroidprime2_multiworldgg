"""Client-side ISO patching for Metroid Prime 2: Echoes.

Reproduces open-prime-rando's ``echoes.patcher.patch_iso`` step by step
(rather than calling it directly) because two DOL writes per counter must
land *before* ``_apply_patches`` runs, so that its trailing
``editor.save_modifications(output, ...)`` picks them up along with every
other DOL patch it makes: persisting each of the four pickup bitmask
counters (``constants.PICKUP_COUNTER_ITEMS``, PLAN.md section P) across
saves, and giving each a large enough ``powerup_max`` that its amount can
never wrap. (Goal detection does not patch the ISO at all; it is a
client-side memory read of the current area -- see
``constants.GAME_END_AREA_INDICES``.)

Every ``open_prime_rando``/``retro_data_structures`` import in this module
is deliberately deferred into function bodies: importing this module (e.g.
for ``detect_iso_version``, or so ``worlds.metroidprime2`` can register its
Component without immediately requiring the patcher stack) must not
require open-prime-rando to be installed. Callers that do need to patch
should call ``utils.setup_libs()`` first.
"""

from __future__ import annotations

import contextlib
import json
import os
import struct
import zipfile
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from .. import constants
from ..utils import get_output_path

if TYPE_CHECKING:
    from open_prime_rando.area_patcher import AreaPatcher
    from open_prime_rando.echoes.rando_configuration import RandoConfiguration

ProgressCallback = Callable[[str, float], None]

# --------------------------------------------------------------------------
# ISO version detection
# --------------------------------------------------------------------------

_GAME_ID_NTSC = b"G2ME01"
_GAME_ID_PAL = b"G2MP01"
_GAME_ID_JAPAN = b"G2MJ01"

_NKIT_MAGIC_OFFSET = 0x200
_NKIT_MAGIC = b"NKIT"
_GCZ_MAGIC = 0xB10B


def detect_iso_version(iso_path: str | os.PathLike[str]) -> str:
    """Returns ``"NTSC"`` or ``"PAL"`` for a supported Metroid Prime 2:
    Echoes ISO, or raises ``ValueError`` explaining why it isn't one
    (wrong game, Japanese release, or a compressed/derived disc image
    format open-prime-rando's ``nod_rs`` backend cannot read -- PLAN.md
    section I / Context fact 4: NTSC-U and PAL only).
    """
    with open(iso_path, "rb") as f:
        f.seek(_NKIT_MAGIC_OFFSET)
        if f.read(len(_NKIT_MAGIC)) == _NKIT_MAGIC:
            raise ValueError("NKit images are not supported; dump a full-size raw ISO from your disc.")

        f.seek(0)
        header = f.read(6)

        if header[:3] in (b"RVZ", b"WIA"):
            image_format = header[:3].decode("ascii", errors="replace")
            raise ValueError(f"{image_format} images are not supported; dump a raw ISO from your disc.")

        if len(header) >= 2 and struct.unpack("<H", header[:2])[0] == _GCZ_MAGIC:
            raise ValueError("GCZ images are not supported; dump a raw ISO from your disc.")

        if header[:4] == b"CISO":
            raise ValueError("CISO images are not supported; dump a raw ISO from your disc.")

        game_id = header

    if game_id == _GAME_ID_NTSC:
        return "NTSC"
    if game_id == _GAME_ID_PAL:
        return "PAL"
    if game_id == _GAME_ID_JAPAN:
        raise ValueError(
            "The Japanese release of Metroid Prime 2: Echoes is not supported; use an NTSC-U or PAL ISO."
        )
    raise ValueError(f"Not a supported Metroid Prime 2: Echoes ISO (game id {game_id!r}).")


@contextlib.contextmanager
def warp_to_start_installed(dol_version: Any, starting_area: Any):
    """Context manager installing both halves of warp-to-start (see
    ``client/warp_patch.py``) for the duration of one ``_apply_patches``
    call.

    Wraps ``register_world_changes`` the same way the removed goal-trigger
    hook did; the hook is where the DOL half goes: it runs
    inside ``_apply_patches``, so the code-cave request it makes is still
    pending when ``_apply_patches`` calls
    ``editor.code_cave.fulfill_requests()``.
    """
    from open_prime_rando.echoes import patcher as opr_patcher
    from open_prime_rando.echoes.version import EchoesVersion

    from . import versions as version_tables
    from . import warp_patch

    address_tables = {
        EchoesVersion.NTSC_U: version_tables.NTSC,
        EchoesVersion.PAL: version_tables.PAL,
    }
    version_info = address_tables.get(dol_version.echoes_version)
    if version_info is None:
        raise ValueError(
            f"Warp to Start is not supported on {dol_version.description} "
            f"({dol_version.echoes_version.name}); patch an NTSC-U or PAL ISO, "
            f"or disable the Warp to Start option."
        )

    original_register_world_changes = opr_patcher.register_world_changes

    def _register_world_changes_with_warp(
        area_patcher: AreaPatcher, world_changes: list[Any]
    ) -> None:
        original_register_world_changes(area_patcher, world_changes)
        warp_patch.register(area_patcher, starting_area)
        warp_patch.apply_dol_patches(area_patcher.editor.code_cave, version_info.warp_to_start)

    opr_patcher.register_world_changes = _register_world_changes_with_warp
    try:
        yield
    finally:
        opr_patcher.register_world_changes = original_register_world_changes


@contextlib.contextmanager
def item_map_icons_always_visible():
    """Context manager: for its duration, every pickup's map icon is
    explicitly set to ``ObjectVisibility.AreaVisitOrMapStation``, matching
    open-prime-rando's own hardcoded default for pickup icons and
    implementing the player-facing ``map_visibility`` option's
    ``full_map_and_items`` value -- delivered here as ``options.json``'s
    ``show_item_locations`` flag, the internal patch-time setting derived
    from it (PLAN.md section M).

    ``ObjectVisibility.Always`` was tried first, but grepping the pinned
    open-prime-rando release shows no code path -- upstream or in
    Randovania -- ever assigns it to any mappable object, for any object
    type, in any game; every real usage only ever sets
    ``AreaVisitOrMapStation``/``AreaVisitOrMapStation2``. That makes
    ``Always`` untested territory the reverse-engineered enum names may
    not accurately describe, and matches the reported symptom (map icons
    setting enabled, no dots ever rendered). ``AreaVisitOrMapStation`` is
    open-prime-rando's own proven default for pickup icons
    (``open_prime_rando.echoes.pickups.pickup_editing._add_map_icon``, a
    ``MappableObject`` of custom ``object_type=0x12``) -- the dot shows
    once the room has been visited or a map station used, same as every
    real Randovania-generated Echoes game. OPR's own
    ``map_visibility.unvisited_map_icons`` setting does not cover these
    regardless: ``general_changes.py``'s ``objects_to_reveal`` set (the
    object types that setting forces visible) lists only Elevator/
    SaveStation/Portal/LightTeleporter/TranslatorGate/Up-DownArrow, not
    pickups.

    ``_add_map_icon`` is called from exactly one place,
    ``patch_simple_pickup`` (an unqualified global lookup resolved against
    the module's namespace at call time, the same mechanism
    ``warp_to_start_installed`` above relies on for
    ``register_world_changes``); ``patch_complex_pickup`` delegates to
    ``patch_simple_pickup``, so replacing the module attribute here covers
    every pickup regardless of stage count. The wrapper calls the original
    to append the icon exactly as before, then walks the mappable objects
    it just added (tracked by a before/after length -- the append is the
    only mutation ``_add_map_icon`` makes to ``area.mapa.mappable_objects``)
    and flips ``visibility_mode``, whose ``Field`` descriptor
    (``retro_data_structures.construct_extensions.wrapper_classes.Field``)
    has a working ``__set__``, exactly as
    ``open_prime_rando.echoes.general_changes``'s own
    ``mappable.visibility_mode = ObjectVisibility.AreaVisitOrMapStation``
    line relies on.
    """
    from open_prime_rando.echoes.pickups import pickup_editing
    from retro_data_structures.formats.mapa import ObjectVisibility

    original_add_map_icon = pickup_editing._add_map_icon

    def _add_map_icon_always_visible(editor, mlvl, area, instances) -> None:
        before = len(area.mapa.mappable_objects)
        original_add_map_icon(editor, mlvl, area, instances)
        for mappable in area.mapa.mappable_objects[before:]:
            mappable.visibility_mode = ObjectVisibility.AreaVisitOrMapStation

    pickup_editing._add_map_icon = _add_map_icon_always_visible
    try:
        yield
    finally:
        pickup_editing._add_map_icon = original_add_map_icon


# --------------------------------------------------------------------------
# Configuration loading + cosmetics
# --------------------------------------------------------------------------


def _read_apmp2_json(apmp2_file: str | os.PathLike[str], member: str) -> dict[str, Any]:
    with zipfile.ZipFile(apmp2_file) as zf:
        with zf.open(member) as f:
            return json.loads(f.read().decode("utf-8"))


def _check_pickup_encoding_compatibility(apmp2_options: dict[str, Any]) -> None:
    """PLAN.md section P's compatibility gate: the per-pickup resource
    mapping (which item/bit each pickup grants) is baked into config.json
    at *generation* time, while the DOL writes that make this client
    understand that mapping as a bitmask happen client-side at *patch*
    time. A new (bitmask-aware) client fed an old ``.apmp2`` would
    therefore patch an ISO whose pickups still use the old summed encoding
    and then misread every pickup as a bitmask -- silent divergence that
    costs location checks, so this is a hard error, not a warning.
    """
    pickup_encoding = apmp2_options.get("pickup_encoding")
    if pickup_encoding != constants.PICKUP_ENCODING_VERSION:
        raise ValueError(
            "This .apmp2 file's pickup encoding "
            f"({pickup_encoding!r}) doesn't match what this client understands "
            f"({constants.PICKUP_ENCODING_VERSION!r}). Regenerate the seed with a matching "
            "version of the metroidprime2 apworld before patching."
        )


def _load_configuration(
    apmp2_file: str | os.PathLike[str], settings: dict[str, Any]
) -> RandoConfiguration:
    """Builds the ``RandoConfiguration`` for a patch run: the generation-time
    ``config.json`` embedded in the ``.apmp2``, with client-side cosmetic
    settings (host.yaml, not known at generation time) merged in (PLAN.md
    section I/H): ``settings["hud_color"]`` (an RGB 0-255 3-tuple/list, or a
    named color already resolved by the caller) becomes
    ``hud_color.main_color`` (0.0-1.0 floats), and
    ``settings["suit_replacement"]`` (``{"varia": ..., "dark": ...,
    "light": ...}``) is passed straight through.
    """
    from open_prime_rando.echoes.rando_configuration import RandoConfiguration

    config = _read_apmp2_json(apmp2_file, "config.json")

    hud_color = settings.get("hud_color")
    if hud_color is not None:
        r, g, b = hud_color
        if isinstance(r, int) or isinstance(g, int) or isinstance(b, int):
            r, g, b = (r / 255.0, g / 255.0, b / 255.0)
        config["hud_color"] = {"main_color": [r, g, b]}

    suit_replacement = settings.get("suit_replacement")
    if suit_replacement is not None:
        config["suit_replacement"] = dict(suit_replacement)

    return RandoConfiguration.model_validate(config)


# --------------------------------------------------------------------------
# Patch entrypoint
# --------------------------------------------------------------------------


def patch_iso_with_ap(
    apmp2_file: str | os.PathLike[str],
    input_iso: str | os.PathLike[str],
    settings: dict[str, Any],
    progress: ProgressCallback | None = None,
) -> str:
    """Patches ``input_iso`` per the configuration embedded in
    ``apmp2_file`` (plus cosmetic ``settings``), writing
    ``utils.get_output_path(apmp2_file)`` and returning that path.

    Synchronous and potentially slow (this is exactly
    ``open_prime_rando.echoes.patcher.patch_iso``'s body, inlined so the
    two DOL writes can be spliced in before
    ``_apply_patches``); callers on an asyncio event loop (``client.py``,
    PLAN.md milestone M3) should run it via ``asyncio.to_thread``.

    If the output ISO already exists, patching is skipped and the existing
    path is returned unchanged (the client's ``/export_iso`` command is
    expected to delete it first to force a re-patch). On any failure during
    patching, a partially-written output file is removed before the
    exception propagates.
    """
    from open_prime_rando.dol_patching.dol_version import find_version_for_dol
    from open_prime_rando.dol_patching.echoes import dol_versions
    from open_prime_rando.echoes import patcher as opr_patcher
    from open_prime_rando.patcher_editor import IsoFileProvider, IsoFileWriter, PatcherEditor
    from retro_data_structures.game_check import Game

    apmp2_file = os.fspath(apmp2_file)
    input_iso = os.fspath(input_iso)
    output_iso = get_output_path(apmp2_file)

    if os.path.exists(output_iso):
        return output_iso

    def _report(text: str, percent: float = 0.0) -> None:
        if progress is not None:
            progress(text, percent)

    configuration = _load_configuration(apmp2_file, settings)
    # Patch-time settings that the OPR RandoConfiguration has no field for
    # (config.json is validated with extra="forbid"), so they travel in the
    # .apmp2's options.json instead. Both .get defaults keep .apmp2 files
    # produced before the respective option existed working.
    apmp2_options = _read_apmp2_json(apmp2_file, "options.json")
    _check_pickup_encoding_compatibility(apmp2_options)
    warp_to_start = bool(apmp2_options.get("warp_to_start", False))
    show_item_locations = bool(apmp2_options.get("show_item_locations", False))

    _report("Reading input ISO", 0.0)
    provider = IsoFileProvider(input_iso)  # type: ignore[arg-type]
    editor = PatcherEditor(provider, Game.ECHOES)
    output = IsoFileWriter(provider)

    dol_version = find_version_for_dol(editor.dol, dol_versions.ALL_VERSIONS)

    # Persist every pickup bitmask counter (constants.PICKUP_COUNTER_ITEMS
    # -- PLAN.md section P) across saves, and give each enough capacity
    # that its amount can never overflow. Both tables are
    # byte-per-item/u32-per-item, indexed by PlayerItemEnum value (PLAN.md
    # Context facts). A retail NTSC DOL already has
    # constants.COUNTER_MAX_CAPACITY in `powerup_max` for every one of
    # these items and 0 in `powerup_should_persist` (measured -- see
    # PLAN.md section P): the persist byte is the write that actually
    # matters, and the ceiling is rewritten only so it is guaranteed on
    # every DOL version rather than assumed from one.
    for counter_item in constants.PICKUP_COUNTER_ITEMS:
        editor.dol.write(dol_version.powerup_should_persist + counter_item, b"\x01")
        editor.dol.write(
            dol_version.powerup_max + counter_item * 4,
            struct.pack(">I", constants.COUNTER_MAX_CAPACITY),
        )

    try:
        with contextlib.ExitStack() as patches:
            if warp_to_start:
                patches.enter_context(
                    warp_to_start_installed(dol_version, configuration.starting_area)
                )
            if show_item_locations:
                patches.enter_context(item_map_icons_always_visible())
            opr_patcher._apply_patches(editor, configuration, output, _report, _report, _report)

        def _write_callback(bytes_written: int, total_bytes: int) -> None:
            _report("Writing ISO", bytes_written / total_bytes if total_bytes else 0.0)

        output.commit(output_iso, "ISO", callback=_write_callback)  # type: ignore[arg-type]
    except BaseException:
        if os.path.exists(output_iso):
            os.remove(output_iso)
        raise

    _report("Finished", 1.0)
    return output_iso


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------


def _main(argv: list[str] | None = None) -> None:
    import argparse
    import shutil

    parser = argparse.ArgumentParser(
        prog="python -m worlds.metroidprime2.client.patcher_runner",
        description="Patch a Metroid Prime 2: Echoes ISO for a MultiWorldGG .apmp2 file.",
    )
    parser.add_argument("apmp2_file", help="Path to the .apmp2 file produced by generation.")
    parser.add_argument("input_iso", help="Path to a vanilla NTSC-U or PAL Metroid Prime 2: Echoes ISO.")
    parser.add_argument("--output", default=None, help="Output ISO path (default: next to the .apmp2 file).")
    args = parser.parse_args(argv)

    detected = detect_iso_version(args.input_iso)
    print(f"Detected {detected} ISO.")  # noqa: T201 -- CLI entrypoint status output

    def _progress(text: str, percent: float) -> None:
        print(f"[{percent * 100:5.1f}%] {text}")  # noqa: T201 -- CLI entrypoint status output

    output_path = patch_iso_with_ap(args.apmp2_file, args.input_iso, {}, _progress)

    if args.output is not None and os.path.abspath(args.output) != os.path.abspath(output_path):
        shutil.move(output_path, args.output)
        output_path = args.output

    print(f"Wrote {output_path}")  # noqa: T201 -- CLI entrypoint status output


if __name__ == "__main__":
    _main()
