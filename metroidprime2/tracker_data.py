"""Universal Tracker support: slot-data encoding of the per-seed randomized
state, so a UT regeneration reproduces the real seed's logic graph.

UT regenerates the world from ``multiworld.re_gen_passthrough[game]`` (the
slot data returned by ``MetroidPrime2World.interpret_slot_data``) but does
not have the original seed, so anything drawn from ``world.random`` -- the
starting room, door lock / elevator / portal rando, translator gate colors
and lore hologram colors -- would come out different. ``fill_slot_data``
stores each result through ``encode_randomization`` and ``generate_early``
restores it through ``decode_randomization`` instead of re-rolling.

Everything is stored as JSON-safe nested lists (slot data round-trips
through the server as JSON, so ``NodeId`` keys can't be dict keys and
tuples come back as lists).
"""

from __future__ import annotations

import importlib.resources
import json
from dataclasses import dataclass
from functools import cache
from typing import TYPE_CHECKING, Any

from . import constants
from .logic.db_reader import NodeId
from .logic.dock_rando import DockRandoAssignment

if TYPE_CHECKING:
    from . import MetroidPrime2World

SLOT_STARTING_LOCATION = "starting_location"
SLOT_TRANSLATOR_GATES = "translator_gates"
SLOT_TRANSLATOR_LORE = "translator_lore"
SLOT_DOCK_RANDO = "dock_rando"

_REQUIRED_KEYS = (SLOT_STARTING_LOCATION, SLOT_TRANSLATOR_GATES, SLOT_TRANSLATOR_LORE, SLOT_DOCK_RANDO)


@dataclass(frozen=True)
class Randomization:
    starting_location: NodeId
    translator_gates: dict[NodeId, str | None]
    translator_lore: dict[int, str]
    dock_rando: DockRandoAssignment


def _encode_node(node_id: NodeId) -> list[str]:
    return [node_id.region, node_id.area, node_id.node]


def _decode_node(raw: list[str]) -> NodeId:
    region, area, node = raw
    return NodeId(region=region, area=area, node=node)


def _encode_node_map(mapping: dict[NodeId, Any], encode_value: Any) -> list[list[Any]]:
    return [[_encode_node(key), encode_value(value)] for key, value in mapping.items()]


def _decode_node_map(raw: list[list[Any]], decode_value: Any) -> dict[NodeId, Any]:
    return {_decode_node(key): decode_value(value) for key, value in raw}


def _identity(value: Any) -> Any:
    return value


def encode_randomization(world: MetroidPrime2World) -> dict[str, Any]:
    dock_rando = world.dock_rando
    return {
        SLOT_STARTING_LOCATION: _encode_node(world.starting_location),
        SLOT_TRANSLATOR_GATES: _encode_node_map(world.translator_gate_assignment, _identity),
        SLOT_TRANSLATOR_LORE: [[strg_id, color] for strg_id, color in world.translator_lore_assignment.items()],
        SLOT_DOCK_RANDO: {
            "door_lock": _encode_node_map(dock_rando.door_lock, _identity),
            "elevator": _encode_node_map(dock_rando.elevator, _encode_node),
            "portal": _encode_node_map(dock_rando.portal, _encode_node),
            "portal_weakness": _encode_node_map(dock_rando.portal_weakness, _identity),
        },
    }


def decode_randomization(slot_data: dict[str, Any]) -> Randomization | None:
    """``None`` when ``slot_data`` predates this encoding (a seed generated
    before UT support landed) -- the caller then falls back to re-rolling,
    which is only right for seeds that left every randomized option at
    "vanilla"."""
    if not all(key in slot_data for key in _REQUIRED_KEYS):
        return None
    dock = slot_data[SLOT_DOCK_RANDO]
    return Randomization(
        starting_location=_decode_node(slot_data[SLOT_STARTING_LOCATION]),
        translator_gates=_decode_node_map(slot_data[SLOT_TRANSLATOR_GATES], _identity),
        translator_lore={int(strg_id): color for strg_id, color in slot_data[SLOT_TRANSLATOR_LORE]},
        dock_rando=DockRandoAssignment(
            door_lock=_decode_node_map(dock["door_lock"], _identity),
            elevator=_decode_node_map(dock["elevator"], _decode_node),
            portal=_decode_node_map(dock["portal"], _decode_node),
            portal_weakness=_decode_node_map(dock["portal_weakness"], _identity),
        ),
    )


