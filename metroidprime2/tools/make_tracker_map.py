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
from collections.abc import Iterable
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
# Room bounding boxes are 3D AABBs, so stacked rooms and rooms with a lot of
# empty air around them overlap heavily when seen from above. Each room is
# drawn at ROOM_SHRINK of its footprint and the rooms are then pushed apart
# until none overlap (keeping ROOM_GAP world units between neighbours).
ROOM_SHRINK = 0.6
ROOM_MIN_HALF = 5.0
ROOM_GAP = 6.0
# A label goes inside its room at the largest of these sizes that fits;
# a room too small for even the last one gets a LABEL_FONT_SIZE_OUTSIDE label
# beside it instead. Small outside labels are what keep dense maps readable:
# one big size made every cramped room's label collide with its neighbours'.
LABEL_FONT_SIZES_INSIDE = (30, 27, 24)
LABEL_FONT_SIZE_OUTSIDE = 22
LABEL_STROKE = 4
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
# Layout
# --------------------------------------------------------------------------


def layout_areas(areas: dict[str, dict]) -> dict[str, dict]:
    """Display geometry for every area: ``bounds`` is the shrunk, de-overlapped
    box (world units, z untouched) and ``source`` the real one, which
    ``display_point`` uses to carry a pickup coordinate across."""
    rects: dict[str, list[float]] = {}
    for name, area in areas.items():
        b = area["bounds"]
        cx, cy = (b[0] + b[3]) / 2, (b[1] + b[4]) / 2
        hx = max((b[3] - b[0]) / 2 * ROOM_SHRINK, ROOM_MIN_HALF)
        hy = max((b[4] - b[1]) / 2 * ROOM_SHRINK, ROOM_MIN_HALF)
        rects[name] = [cx - hx, cy - hy, cx + hx, cy + hy]

    names = sorted(rects, key=lambda n: (rects[n][0], rects[n][1], n))
    for _ in range(500):
        moved = False
        for i, a in enumerate(names):
            for b in names[i + 1 :]:
                ra, rb = rects[a], rects[b]
                ox = min(ra[2], rb[2]) - max(ra[0], rb[0]) + ROOM_GAP
                oy = min(ra[3], rb[3]) - max(ra[1], rb[1]) + ROOM_GAP
                if ox <= 0 or oy <= 0:
                    continue
                moved = True
                area_a = (ra[2] - ra[0]) * (ra[3] - ra[1])
                area_b = (rb[2] - rb[0]) * (rb[3] - rb[1])
                share_a = area_b / (area_a + area_b)  # the smaller room moves further
                axis = 0 if ox < oy else 1
                depth = ox if axis == 0 else oy
                sign = 1 if (ra[axis] + ra[axis + 2]) >= (rb[axis] + rb[axis + 2]) else -1
                for rect, share, direction in ((ra, share_a, sign), (rb, 1 - share_a, -sign)):
                    rect[axis] += direction * depth * share
                    rect[axis + 2] += direction * depth * share
        if not moved:
            break

    result: dict[str, dict] = {}
    for name, area in areas.items():
        b, r = area["bounds"], rects[name]
        result[name] = {**area, "source": b, "bounds": [r[0], r[1], b[2], r[2], r[3], b[5]]}
    return result


def display_point(area: dict, x: float, y: float) -> tuple[float, float]:
    """Maps a world point inside ``area``'s real bounds to the same relative
    spot inside its display box."""
    s, d = area["source"], area["bounds"]
    fx = (x - s[0]) / max(s[3] - s[0], 1e-6)
    fy = (y - s[1]) / max(s[4] - s[1], 1e-6)
    return d[0] + fx * (d[3] - d[0]), d[1] + fy * (d[4] - d[1])


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


def _balanced_label(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.FreeTypeFont) -> str:
    """One line if the name is short, otherwise split into two lines of as
    even a width as possible."""
    words = text.split()
    if len(words) < 2 or draw.textlength(text, font=font) <= 5.8 * font.size:
        return text
    candidates = [" ".join(words[:i]) + "\n" + " ".join(words[i:]) for i in range(1, len(words))]
    return min(candidates, key=lambda c: max(draw.textlength(line, font=font) for line in c.split("\n")))


