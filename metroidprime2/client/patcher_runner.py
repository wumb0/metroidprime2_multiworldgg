"""Client-side ISO patching for Metroid Prime 2: Echoes.

Reproduces open-prime-rando's ``echoes.patcher.patch_iso`` step by step
(rather than calling it directly) for two reasons (PLAN.md section I):

1. Two DOL writes must land *before* ``_apply_patches`` runs, so that its
   trailing ``editor.save_modifications(output, ...)`` picks them up along
   with every other DOL patch it makes: persisting the multiworld "magic"
   counter item (item 74) across saves, and giving it a large enough
   ``powerup_max`` that its amount can climb past 119 without wrapping.
2. A goal-detection sentinel needs to be injected into the Credits area,
   which requires wrapping ``open_prime_rando.echoes.patcher.
   register_world_changes`` for the duration of the patch (see
   ``goal_trigger_installed`` below).

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
    from open_prime_rando.patcher_editor import PatcherEditor
    from retro_data_structures.formats.mrea import Area

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


# --------------------------------------------------------------------------
# Goal-trigger sentinel (PLAN.md section J, mechanism 1)
# --------------------------------------------------------------------------

# amount - 1 >= 119 is the client's goal condition (PLAN.md section J);
# 120 is comfortably clear of the 119 real pickup indices (max amount 119)
# without depending on the exact pickup count.
_GOAL_SENTINEL_AMOUNT = 120


def _add_goal_trigger(editor: PatcherEditor, mlvl: Any, area: Area) -> None:
    """Raw ``AreaPatcher`` function (PLAN.md section J): adds a one-shot
    Timer wired to a ``SetInventoryAmount`` SpecialFunction that sets item
    74 (``PersistentCounter8``, the multiworld magic counter) to
    ``_GOAL_SENTINEL_AMOUNT`` a second after the Credits area loads. The
    client treats any magic-item amount past the real pickup range as the
    goal signal, so this needs no memory offsets (mechanism 1 of two in
    PLAN.md section J -- mechanism 2, a direct current-area memory read, is
    an optional PLAN.md M4 addition).

    Modeled directly on
    ``open_prime_rando.echoes.pickups.pickup_editing._add_modify_inventory_sf``
    (the same ``SpecialFunction(function=Function.SetInventoryAmount, ...)``
    shape used to grant pickup resources) and the looping-Timer pattern in
    ``pickup_editing.patch_complex_pickup``.
    """
    from retro_data_structures.enums.echoes import Message, PlayerItemEnum, State
    from retro_data_structures.properties.echoes.archetypes.EditorProperties import EditorProperties
    from retro_data_structures.properties.echoes.objects import SpecialFunction, Timer
    from retro_data_structures.properties.echoes.objects.SpecialFunction import Function

    layer = area.add_layer("AP Goal Trigger")

    timer = layer.add_instance_with(
        Timer(
            editor_properties=EditorProperties(name="AP Goal Timer"),
            time=1.0,
            auto_reset=False,
            auto_start=True,
        )
    )
    special_function = layer.add_instance_with(
        SpecialFunction(
            editor_properties=EditorProperties(name="AP Goal Trigger"),
            function=Function.SetInventoryAmount,
            int_parm2=_GOAL_SENTINEL_AMOUNT,
            inventory_item_parm=PlayerItemEnum.PersistentCounter8,
            sound1=-1,
            sound2=-1,
            sound3=-1,
        )
    )
    timer.add_connection(State.Zero, Message.Action, special_function)


@contextlib.contextmanager
def goal_trigger_installed():
    """Context manager: for its duration, every call to
    ``open_prime_rando.echoes.patcher.register_world_changes`` also
    registers ``_add_goal_trigger`` on the Credits area, then restores the
    original function on exit (including on exception) -- so this can
    safely wrap a single ``_apply_patches`` call without leaving the
    module patched afterwards.

    ``register_world_changes`` is called by name (an unqualified global
    lookup) from inside ``open_prime_rando.echoes.patcher._apply_patches``,
    which is resolved against the module's namespace at call time -- so
    replacing the attribute on the module object here is picked up by that
    call without needing to touch ``_apply_patches`` itself.
    """
    from open_prime_rando.echoes import patcher as opr_patcher

    original_register_world_changes = opr_patcher.register_world_changes

    def _register_world_changes_with_goal_trigger(
        area_patcher: AreaPatcher, world_changes: list[Any]
    ) -> None:
        original_register_world_changes(area_patcher, world_changes)
        area_patcher.add_raw_function(
            constants.TEMPLE_GROUNDS_MLVL,
            constants.CREDITS_MREA,
            _add_goal_trigger,
        )

    opr_patcher.register_world_changes = _register_world_changes_with_goal_trigger
    try:
        yield
    finally:
        opr_patcher.register_world_changes = original_register_world_changes


@contextlib.contextmanager
def warp_to_start_installed(dol_version: Any, starting_area: Any):
    """Context manager installing both halves of warp-to-start (see
    ``client/warp_patch.py``) for the duration of one ``_apply_patches``
    call.

    Wraps ``register_world_changes`` the same way (and for the same reason)
    as ``goal_trigger_installed``; the two nest safely, each restoring the
    function it replaced. That hook is also where the DOL half goes: it runs
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


# --------------------------------------------------------------------------
# Configuration loading + cosmetics
# --------------------------------------------------------------------------


def _read_apmp2_json(apmp2_file: str | os.PathLike[str], member: str) -> dict[str, Any]:
    with zipfile.ZipFile(apmp2_file) as zf:
        with zf.open(member) as f:
            return json.loads(f.read().decode("utf-8"))


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
    two DOL writes and ``goal_trigger_installed`` can be spliced in before
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
    # .apmp2's options.json instead. Defaulted for .apmp2 files produced
    # before the option existed.
    warp_to_start = bool(_read_apmp2_json(apmp2_file, "options.json").get("warp_to_start", False))

    _report("Reading input ISO", 0.0)
    provider = IsoFileProvider(input_iso)  # type: ignore[arg-type]
    editor = PatcherEditor(provider, Game.ECHOES)
    output = IsoFileWriter(provider)

    dol_version = find_version_for_dol(editor.dol, dol_versions.ALL_VERSIONS)

    # Persist the multiworld magic counter (item 74) across saves, and give
    # it enough capacity that its amount can exceed the 119 real pickup
    # indices (used as the goal sentinel, PLAN.md section J) without
    # overflowing. Both tables are byte-per-item/u32-per-item, indexed by
    # PlayerItemEnum value (PLAN.md Context facts).
    editor.dol.write(dol_version.powerup_should_persist + constants.MAGIC_ITEM, b"\x01")
    editor.dol.write(
        dol_version.powerup_max + constants.MAGIC_ITEM * 4,
        struct.pack(">I", 65536),
    )

    try:
        with contextlib.ExitStack() as patches:
            patches.enter_context(goal_trigger_installed())
            if warp_to_start:
                patches.enter_context(
                    warp_to_start_installed(dol_version, configuration.starting_area)
                )
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
