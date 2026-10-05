"""Sky Temple Key hint scans (PLAN.md section Q) and translator lore hints
(PLAN.md section R), which builds on Q's foundation.

The 9 Luminoth pillars in Sky Temple Gateway (Sky Temple Grounds), and the
22 colored Luminoth lore holograms scattered across the light regions,
each carry a SCAN that already exists in vanilla and is already tracked by
the game's own save data (``CPlayerState::SPersistentState::vec``, an
``rstl::vector<SScanState>`` -- see ``client/versions.py``'s
``SCAN_STATES_OFFSET`` for the verified offsets/layout). Scanning one to
completion (``SScanState.progress == 255``) is a plain memory read of
state the game keeps regardless of anything this world patches, so no DOL
patch is needed to detect it -- only the STRG text those SCANs point at
needs to change, which goes in through OPR's ordinary ``string_changes``
(``patch_data.py``).

This module is the data + pure-function half of that feature (mirrors
``pickup_encoding.py``'s split: no Dolphin, no live multiworld needed to
exercise ``encode_hint_scans``/``decode_hint_scans``/
``newly_completed_hints``), so it can be imported at generation time
(``patch_data.py``) and at runtime (``client/client.py``) alike.
``sky_temple_key_locations``/``translator_lore_hint_locations`` are the two
functions here that do need a real ``World``/``MultiWorld`` (they walk
``get_filled_locations()``), but they are still the single source of truth
both the hologram/pillar text (``patch_data.py``) and the slot_data hint
table (``__init__.py``) read from, so those two can never disagree about
where a hint actually points.

The generic ``{scan_id: (location_player, location_id, status)}`` shape
(``encode_hint_scans``/``decode_hint_scans``/``newly_completed_hints``) is
deliberately not Sky-Temple-Key-specific: translator lore hints (see
``TRANSLATOR_LORE_HINT_SCANS`` below) only add more entries to that same
dict -- the client path does not change, beyond grouping sends by
``(player, status)`` instead of just ``player`` (section R.1: hinting
another player's item is only legal under ``HINT_UNSPECIFIED``, so a mixed
batch needs one ``CreateHints`` call per status).
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from BaseClasses import ItemClassification
from NetUtils import HintStatus

from .item_pool import STK_ITEM_NAMES
from .options import TranslatorLoreHints

if TYPE_CHECKING:
    from BaseClasses import Location

    from . import MetroidPrime2World

# Item names translator_lore_hint_locations never picks as a hologram's
# hint target: Sky Temple Keys (always -- the 9 pillars are their own
# dedicated hint mechanism, see sky_temple_key_locations above, regardless
# of sky_temple_key_hints) and Energy Tank (indistinguishable copies --
# "one of your 14 tanks is at X" isn't actionable). Expansions are already
# filtered out via ItemClassification.skip_balancing, not by name.
_LORE_HINT_EXCLUDED_ITEM_NAMES: frozenset[str] = frozenset(STK_ITEM_NAMES) | {"Energy Tank"}

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

    room: str = ""
    """``"{region} - {area}"`` for a translator lore hologram (e.g.
    ``"Temple Grounds - Meeting Grounds"``), used only by
    ``write_spoiler`` -- left at its default for the Sky Temple Key
    pillars, which are all in the same room and don't need it."""

    translator: str = ""
    """Vanilla translator color (``"Violet"``/``"Amber"``/``"Emerald"``/
    ``"Cobalt"``, the vendored DB's ``extra.translator``) a translator lore
    hologram requires -- what ``translator_lore_rando`` reassigns (see
    ``logic/translator_gate_rando.py``'s
    ``build_translator_lore_assignment``). Left at its default for the Sky
    Temple Key pillars, which need no translator."""


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
# identical ids on NTSC/PAL (PLAN.md section Q.1). TRANSLATOR_LORE_HINT_SCANS
# below uses 22 of them; the 9 Keybearer corpses are recorded but unused.
# test_hint_scans.py guards that this stays in sync with the vendored DB (a
# resync that adds a new hint node fails loudly instead of silently missing
# an entry here) and disjoint from SKY_TEMPLE_KEY_HINT_SCANS.
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

