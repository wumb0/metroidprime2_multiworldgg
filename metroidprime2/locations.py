"""Location table for Metroid Prime 2: Echoes.

Built directly from the vendored randovania logic database's 119 pickup
nodes (see ``logic/db_reader.py``), in ``pickup_index`` order, so that
``LOCATION_TABLE[i].pickup_index == i`` for every entry.
"""

from __future__ import annotations

from dataclasses import dataclass

from BaseClasses import Location

from . import constants
from .logic.db_reader import load_game_database


@dataclass(frozen=True)
class LocationData:
    name: str
    code: int
    pickup_index: int
    node_id: str  # NodeId.ap_name of the source pickup node, e.g. "Region/Area/Pickup (X)"
    region: str
    area: str
    boss: str | None  # None, "guardian", or "sub-guardian"
    mlvl_id: int
    mrea_id: int
    location_category: str | None  # "major" or "minor" per randovania


class MetroidPrime2Location(Location):
    game = "Metroid Prime 2: Echoes"


def _build_location_table() -> list[LocationData]:
    db = load_game_database()
    table: list[LocationData] = []
    for node in db.pickup_nodes():
        region = db.regions[node.id.region]
        area = region.areas[node.id.area]
        mrea_id = area.asset_id
        assert mrea_id is not None, f"{node.ap_name}: area has no MREA asset_id"
        table.append(
            LocationData(
                name=f"{node.id.region}: {node.id.area} - {node.id.node}",
                code=constants.LOCATION_ID_BASE + node.pickup_index,
                pickup_index=node.pickup_index,
                node_id=node.ap_name,
                region=node.id.region,
                area=node.id.area,
                boss=node.boss,
                mlvl_id=db.mlvl_for_region(node.id.region),
                mrea_id=mrea_id,
                location_category=node.location_category,
            )
        )
    return table


LOCATION_TABLE: list[LocationData] = _build_location_table()

assert len(LOCATION_TABLE) == 119, f"expected 119 pickup locations, got {len(LOCATION_TABLE)}"
assert [loc.pickup_index for loc in LOCATION_TABLE] == list(range(119)), (
    "LOCATION_TABLE is not indexed contiguously by pickup_index"
)

_names = [loc.name for loc in LOCATION_TABLE]
assert len(_names) == len(set(_names)), "duplicate location names in LOCATION_TABLE"
del _names

_codes = [loc.code for loc in LOCATION_TABLE]
assert len(_codes) == len(set(_codes)), "duplicate location codes in LOCATION_TABLE"
del _codes

location_name_to_id: dict[str, int] = {loc.name: loc.code for loc in LOCATION_TABLE}

# --------------------------------------------------------------------------
# Location groups
# --------------------------------------------------------------------------


def _build_location_groups() -> dict[str, set[str]]:
    db = load_game_database()
    groups: dict[str, set[str]] = {
        "Boss": {loc.name for loc in LOCATION_TABLE if loc.boss},
        "Guardian": {loc.name for loc in LOCATION_TABLE if loc.boss == "guardian"},
    }
    # One group per DB region name (may be empty, e.g. Sky Temple has no
    # pickup nodes of its own).
    for region_name in db.regions:
        groups[region_name] = set()
    for loc in LOCATION_TABLE:
        groups[loc.region].add(loc.name)
    return groups


LOCATION_GROUPS: dict[str, set[str]] = _build_location_groups()

assert len(LOCATION_GROUPS["Boss"]) == 9, f"expected 9 boss locations, got {len(LOCATION_GROUPS['Boss'])}"
assert len(LOCATION_GROUPS["Guardian"]) == 3, (
    f"expected 3 guardian locations, got {len(LOCATION_GROUPS['Guardian'])}"
)
