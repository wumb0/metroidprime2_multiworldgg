"""Sky Temple Key hint scans (PLAN.md section Q), the foundation for a
later lore-hint feature.

The 9 Luminoth pillars in Sky Temple Gateway (Sky Temple Grounds) each
carry a SCAN that already exists in vanilla and is already tracked by the
game's own save data (``CPlayerState::SPersistentState::vec``, an
``rstl::vector<SScanState>`` -- see ``client/versions.py``'s
``SCAN_STATES_OFFSET`` for the verified offsets/layout). Scanning one to
completion (``SScanState.progress == 255``) is a plain memory read of
state the game keeps regardless of anything this world patches, so no DOL
patch is needed to detect it -- only the STRG text those 9 SCANs point at
needs to change, which goes in through OPR's ordinary ``string_changes``
(``patch_data.py``).

This module is the data + pure-function half of that feature (mirrors
``pickup_encoding.py``'s split: no Dolphin, no live multiworld needed to
exercise ``encode_hint_scans``/``decode_hint_scans``/
``newly_completed_hints``), so it can be imported at generation time
(``patch_data.py``) and at runtime (``client/client.py``) alike.
``sky_temple_key_locations`` is the one function here that does need a
real ``World``/``MultiWorld`` (it walks ``get_filled_locations()``), but
it is still the single source of truth both the pillar text
(``patch_data.py``) and the slot_data hint table (``__init__.py``) read
from, so those two can never disagree about where a key landed.

The generic ``{scan_id: (location_player, location_id)}`` shape
(``encode_hint_scans``/``decode_hint_scans``/``newly_completed_hints``) is
deliberately not Sky-Temple-Key-specific: a future lore-hint feature (see
``LORE_HINT_SCAN_IDS`` below) only adds more entries to that same dict --
the client path does not change.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from .item_pool import STK_ITEM_NAMES

if TYPE_CHECKING:
    from BaseClasses import Location

    from . import MetroidPrime2World

# --------------------------------------------------------------------------
# Sky Temple Key pillar STRG -> SCAN table (PLAN.md section Q.1, verified
# 2026-09-26 from both retail NTSC and PAL DOLs/ISOs -- do not re-derive).
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class HintScan:
    strg_id: int
    """STRG asset id this SCAN's ``ScannableObjectInfo.string`` names --
    what ``patch_data.py``'s ``string_changes`` rewrites."""

    scan_id: int
    """SCAN asset id whose ``SScanState.progress`` (in
    ``CPlayerState::SPersistentState::vec``) the client reads to detect
    completion."""


# Index n-1 is Sky Temple Key n (items.py's "Sky Temple Key 1".."Sky Temple
# Key 9", same order as randovania's echoes_items.SKY_TEMPLE_KEY_ITEMS and
# OPR's own logbook renames).
SKY_TEMPLE_KEY_HINT_SCANS: tuple[HintScan, ...] = (
    HintScan(strg_id=0xD97685FE, scan_id=0x856AD9A4),  # Sky Temple Key 1
    HintScan(strg_id=0x32413EFD, scan_id=0x6E5D62A7),  # Sky Temple Key 2
    HintScan(strg_id=0xDD8355C3, scan_id=0x819F0999),  # Sky Temple Key 3
    HintScan(strg_id=0x3F5F4EBA, scan_id=0x634312E0),  # Sky Temple Key 4
    HintScan(strg_id=0xD09D2584, scan_id=0x8C8179DE),  # Sky Temple Key 5
    HintScan(strg_id=0x3BAA9E87, scan_id=0x67B6C2DD),  # Sky Temple Key 6
    HintScan(strg_id=0xD468F5B9, scan_id=0x8874A9E3),  # Sky Temple Key 7
    HintScan(strg_id=0x2563AE34, scan_id=0x797FF26E),  # Sky Temple Key 8
    HintScan(strg_id=0xCAA1C50A, scan_id=0x96BD9950),  # Sky Temple Key 9
)

