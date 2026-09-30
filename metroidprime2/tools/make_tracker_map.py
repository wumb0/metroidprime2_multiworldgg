"""Builds the Universal Tracker map pack in ``metroidprime2/tracker/``:
one schematic top-down map image per logic-database region, a poptracker
``maps.json`` / ``locations.json`` placing every pickup location on its map,
and ``area_maps.json`` (which map tab a given in-game area belongs to, for
auto-tabbing).

The maps are drawn from room geometry (each room's bounding box), not game
art, so nothing copyrighted ships in the apworld. Run from the repo root::

    python metroidprime2/tools/make_tracker_map.py              # redraw from committed bounds
    python metroidprime2/tools/make_tracker_map.py --iso echoes.iso   # re-extract bounds first

``tools/room_bounds.json`` holds the extracted bounds: for every area, its
world-space AABB (MLVL ``area_bounding_box`` + ``area_transform``
translation), its index in the MLVL's area list (what the client reads as
the current area id), and its MLVL. Pickup coordinates in the logic database
are in the same world frame.

Pickup location names follow ``locations.py`` (``"<region>: <area> - <node>"``)
-- UT matches a poptracker section's ``name`` against AP location names
exactly.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

PACKAGE = Path(__file__).resolve().parents[1]
DB_DIR = PACKAGE / "data" / "logic_database"
BOUNDS_FILE = Path(__file__).resolve().parent / "room_bounds.json"
OUT_DIR = PACKAGE / "tracker"

# (group, region) in tab order. Group names become the dropdown's headings.
GROUPS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("Light Aether", ("Temple Grounds", "Great Temple", "Agon Wastes", "Torvus Bog", "Sanctuary Fortress")),
    ("Dark Aether", ("Sky Temple Grounds", "Dark Agon Wastes", "Dark Torvus Bog", "Ing Hive")),
    ("Sky Temple", ("Sky Temple",)),
)
DARK_REGIONS = frozenset({"Sky Temple Grounds", "Dark Agon Wastes", "Dark Torvus Bog", "Ing Hive"})

IMAGE_LONG_SIDE = 1800
PADDING = 60
LOCATION_SIZE = 26
LOCATION_BORDER = 3


def slug(region: str) -> str:
    return region.lower().replace(" ", "_")


def load_db() -> dict[str, dict]:
    return {
        path.stem: json.loads(path.read_text(encoding="utf-8"))
        for path in sorted(DB_DIR.glob("*.json"))
        if path.stem != "header"
    }


# --------------------------------------------------------------------------
# Bounds extraction (needs the ISO)
# --------------------------------------------------------------------------


def _region_mlvl(db: dict[str, dict], region: str) -> int:
    extra = db[region]["extra"]
    if "asset_id" in extra:
        return extra["asset_id"]
    return _region_mlvl(db, extra["associated_region"])


def extract_bounds(iso: Path, db: dict[str, dict]) -> dict:
    from open_prime_rando.patcher_editor import PatcherEditor
    from retro_data_structures.file_provider import IsoFileProvider
    from retro_data_structures.game_check import Game

    editor = PatcherEditor(IsoFileProvider(iso), Game.ECHOES)
    result: dict[str, dict] = {}
    for region, data in db.items():
        mlvl_id = _region_mlvl(db, region)
        mlvl = editor.get_mlvl(mlvl_id)
        raw_index = {raw["area_mrea_id"]: (index, raw) for index, raw in enumerate(mlvl.raw.areas)}
        areas: dict[str, dict] = {}
        for area_name, area in data["areas"].items():
            index, raw = raw_index[area["extra"]["asset_id"]]
            t, bb = list(raw["area_transform"]), list(raw["area_bounding_box"])
            tx, ty, tz = t[3], t[7], t[11]
            areas[area_name] = {
                "index": index,
                "bounds": [
                    round(bb[0] + tx, 1),
                    round(bb[1] + ty, 1),
                    round(bb[2] + tz, 1),
                    round(bb[3] + tx, 1),
                    round(bb[4] + ty, 1),
                    round(bb[5] + tz, 1),
                ],
            }
        result[region] = {"mlvl": f"{mlvl_id:X}", "areas": areas}
    return result


# --------------------------------------------------------------------------
# Drawing
# --------------------------------------------------------------------------


class Projection:
    def __init__(self, areas: dict[str, dict]) -> None:
        boxes = [a["bounds"] for a in areas.values()]
        self.min_x = min(b[0] for b in boxes)
        self.max_x = max(b[3] for b in boxes)
        self.min_y = min(b[1] for b in boxes)
        self.max_y = max(b[4] for b in boxes)
        self.min_z = min(b[2] for b in boxes)
        self.max_z = max(b[5] for b in boxes)
        self.scale = IMAGE_LONG_SIDE / max(self.max_x - self.min_x, self.max_y - self.min_y)
        self.width = round((self.max_x - self.min_x) * self.scale) + 2 * PADDING
        self.height = round((self.max_y - self.min_y) * self.scale) + 2 * PADDING

    def point(self, x: float, y: float) -> tuple[int, int]:
        # Metroid's +Y is "north"; image Y grows downward.
        return (
            round((x - self.min_x) * self.scale) + PADDING,
            round((self.max_y - y) * self.scale) + PADDING,
        )

    def height_color(self, z: float, dark: bool) -> tuple[int, int, int]:
        span = max(self.max_z - self.min_z, 1.0)
        t = max(0.0, min(1.0, (z - self.min_z) / span))
        low, high = ((70, 90, 200), (220, 90, 200)) if dark else ((40, 150, 190), (230, 170, 60))
        return tuple(round(low[i] + (high[i] - low[i]) * t) for i in range(3))  # type: ignore[return-value]


def _wrap_label(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.FreeTypeFont, max_width: float) -> str | None:
    if draw.textlength(text, font=font) <= max_width:
        return text
    words = text.split()
    for split in range(1, len(words)):
        candidate = " ".join(words[:split]) + "\n" + " ".join(words[split:])
        if max(draw.textlength(line, font=font) for line in candidate.split("\n")) <= max_width:
            return candidate
    return None


def draw_map(region: str, areas: dict[str, dict], projection: Projection) -> Image.Image:
    dark = region in DARK_REGIONS
    # RGB base: ImageDraw only alpha-blends translucent fills onto RGB images.
    image = Image.new("RGB", (projection.width, projection.height), (26, 18, 36) if dark else (18, 22, 30))
    draw = ImageDraw.Draw(image, "RGBA")
    title_font = ImageFont.load_default(size=34)
    label_font = ImageFont.load_default(size=15)

    grid = 100
    x = (projection.min_x // grid + 1) * grid
    while x < projection.max_x:
        px, _ = projection.point(x, 0)
        draw.line([(px, PADDING // 2), (px, projection.height - PADDING // 2)], fill=(255, 255, 255, 14), width=1)
        x += grid
    y = (projection.min_y // grid + 1) * grid
    while y < projection.max_y:
        _, py = projection.point(0, y)
        draw.line([(PADDING // 2, py), (projection.width - PADDING // 2, py)], fill=(255, 255, 255, 14), width=1)
        y += grid

    ordered = sorted(areas.items(), key=lambda item: item[1]["bounds"][2])
    for _, area in ordered:
        b = area["bounds"]
        x0, y1 = projection.point(b[0], b[1])
        x1, y0 = projection.point(b[3], b[4])
        color = projection.height_color((b[2] + b[5]) / 2, dark)
        draw.rectangle((x0, y0, x1, y1), fill=(*color, 55), outline=(*color, 200), width=2)
    for name, area in ordered:
        b = area["bounds"]
        x0, y1 = projection.point(b[0], b[1])
        x1, y0 = projection.point(b[3], b[4])
        label = _wrap_label(draw, name, label_font, (x1 - x0) - 6)
        if label is not None:
            draw.multiline_text(
                ((x0 + x1) / 2, (y0 + y1) / 2),
                label,
                font=label_font,
                fill=(255, 255, 255, 190),
                anchor="mm",
                align="center",
            )
    draw.text((PADDING // 2, 8), region, font=title_font, fill=(255, 255, 255, 230))
    return image


# --------------------------------------------------------------------------
# Pack JSON
# --------------------------------------------------------------------------


def pickup_nodes(db: dict[str, dict], region: str) -> list[tuple[str, str, dict]]:
    return [
        (area_name, node_name, node)
        for area_name, area in db[region]["areas"].items()
        for node_name, node in area["nodes"].items()
        if node["node_type"] == "pickup"
    ]


def build_locations(db: dict[str, dict], region: str, projection: Projection) -> dict:
    used: set[tuple[int, int]] = set()
    by_area: dict[str, list[dict]] = {}
    for area_name, node_name, node in pickup_nodes(db, region):
        c = node["coordinates"]
        px, py = projection.point(c["x"], c["y"])
        # UT keys a map dot by its (x, y); two pickups sharing one pixel would
        # collapse into a single dot, so nudge later ones apart.
        while (px, py) in used:
            px += LOCATION_SIZE // 2
        used.add((px, py))
        location_name = f"{region}: {area_name} - {node_name}"
        by_area.setdefault(area_name, []).append(
            {
                "name": location_name,
                "sections": [{"name": location_name}],
                "map_locations": [{"map": region, "x": px, "y": py}],
            }
        )
    return {"name": region, "children": [{"name": area, "children": locs} for area, locs in by_area.items()]}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--iso", type=Path, help="Echoes ISO; re-extracts tools/room_bounds.json first")
    args = parser.parse_args()

    db = load_db()
    if args.iso:
        bounds = extract_bounds(args.iso, db)
        BOUNDS_FILE.write_text(json.dumps(bounds, indent=1), encoding="utf-8")
        print(f"wrote {BOUNDS_FILE}")
    bounds = json.loads(BOUNDS_FILE.read_text(encoding="utf-8"))

    (OUT_DIR / "images").mkdir(parents=True, exist_ok=True)
    (OUT_DIR / "maps").mkdir(exist_ok=True)
    (OUT_DIR / "locations").mkdir(exist_ok=True)

    regions = [region for _, group in GROUPS for region in group]
    assert set(regions) == set(db), f"GROUPS out of sync with the logic database: {set(regions) ^ set(db)}"

    maps: list[dict] = []
    locations: list[dict] = []
    area_maps: dict[str, dict[str, str]] = {}
    for region in regions:
        areas = bounds[region]["areas"]
        projection = Projection(areas)
        draw_map(region, areas, projection).save(OUT_DIR / "images" / f"{slug(region)}.png", optimize=True)
        maps.append(
            {
                "name": region,
                "img": f"images/{slug(region)}.png",
                "location_size": LOCATION_SIZE,
                "location_border_thickness": LOCATION_BORDER,
            }
        )
        locations.append(build_locations(db, region, projection))
        mlvl_areas = area_maps.setdefault(bounds[region]["mlvl"], {})
        for area in areas.values():
            mlvl_areas[str(area["index"])] = region

    (OUT_DIR / "maps" / "maps.json").write_text(json.dumps(maps, indent=2), encoding="utf-8")
    (OUT_DIR / "locations" / "locations.json").write_text(json.dumps(locations, indent=2), encoding="utf-8")
    (OUT_DIR / "area_maps.json").write_text(json.dumps(area_maps, indent=1, sort_keys=True), encoding="utf-8")
    total = sum(len(pickup_nodes(db, region)) for region in regions)
    print(f"wrote {len(maps)} maps, {total} locations to {OUT_DIR}")


if __name__ == "__main__":
    main()