# The 22 translator lore holograms (PLAN.md section R.1, verified
# 2026-09-26 the same way as the table above -- NOT translator gates, NOT
# the 9 Keybearer corpses; those are the other 9 entries in
# LORE_HINT_SCAN_IDS this table doesn't use). Each row's scan_id is
# LORE_HINT_SCAN_IDS[strg_id]; test_hint_scans.py guards both that
# relationship and that this set is exactly the vendored DB's hint nodes
# with an extra.translator field.
TRANSLATOR_LORE_HINT_SCANS: tuple[HintScan, ...] = (
    HintScan(
        strg_id=0x24E69725,
        scan_id=0xC108FC20,
        room="Agon Wastes - Mining Plaza",
        translator="Amber",
    ),
    HintScan(
        strg_id=0xA272E58B,
        scan_id=0x479C8E8E,
        room="Agon Wastes - Mining Station B",
        translator="Amber",
    ),
    HintScan(
        strg_id=0x5324575E,
        scan_id=0xB6CA3C5B,
        room="Agon Wastes - Mining Station A",
        translator="Amber",
    ),
    HintScan(
        strg_id=0x692E362E,
        scan_id=0x8CC05D2B,
        room="Agon Wastes - Portal Terminal",
        translator="Amber",
    ),
    HintScan(
        strg_id=0xEFBA4480,
        scan_id=0x0A542F85,
        room="Agon Wastes - Agon Energy Controller",
        translator="Amber",
    ),
    HintScan(
        strg_id=0xC3576EA5,
        scan_id=0x26B905A0,
        room="Great Temple - Main Energy Controller",
        translator="Violet",
    ),
    HintScan(
        strg_id=0xF2BF7438,
        scan_id=0x17511F3D,
        room="Sanctuary Fortress - Sanctuary Entrance",
        translator="Cobalt",
    ),
    HintScan(
        strg_id=0x0405EE3F,
        scan_id=0xE1EB853A,
        room="Sanctuary Fortress - Hall of Combat Mastery",
        translator="Cobalt",
    ),
    HintScan(
        strg_id=0xBF77D533,
        scan_id=0x5A99BE36,
        room="Sanctuary Fortress - Main Research",
        translator="Cobalt",
    ),
    HintScan(
        strg_id=0x742B0696,
        scan_id=0x91C56D93,
        room="Sanctuary Fortress - Watch Station",
        translator="Cobalt",
    ),
    HintScan(
        strg_id=0xF5535CEA,
        scan_id=0x10BD37EF,
        room="Sanctuary Fortress - Main Gyro Chamber",
        translator="Cobalt",
    ),
    HintScan(
        strg_id=0x3E0F8F4F,
        scan_id=0xDBE1E44A,
        room="Sanctuary Fortress - Sanctuary Energy Controller",
        translator="Cobalt",
    ),
    HintScan(
        strg_id=0x987884FB,
        scan_id=0x7D96EFFE,
        room="Temple Grounds - Meeting Grounds",
        translator="Violet",
    ),
    HintScan(
        strg_id=0x8E9FCFAE,
        scan_id=0x6B71A4AB,
        room="Temple Grounds - Path of Eyes",
        translator="Violet",
    ),
    HintScan(
        strg_id=0x39E3A79D,
        scan_id=0xDC0DCC98,
        room="Temple Grounds - Transport to Agon Wastes",
        translator="Violet",
    ),
    HintScan(
        strg_id=0xCF593D9A,
        scan_id=0x2AB7569F,
        room="Temple Grounds - Fortress Transport Access",
        translator="Violet",
    ),
    HintScan(
        strg_id=0x45C31C0B,
        scan_id=0xA02D770E,
        room="Torvus Bog - Path of Roots",
        translator="Emerald",
    ),
    HintScan(
        strg_id=0x54C87F8C,
        scan_id=0xB1261489,
        room="Torvus Bog - Underground Tunnel",
        translator="Emerald",
    ),
    HintScan(
        strg_id=0xD25C0D22,
        scan_id=0x37B26627,
        room="Torvus Bog - Torvus Energy Controller",
        translator="Emerald",
    ),
    HintScan(
        strg_id=0x49CD4F34,
        scan_id=0xAC232431,
        room="Torvus Bog - Gathering Hall",
        translator="Emerald",
    ),
    HintScan(
        strg_id=0x9F94AC29,
        scan_id=0x7A7AC72C,
        room="Torvus Bog - Training Chamber",
        translator="Emerald",
    ),
    HintScan(
        strg_id=0x82919C91,
        scan_id=0x677FF794,
        room="Torvus Bog - Catacombs",
        translator="Emerald",
    ),
)

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
# slot_data encoding: {scan_id: (location_player, location_id, status)}
# <-> JSON.
# --------------------------------------------------------------------------


