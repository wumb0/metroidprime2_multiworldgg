"""Per-pickup SCAN assets for item scan hints (``item_scan_hints``).

Scanning a pickup completes the SCAN open-prime-rando attached to it, and the
game records that in the save's scan-state vector (the same state the Sky
Temple Key pillar hints read; see ``hint_scans.py``). But open-prime-rando
pools SCANs by their text and model, so every "Missile Expansion." pickup
shares one SCAN, and scanning any of them completes all of them. For the
pickups listed in ``options.json``'s ``item_scan_hint_indices`` this swaps in
a SCAN of its own, named by ``hint_scans.item_scan_asset_name`` so generation
can compute its asset id without running the patcher.

open-prime-rando already lists each pickup's SCAN in its world's SAVW, which
is what makes the game track it.
"""

from __future__ import annotations

import contextlib
from collections.abc import Collection
from typing import Any

from ..hint_scans import item_scan_asset_name
from ..pickup_encoding import pickup_index_for

# Uncategorized/Light Beam.SCAN, the template open-prime-rando's own
# PatcherEditor._create_scan duplicates.
_SCAN_TEMPLATE_ID = 0x7427BA3C


def create_unique_scan(editor: Any, pickup_index: int, text: str, model: int) -> int:
    """``PatcherEditor._create_scan`` for one ``(text,)`` scan without the
    pooling: a SCAN (and STRG) named after ``pickup_index``."""
    from retro_data_structures.formats.scan import Scan
    from retro_data_structures.properties.echoes.objects.ScannableObjectInfo import ScannableObjectInfo

    name = item_scan_asset_name(pickup_index).removesuffix(".SCAN")
    asset_id = editor.duplicate_asset(_SCAN_TEMPLATE_ID, f"{name}.SCAN")
    scan = editor.get_file(asset_id, Scan)
    with scan.scannable_object_info.edit_properties(ScannableObjectInfo) as info:
        info.string, _ = editor.create_strg(f"{name}.STRG", (text,))
        info.static_model = model
    return asset_id


def pickup_index_of(modification: Any) -> int | None:
    """The pickup index a patch-data pickup modification belongs to, read
    back from the single bit of one pickup counter it grants
    (``pickup_encoding.counter_and_amount``'s inverse)."""
    resources = modification.primary_stage.resources
    if len(resources) != 1:
        return None
    resource = resources[0]
    return pickup_index_for(int(resource.item), int(resource.amount))


@contextlib.contextmanager
def installed(pickup_indices: Collection[int]):
    """Gives the pickups in ``pickup_indices`` their own SCAN for the
    duration of one ``_apply_patches`` call, by wrapping
    ``pickup_editing.patch_simple_pickup`` (``pickups.patch_pickup`` looks it
    up in the module at call time) so that, while it runs for one of those
    pickups, the editor's ``create_simple_scan`` makes an unpooled SCAN."""
    from open_prime_rando.echoes.pickups import pickup_editing

    original = pickup_editing.patch_simple_pickup
    wanted = frozenset(pickup_indices)

    def _patch_simple_pickup(modification: Any, editor: Any, *args: Any, **kwargs: Any) -> None:
        pickup_index = pickup_index_of(modification)
        if pickup_index not in wanted:
            original(modification, editor, *args, **kwargs)
            return

        def _create_simple_scan(box1: str, box2: str | None = None, model: int = 0xFFFFFFFF) -> int:
            assert box2 is None, "pickup scans have a single box"
            return create_unique_scan(editor, pickup_index, box1, model)

        editor.create_simple_scan = _create_simple_scan
        try:
            original(modification, editor, *args, **kwargs)
        finally:
            del editor.create_simple_scan

    pickup_editing.patch_simple_pickup = _patch_simple_pickup
    try:
        yield
    finally:
        pickup_editing.patch_simple_pickup = original
