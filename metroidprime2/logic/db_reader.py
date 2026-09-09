"""Parses the vendored randovania prime2 logic database
(``metroidprime2/data/logic_database``) into small, stable dataclasses.

Only the fields actually consumed elsewhere in this world are kept; see
``PLAN.md`` section C. The database is read once per process via
``load_game_database`` (``functools.lru_cache``), regardless of how many
players in a multiworld are playing Echoes.
"""

from __future__ import annotations

import functools
from dataclasses import dataclass
from typing import Any

from ..data import load_json

# --------------------------------------------------------------------------
# Ids and small value types
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class NodeId:
    region: str
    area: str
    node: str

    @property
    def ap_name(self) -> str:
        return f"{self.region}/{self.area}/{self.node}"

    @classmethod
    def from_dict(cls, region: str, data: dict) -> NodeId:
        return cls(region=data.get("region", region), area=data["area"], node=data["node"])


@dataclass(frozen=True)
class ItemResource:
    short_name: str
    long_name: str
    max_capacity: int
    item_id: int | None  # extra.item_id; >= 1000 marks a pseudo item (no in-game slot)


@dataclass(frozen=True)
class TrickResource:
    short_name: str
    long_name: str
    description: str


@dataclass(frozen=True)
class DamageReduction:
    item_short_name: str | None
    quantity: int
    multiplier: float


@dataclass(frozen=True)
class DockWeakness:
    dock_type: str
    name: str
    requirement: dict
    lock_requirement: dict | None
    lock_type: str | None
    door_type: str | None


# --------------------------------------------------------------------------
# Nodes / areas / regions
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class Node:
    id: NodeId
    node_type: str
    heal: bool
    coordinates: dict | None
    connections: dict[str, dict]

    dock_type: str | None = None
    default_connection: NodeId | None = None
    default_dock_weakness: str | None = None
    override_default_open_requirement: dict | None = None
    override_default_lock_requirement: dict | None = None

    pickup_index: int | None = None
    location_category: str | None = None
    location_data: dict | None = None
    boss: str | None = None

    event_name: str | None = None

    gate_index: int | None = None
    vanilla_actual: str | None = None
    vanilla_color: str | None = None
    gate_instances: dict | None = None

    hint_kind: str | None = None
    requirement_to_collect: dict | None = None

    teleporter_instance_id: int | None = None
    scan_asset_id: int | None = None
    dock_name: str | None = None

    @property
    def ap_name(self) -> str:
        return self.id.ap_name


@dataclass(frozen=True)
class Area:
    name: str
    region: str
    asset_id: int | None
    default_node: str | None
    nodes: dict[str, Node]


@dataclass(frozen=True)
class Region:
    name: str
    asset_id: int | None
    associated_region: str | None
    areas: dict[str, Area]


# --------------------------------------------------------------------------
# GameDatabase
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class GameDatabase:
    items: dict[str, ItemResource]
    events: dict[str, str]  # short_name -> long_name
    tricks: dict[str, TrickResource]
    damage: dict[str, str]  # short_name -> long_name
    versions: dict[str, str]  # short_name -> long_name
    misc: dict[str, str]  # short_name -> long_name
    requirement_templates: dict[str, dict]  # name -> requirement dict
    damage_reductions: dict[str, list[DamageReduction]]  # damage short_name -> reductions
    energy_tank_item: str
    dock_weaknesses: dict[tuple[str, str], DockWeakness]  # (dock_type, name) -> weakness
    regions: dict[str, Region]
    victory_condition: dict
    starting_location: NodeId

    def node(self, id: NodeId) -> Node:
        return self.regions[id.region].areas[id.area].nodes[id.node]

    def all_nodes(self):
        for region in self.regions.values():
            for area in region.areas.values():
                yield from area.nodes.values()

    def pickup_nodes(self) -> list[Node]:
        """All pickup nodes, sorted by pickup_index. Asserts indices are
        exactly 0..118 (contiguous, no gaps or duplicates)."""
        nodes = sorted(
            (n for n in self.all_nodes() if n.node_type == "pickup"),
            key=lambda n: n.pickup_index,
        )
        indices = [n.pickup_index for n in nodes]
        assert indices == list(range(len(indices))), (
            f"pickup indices are not contiguous starting at 0: {indices}"
        )
        return nodes

    def mlvl_for_region(self, name: str) -> int:
        """Resolve a region's MLVL asset id, following extra.associated_region
        for dark regions (which have no MLVL asset_id of their own)."""
        seen: set[str] = set()
        current = name
        while True:
            if current in seen:
                raise ValueError(f"associated_region cycle starting at {name!r}")
            seen.add(current)
            region = self.regions[current]
            if region.asset_id is not None:
                return region.asset_id
            if region.associated_region is None:
                raise ValueError(f"region {current!r} has neither asset_id nor associated_region")
            current = region.associated_region