# --------------------------------------------------------------------------
# Map tab (poptracker pack in ``tracker/``, built by tools/make_tracker_map.py)
# --------------------------------------------------------------------------

def _tracker_file(*parts: str) -> Any:
    ref = importlib.resources.files(__package__).joinpath("tracker")
    for part in parts:
        ref = ref.joinpath(part)
    return json.loads(ref.read_text(encoding="utf-8"))


@cache
def _area_maps() -> dict[str, dict[str, str]]:
    return _tracker_file("area_maps.json")


@cache
def _area_names() -> dict[str, dict[str, str]]:
    return _tracker_file("area_names.json")


@cache
def _map_names() -> list[str]:
    return [m["name"] for m in _tracker_file("maps", "maps.json")]


def map_page_index(data: Any) -> int:
    """UT ``map_page_index`` hook: datastorage value -> index into
    ``maps.json``. -1 (don't change tab) for anything unrecognized, so a
    missing/garbled value or a menu/loading area leaves the current tab."""
    try:
        mlvl, area = str(data).split(":")
        return _map_names().index(_area_maps()[mlvl.upper()][area])
    except (ValueError, KeyError):
        return -1


def area_region_name(mlvl: int | None, area: int | None) -> str | None:
    """Region name (e.g. "Dark Agon Wastes") for a live (MLVL, TAreaId) read,
    or None if either is unavailable or unrecognized."""
    if mlvl is None or area is None:
        return None
    return _area_maps().get(f"{mlvl:X}", {}).get(str(area))


def area_room_name(mlvl: int | None, area: int | None) -> str | None:
    """Room name (e.g. "Hall of Combat Mastery") for a live (MLVL, TAreaId)
    read, or None if either is unavailable or unrecognized."""
    if mlvl is None or area is None:
        return None
    return _area_names().get(f"{mlvl:X}", {}).get(str(area))


@cache
def _room_icons() -> dict[str, dict[str, dict[str, Any]]]:
    return _tracker_file("room_icons.json")


def _init_map_page_icons() -> None:
    """UT's ``VisualTracker`` only creates ``location_icons`` at the end of
    ``load_coords``, but calls ``update_location_icon_widgets`` (which reads
    it) whenever the ``location_setting_key`` reply arrives -- possibly before
    ``load_coords`` has finished, which raises ``AttributeError``. Called from
    the hook, which UT runs immediately before that update, to give the widget
    the empty list it expects. Best effort: no-op outside a running UT client."""
    try:
        from kivy.app import App

        page = App.get_running_app().ctx.map_page
        if page is not None and not hasattr(page, "location_icons"):
            page.location_icons = []
    except Exception:
        pass


def room_icon_coords(map_id: int | None, data: Any) -> tuple[int, int, str] | None:
    """UT ``location_icon_coords`` hook: the current room's highlight overlay
    (``tools/make_tracker_map.py`` draws one per room, sized to the map's
    ``location_icon_size``), or None -- no icon -- when the room is unknown
    or belongs to a different map than the one being viewed (auto-tab off,
    or a dark room on a light map)."""
    _init_map_page_icons()
    try:
        mlvl, area = str(data).split(":")
        icon = _room_icons()[mlvl.upper()][area]
        if map_id is None or _map_names()[map_id] != icon["map"]:
            return None
        return icon["x"], icon["y"], icon["img"]
    except (ValueError, KeyError, IndexError):
        return None


TRACKER_WORLD: dict[str, Any] = {
    "map_page_folder": "tracker",
    "map_page_maps": "maps/maps.json",
    "map_page_locations": "locations/locations.json",
    "map_page_groups": [
        ("Light Aether", ["Temple Grounds", "Great Temple", "Agon Wastes", "Torvus Bog", "Sanctuary Fortress"]),
        ("Dark Aether", ["Sky Temple Grounds", "Dark Agon Wastes", "Dark Torvus Bog", "Ing Hive"]),
        ("Sky Temple", ["Sky Temple"]),
    ],
    # UT substitutes {player} and {team}; the client formats {slot} itself.
    "map_page_setting_key": constants.AREA_DATASTORAGE_KEY.replace("{slot}", "{player}"),
    "map_page_index": map_page_index,
    # Same key: the room highlight follows the player's area too.
    "location_setting_key": constants.AREA_DATASTORAGE_KEY.replace("{slot}", "{player}"),
    "location_icon_coords": room_icon_coords,
}