def encode_hint_scans(entries: dict[int, tuple[int, int, int]]) -> dict[str, list[int]]:
    """``{scan_id: (location_player, location_id, status)}`` -> JSON-safe
    ``{str(scan_id): [location_player, location_id, status]}`` (slot_data
    keys must be strings; JSON has no tuples)."""
    return {
        str(scan_id): [location_player, location_id, status]
        for scan_id, (location_player, location_id, status) in entries.items()
    }


def decode_hint_scans(raw: Any) -> dict[int, tuple[int, int, int]]:
    """Inverse of ``encode_hint_scans``. Tolerates ``None``/missing (an
    older .apmp2/slot_data generated before this option existed) by
    returning ``{}`` rather than raising, and tolerates an older 2-element
    entry (before section R added a per-entry status) by defaulting its
    status to HINT_PRIORITY -- the only status Q's Sky Temple Key entries
    ever used."""
    if not raw:
        return {}
    result: dict[int, tuple[int, int, int]] = {}
    for scan_id, entry in raw.items():
        location_player, location_id = entry[0], entry[1]
        status = entry[2] if len(entry) > 2 else HintStatus.HINT_PRIORITY
        result[int(scan_id)] = (location_player, location_id, status)
    return result


def newly_completed_hints(
    scan_progress: dict[int, int],
    hint_scans: dict[int, tuple[int, int, int]],
    already_sent: set[int],
) -> tuple[set[int], dict[tuple[int, int], list[int]]]:
    """Which of ``hint_scans``' scan ids just finished scanning (``progress
    >= SCAN_COMPLETE`` in ``scan_progress``), grouped by ``(location
    player, status)`` for one or more ``CreateHints`` calls.

    Grouped by ``(player, status)`` rather than just ``player`` (as Q.5
    originally had it) because translator lore hints can name another
    player's item, and ``CreateHints`` only allows that under
    ``HINT_UNSPECIFIED`` (section R.1) -- a single tick's newly-completed
    scans can therefore need more than one ``CreateHints`` call for the
    very same player if some of that player's completed scans are
    HINT_PRIORITY (their own item) and others are HINT_UNSPECIFIED
    (someone else's).

    Ignores anything not yet complete, any scan id ``hint_scans`` doesn't
    know about (a real SCAN this player scanned that just isn't one of
    ours), and anything already in ``already_sent`` (this function is pure
    -- it doesn't mutate ``already_sent`` itself; the caller updates it
    from the returned scan-id set once the ``CreateHints`` message actually
    goes out, so a send that never happens doesn't get marked sent).
    """
    newly_completed: set[int] = set()
    locations_by_group: dict[tuple[int, int], list[int]] = {}

    for scan_id, progress in scan_progress.items():
        if progress < SCAN_COMPLETE:
            continue
        if scan_id not in hint_scans or scan_id in already_sent:
            continue
        newly_completed.add(scan_id)
        location_player, location_id, status = hint_scans[scan_id]
        locations_by_group.setdefault((location_player, status), []).append(location_id)

    for locations in locations_by_group.values():
        locations.sort()

    return newly_completed, locations_by_group