# --------------------------------------------------------------------------
# Requirement tree walking (for validation)
# --------------------------------------------------------------------------


def _iter_template_names(req: Any):
    """Yield every template name referenced anywhere in a requirement tree."""
    if req is None:
        return
    if isinstance(req, dict):
        req_type = req.get("type")
        if req_type == "template":
            yield req["data"]
        elif req_type in ("and", "or"):
            for item in req["data"]["items"]:
                yield from _iter_template_names(item)
        # "resource" leaves reference no templates.


# --------------------------------------------------------------------------
# Parsing
# --------------------------------------------------------------------------


def _parse_items(raw: dict) -> dict[str, ItemResource]:
    result = {}
    for short_name, item in raw.items():
        result[short_name] = ItemResource(
            short_name=short_name,
            long_name=item["long_name"],
            max_capacity=item["max_capacity"],
            item_id=item.get("extra", {}).get("item_id"),
        )
    return result


def _parse_tricks(raw: dict) -> dict[str, TrickResource]:
    return {
        short_name: TrickResource(
            short_name=short_name,
            long_name=trick["long_name"],
            description=trick.get("description") or "",
        )
        for short_name, trick in raw.items()
    }


def _parse_name_to_long_name(raw: dict) -> dict[str, str]:
    return {short_name: entry["long_name"] for short_name, entry in raw.items()}


def _parse_damage_reductions(raw: list) -> dict[str, list[DamageReduction]]:
    result: dict[str, list[DamageReduction]] = {}
    for entry in raw:
        result[entry["name"]] = [
            DamageReduction(
                item_short_name=reduction["name"],
                quantity=reduction["quantity"],
                multiplier=reduction["multiplier"],
            )
            for reduction in entry["reductions"]
        ]
    return result


def _parse_dock_weaknesses(raw: dict) -> dict[tuple[str, str], DockWeakness]:
    result: dict[tuple[str, str], DockWeakness] = {}
    for dock_type, type_info in raw["types"].items():
        for name, item in type_info["items"].items():
            lock = item.get("lock")
            result[(dock_type, name)] = DockWeakness(
                dock_type=dock_type,
                name=name,
                requirement=item["requirement"],
                lock_requirement=lock["requirement"] if lock else None,
                lock_type=lock["lock_type"] if lock else None,
                door_type=item.get("extra", {}).get("door_type"),
            )
    return result


def _parse_node(region: str, area: str, node_name: str, raw: dict) -> Node:
    extra = raw.get("extra", {})
    default_connection = raw.get("default_connection")
    return Node(
        id=NodeId(region=region, area=area, node=node_name),
        node_type=raw["node_type"],
        heal=raw.get("heal", False),
        coordinates=raw.get("coordinates"),
        connections=raw.get("connections", {}),
        dock_type=raw.get("dock_type"),
        default_connection=NodeId.from_dict(region, default_connection) if default_connection else None,
        default_dock_weakness=raw.get("default_dock_weakness"),
        override_default_open_requirement=raw.get("override_default_open_requirement"),
        override_default_lock_requirement=raw.get("override_default_lock_requirement"),
        pickup_index=raw.get("pickup_index"),
        location_category=raw.get("location_category"),
        location_data=extra.get("location_data"),
        boss=extra.get("boss"),
        event_name=raw.get("event_name"),
        gate_index=extra.get("gate_index"),
        vanilla_actual=extra.get("vanilla_actual"),
        vanilla_color=extra.get("vanilla_color"),
        # Not present anywhere in the vendored prime2 DB today (verified:
        # no configurable_node's extra dict has a "gate_instances" key) --
        # exposed as None so the patcher side can apply its own default
        # once/if the field is ever added upstream.
        gate_instances=extra.get("gate_instances"),
        hint_kind=raw.get("kind"),
        requirement_to_collect=raw.get("requirement_to_collect"),
        teleporter_instance_id=extra.get("teleporter_instance_id"),
        scan_asset_id=extra.get("scan_asset_id"),
        dock_name=extra.get("dock_name"),
    )