def _place_labels(
    draw: ImageDraw.ImageDraw,
    rooms: list[tuple[str, tuple[int, int, int, int]]],
    fonts: dict[int, ImageFont.FreeTypeFont],
    image_size: tuple[int, int],
) -> list[tuple[str, str, tuple[float, float], int]]:
    """Picks a label (text, position, font size) per room, largest rooms
    first so they keep the center spots: inside the room at the largest size
    in ``LABEL_FONT_SIZES_INSIDE`` that fits without touching another label,
    otherwise small and just outside one of its sides. A label that would
    run off the image (and be clipped) is the costliest of all."""
    placed: list[tuple[float, float, float, float]] = []
    result: list[tuple[str, str, tuple[float, float], int]] = []

    def overlap(box: tuple[float, float, float, float], others: Iterable[tuple[float, ...]]) -> float:
        total = 0.0
        for other in others:
            w = min(box[2], other[2]) - max(box[0], other[0])
            h = min(box[3], other[3]) - max(box[1], other[1])
            if w > 0 and h > 0:
                total += w * h
        return total

    def measure(name: str, size: int) -> tuple[str, float, float]:
        label = _balanced_label(draw, name, fonts[size])
        left, top, right, bottom = draw.multiline_textbbox((0, 0), label, font=fonts[size], stroke_width=LABEL_STROKE)
        return label, right - left + 4, bottom - top + 4

    boxes = {name: box for name, box in rooms}
    for name, (x0, y0, x1, y1) in sorted(rooms, key=lambda r: -(r[1][2] - r[1][0]) * (r[1][3] - r[1][1])):
        cx, cy = (x0 + x1) / 2, (y0 + y1) / 2

        chosen: tuple[str, tuple[float, float], int, float, float] | None = None
        for size in LABEL_FONT_SIZES_INSIDE:
            label, w, h = measure(name, size)
            box = (cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2)
            if w <= x1 - x0 and h <= y1 - y0 and not overlap(box, placed):
                chosen = (label, (cx, cy), size, w, h)
                break

        if chosen is None:
            label, w, h = measure(name, LABEL_FONT_SIZE_OUTSIDE)
            candidates = [(cx, cy)]
            # Rings of positions around the room, nearest first (min() keeps
            # the first of equally good candidates, so near spots win ties).
            for ring in range(3):
                gap = 2 + ring * (h + 4)
                ex, ey = (x1 - x0) / 2 + w / 2 + gap, (y1 - y0) / 2 + h / 2 + gap
                candidates += [
                    (cx, cy - ey),
                    (cx, cy + ey),
                    (cx + ex, cy),
                    (cx - ex, cy),
                    (cx + ex, cy - ey),
                    (cx - ex, cy - ey),
                    (cx + ex, cy + ey),
                    (cx - ex, cy + ey),
                ]
            foreign = [box for other, box in boxes.items() if other != name]

            def cost(c: tuple[float, float], w: float = w, h: float = h) -> float:
                box = (c[0] - w / 2, c[1] - h / 2, c[0] + w / 2, c[1] + h / 2)
                # Colliding with another label is worst; sitting on another
                # room makes the label look like that room's, so it costs
                # too; and the farther from its own room, the less obviously
                # its own.
                distance = abs(c[0] - cx) + abs(c[1] - cy)
                clipped = w * h - overlap(box, [(0, 0, *image_size)])
                return 100 * clipped + 20 * overlap(box, placed) + overlap(box, foreign) + 8 * distance

            chosen = (label, min(candidates, key=cost), LABEL_FONT_SIZE_OUTSIDE, w, h)

        label, position, size, w, h = chosen
        placed.append((position[0] - w / 2, position[1] - h / 2, position[0] + w / 2, position[1] + h / 2))
        result.append((name, label, position, size))
    return result


def draw_map(region: str, areas: dict[str, dict], projection: Projection) -> Image.Image:
    dark = region in DARK_REGIONS
    # RGB base: ImageDraw only alpha-blends translucent fills onto RGB images.
    image = Image.new("RGB", (projection.width, projection.height), (26, 18, 36) if dark else (18, 22, 30))
    draw = ImageDraw.Draw(image, "RGBA")
    title_font = ImageFont.load_default(size=34)
    label_fonts = {
        size: ImageFont.load_default(size=size) for size in (*LABEL_FONT_SIZES_INSIDE, LABEL_FONT_SIZE_OUTSIDE)
    }

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
    rooms = []
    for name, area in ordered:
        b = area["bounds"]
        x0, y1 = projection.point(b[0], b[1])
        x1, y0 = projection.point(b[3], b[4])
        rooms.append((name, (x0, y0, x1, y1)))
    # Labels go in a pass of their own, on top of every room and outlined, so
    # a neighbour's fill can never hide one. A label that had to leave its
    # room is tied back to it with a leader line (drawn first, under all text).
    placed = _place_labels(draw, rooms, label_fonts, image.size)
    room_boxes = dict(rooms)
    for name, _, position, _ in placed:
        x0, y0, x1, y1 = room_boxes[name]
        if not (x0 <= position[0] <= x1 and y0 <= position[1] <= y1):
            center = ((x0 + x1) / 2, (y0 + y1) / 2)
            draw.line([center, position], fill=(255, 255, 255, 150), width=2)
            draw.ellipse((center[0] - 5, center[1] - 5, center[0] + 5, center[1] + 5), fill=(255, 255, 255, 220))
    for _, label, position, size in placed:
        draw.multiline_text(
            position,
            label,
            font=label_fonts[size],
            fill=(255, 255, 255, 255),
            stroke_width=LABEL_STROKE,
            stroke_fill=(0, 0, 0, 235),
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


def build_locations(db: dict[str, dict], region: str, areas: dict[str, dict], projection: Projection) -> dict:
    used: set[tuple[int, int]] = set()
    by_area: dict[str, list[dict]] = {}
    for area_name, node_name, node in pickup_nodes(db, region):
        c = node["coordinates"]
        px, py = projection.point(*display_point(areas[area_name], c["x"], c["y"]))
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
        areas = layout_areas(bounds[region]["areas"])
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
        locations.append(build_locations(db, region, areas, projection))
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