# --------------------------------------------------------------------------
# Translator lore hints (PLAN.md section R.3)
# --------------------------------------------------------------------------


def translator_lore_hint_locations(world: MetroidPrime2World) -> list[Location | None]:
    """Which filled location (if any) each of the 22 translator lore
    holograms (``TRANSLATOR_LORE_HINT_SCANS``, same index) hints at,
    computed once per world and cached on ``world._translator_lore_hints``
    -- unlike ``sky_temple_key_locations`` above, this draws from its own
    RNG (see below), so recomputing on every call would reshuffle the
    choice out from under callers that expect it pinned (``pre_output`` /
    ``generate_output`` / ``fill_slot_data`` / ``write_spoiler`` must all
    see the same 22 locations).

    ``off`` -> 22 ``None``s, no RNG draw.

    Otherwise, candidates are:
    - every filled location (real address) holding one of this player's
      own progression items, anywhere in the multiworld (``my_items`` and
      ``any`` both include these);
    - under ``any`` only, also every filled location in this player's OWN
      world holding another player's progression item (the most
      ``CreateHints`` allows a hologram to hint at someone else's item --
      see ``patch_data.py``'s Q.1/R.1 notes).

    "Progression" excludes ``skip_balancing`` items (Missile/Power Bomb/
    Dark/Light/Beam Ammo Expansions), Sky Temple Keys (the 9 pillars
    already cover them, section Q, regardless of ``sky_temple_key_hints``),
    and Energy Tanks -- all three are indistinguishable-copy bulk items
    where "one of them is at location X" isn't actionable information, and
    each ``(item owner, item name)`` is hinted at most once besides.

    Candidates are deduped and sorted by ``(location.player,
    location.address)``, shuffled, then taken in order skipping repeated
    item names, up to 22; the result is padded with ``None`` if there
    aren't enough. Sorting first means the draw only depends on which
    locations qualify, never on dict/set iteration order.

    The RNG is ``random.Random(f"{seed}:{player}:translator_lore_hints")``
    -- deliberately NOT ``world.random``, so toggling this option alone
    (leaving everything else the same) never perturbs any other option's
    random draws, i.e. the rest of the patch (OPR's own ``seed`` field,
    item placement, dock/gate rando, ...) is bit-for-bit unaffected by
    whether/how this feature is used.
    """
    if world._translator_lore_hints is not None:
        return world._translator_lore_hints

    total = len(TRANSLATOR_LORE_HINT_SCANS)
    mode = world.options.translator_lore_hints.value
    if mode == TranslatorLoreHints.option_off:
        world._translator_lore_hints = [None] * total
        return world._translator_lore_hints

    seen: set[tuple[int, int]] = set()
    candidates: list[Location] = []
    for location in world.multiworld.get_filled_locations():
        item = location.item
        if item is None or location.address is None or not item.advancement:
            continue
        if ItemClassification.skip_balancing in item.classification:
            continue
        if item.name in _LORE_HINT_EXCLUDED_ITEM_NAMES:
            continue
        own_item = item.player == world.player
        if not own_item and not (mode == TranslatorLoreHints.option_any and location.player == world.player):
            continue
        key = (location.player, location.address)
        if key in seen:
            continue
        seen.add(key)
        candidates.append(location)

    candidates.sort(key=lambda location: (location.player, location.address))

    rng = random.Random(f"{world.multiworld.seed}:{world.player}:translator_lore_hints")
    rng.shuffle(candidates)
    chosen: list[Location | None] = []
    hinted_items: set[tuple[int, str]] = set()
    for location in candidates:
        assert location.item is not None
        item_key = (location.item.player, location.item.name)
        if item_key in hinted_items:
            continue
        hinted_items.add(item_key)
        chosen.append(location)
        if len(chosen) == total:
            break
    chosen.extend([None] * (total - len(chosen)))
    world._translator_lore_hints = chosen
    return chosen