def _parse_region(raw: dict) -> Region:
    region_name = raw["name"]
    extra = raw.get("extra", {})
    areas: dict[str, Area] = {}
    for area_name, area_raw in raw["areas"].items():
        area_extra = area_raw.get("extra", {})
        nodes = {
            node_name: _parse_node(region_name, area_name, node_name, node_raw)
            for node_name, node_raw in area_raw["nodes"].items()
        }
        areas[area_name] = Area(
            name=area_name,
            region=region_name,
            asset_id=area_extra.get("asset_id"),
            default_node=area_raw.get("default_node"),
            nodes=nodes,
        )
    return Region(
        name=region_name,
        asset_id=extra.get("asset_id"),
        associated_region=extra.get("associated_region"),
        areas=areas,
    )


def _validate(db: GameDatabase) -> None:
    # Every default_connection resolves to a real node.
    for node in db.all_nodes():
        if node.default_connection is not None:
            target = node.default_connection
            assert target.region in db.regions, (
                f"{node.ap_name}: default_connection region {target.region!r} does not exist"
            )
            region = db.regions[target.region]
            assert target.area in region.areas, (
                f"{node.ap_name}: default_connection area {target.area!r} does not exist"
            )
            area = region.areas[target.area]
            assert target.node in area.nodes, (
                f"{node.ap_name}: default_connection node {target.node!r} does not exist"
            )

        # Every default_dock_weakness exists.
        if node.default_dock_weakness is not None:
            key = (node.dock_type, node.default_dock_weakness)
            assert key in db.dock_weaknesses, f"{node.ap_name}: unknown dock weakness {key}"

    # Every template referenced anywhere (node connections/requirements,
    # requirement templates themselves, and dock weaknesses) exists.
    referenced_templates: set[str] = set()
    for node in db.all_nodes():
        for req in node.connections.values():
            referenced_templates.update(_iter_template_names(req))
        referenced_templates.update(_iter_template_names(node.override_default_open_requirement))
        referenced_templates.update(_iter_template_names(node.override_default_lock_requirement))
        referenced_templates.update(_iter_template_names(node.requirement_to_collect))
    for template_req in db.requirement_templates.values():
        referenced_templates.update(_iter_template_names(template_req))
    for weakness in db.dock_weaknesses.values():
        referenced_templates.update(_iter_template_names(weakness.requirement))
        referenced_templates.update(_iter_template_names(weakness.lock_requirement))
    referenced_templates.update(_iter_template_names(db.victory_condition))

    missing = referenced_templates - set(db.requirement_templates)
    assert not missing, f"requirement templates referenced but not defined: {sorted(missing)}"

    # Pickup indices are exactly 0..118, contiguous.
    db.pickup_nodes()


@functools.cache
def load_game_database() -> GameDatabase:
    header = load_json("logic_database/header.json")
    rd = header["resource_database"]

    regions: dict[str, Region] = {}
    for region_file in header["regions"]:
        relative = f"logic_database/{region_file}"
        region = _parse_region(load_json(relative))
        regions[region.name] = region

    requirement_templates = {
        name: entry["requirement"] for name, entry in rd["requirement_template"].items()
    }

    db = GameDatabase(
        items=_parse_items(rd["items"]),
        events=_parse_name_to_long_name(rd["events"]),
        tricks=_parse_tricks(rd["tricks"]),
        damage=_parse_name_to_long_name(rd["damage"]),
        versions=_parse_name_to_long_name(rd["versions"]),
        misc=_parse_name_to_long_name(rd["misc"]),
        requirement_templates=requirement_templates,
        damage_reductions=_parse_damage_reductions(rd["damage_reductions"]),
        energy_tank_item=rd["energy_tank_item_index"],
        dock_weaknesses=_parse_dock_weaknesses(header["dock_type_database"]),
        regions=regions,
        victory_condition=header["victory_condition"],
        starting_location=NodeId(
            region=header["starting_location"]["region"],
            area=header["starting_location"]["area"],
            node=header["starting_location"]["node"],
        ),
    )

    _validate(db)
    return db