# Every lore/keybearer hint node in the vendored logic database (any node
# with node_type "hint" and an extra.string_asset_id -- 31 of them, each
# listed in its own world's SAVW) also maps 1:1 to a SAVW-tracked SCAN,
# identical ids on NTSC/PAL. Recorded now (PLAN.md
# section Q.1) so a future lore-hint feature never needs the ISO again;
# unused by runtime code for now -- test_hint_scans.py guards that it stays
# in sync with the vendored DB (a resync that adds a new hint node fails
# loudly instead of silently missing an entry here) and disjoint from
# SKY_TEMPLE_KEY_HINT_SCANS.
LORE_HINT_SCAN_IDS: dict[int, int] = {
    0x24E69725: 0xC108FC20,
    0xA272E58B: 0x479C8E8E,
    0x5324575E: 0xB6CA3C5B,
    0x692E362E: 0x8CC05D2B,
    0x150E8DB8: 0xF0E0E6BD,
    0xEFBA4480: 0x0A542F85,
    0xDE525E1D: 0x3BBC3518,
    0xC3576EA5: 0x26B905A0,
    0xF2BF7438: 0x17511F3D,
    0x62CC4DC3: 0x872226C6,
    0x0405EE3F: 0xE1EB853A,
    0xBF77D533: 0x5A99BE36,
    0xA9909E66: 0x4C7EF563,
    0x742B0696: 0x91C56D93,
    0xF5535CEA: 0x10BD37EF,
    0x3E0F8F4F: 0xDBE1E44A,
    0xE3B417BF: 0x065A7CBA,
    0x987884FB: 0x7D96EFFE,
    0x65206511: 0x80CE0E14,
    0x8E9FCFAE: 0x6B71A4AB,
    0x39E3A79D: 0xDC0DCC98,
    0x28E8C41A: 0xCD06AF1F,
    0xCF593D9A: 0x2AB7569F,
    0x58C62CB3: 0xBD2847B6,
    0x45C31C0B: 0xA02D770E,
    0x54C87F8C: 0xB1261489,
    0xD25C0D22: 0x37B26627,
    0x49CD4F34: 0xAC232431,
    0x9F94AC29: 0x7A7AC72C,
    0x82919C91: 0x677FF794,
    0x939AFF16: 0x76749413,
}

# CPlayerState's SScanState.progress is a u8; SetScanTime stores 255*t for
# a fully-scanned entry, and loading a save restores complete scans as 255
# (PLAN.md section Q.1) -- so 255 (never anything close-but-not-equal) is
# the one value that means "done".
SCAN_COMPLETE = 255


def sky_temple_key_locations(world: MetroidPrime2World) -> list[Location | None]:
    """The filled location holding each of this player's own "Sky Temple
    Key n" items, for n in 1..9 (index n-1), or None if that key never got
    a real placement to hint at all -- pre-collected via the
    ``sky_temple_keys`` option, or landed somewhere only reachable through
    an item link (PLAN.md section Q.3).

    Single source of truth for both the pillar STRG text
    (``patch_data.py``) and the slot_data hint table (``__init__.py``), so
    those two can never disagree about where a key actually is.
    """
    by_item_name: dict[str, Location] = {}
    for location in world.multiworld.get_filled_locations():
        item = location.item
        if item is None or item.player != world.player or item.name not in STK_ITEM_NAMES:
            continue
        if location.address is None:
            continue
        by_item_name[item.name] = location
    return [by_item_name.get(name) for name in STK_ITEM_NAMES]


# --------------------------------------------------------------------------
# slot_data encoding: {scan_id: (location_player, location_id)} <-> JSON.
# --------------------------------------------------------------------------


def encode_hint_scans(entries: dict[int, tuple[int, int]]) -> dict[str, list[int]]:
    """``{scan_id: (location_player, location_id)}`` -> JSON-safe
    ``{str(scan_id): [location_player, location_id]}`` (slot_data keys must
    be strings; JSON has no tuples)."""
    return {
        str(scan_id): [location_player, location_id]
        for scan_id, (location_player, location_id) in entries.items()
    }


def decode_hint_scans(raw: Any) -> dict[int, tuple[int, int]]:
    """Inverse of ``encode_hint_scans``. Tolerates ``None``/missing (an
    older .apmp2/slot_data generated before this option existed) by
    returning ``{}`` rather than raising."""
    if not raw:
        return {}
    return {int(scan_id): (location_player, location_id) for scan_id, (location_player, location_id) in raw.items()}


def newly_completed_hints(
    scan_progress: dict[int, int],
    hint_scans: dict[int, tuple[int, int]],
    already_sent: set[int],
) -> tuple[set[int], dict[int, list[int]]]:
    """Which of ``hint_scans``' scan ids just finished scanning (``progress
    >= SCAN_COMPLETE`` in ``scan_progress``), grouped by the location's
    owning player for a ``CreateHints`` call.

    Ignores anything not yet complete, any scan id ``hint_scans`` doesn't
    know about (a real SCAN this player scanned that just isn't one of
    ours), and anything already in ``already_sent`` (this function is pure
    -- it doesn't mutate ``already_sent`` itself; the caller updates it
    from the returned scan-id set once the ``CreateHints`` message actually
    goes out, so a send that never happens doesn't get marked sent).
    """
    newly_completed: set[int] = set()
    locations_by_player: dict[int, list[int]] = {}

    for scan_id, progress in scan_progress.items():
        if progress < SCAN_COMPLETE:
            continue
        if scan_id not in hint_scans or scan_id in already_sent:
            continue
        newly_completed.add(scan_id)
        location_player, location_id = hint_scans[scan_id]
        locations_by_player.setdefault(location_player, []).append(location_id)

    for locations in locations_by_player.values():
        locations.sort()

    return newly_completed, locations_by_player
