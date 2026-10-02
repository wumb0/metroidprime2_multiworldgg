"""Builds ``metroidprime2/assets/items/*.png`` (the client's item-collection
panel icons) from the Metroid Prime world's icon set plus a few drawn shapes.

Run from the repo root after ``MultiWorldGG`` is symlinked in::

    python metroidprime2/tools/make_tracker_icons.py

The output PNGs are committed, so this only needs re-running to change an
icon. Three sources, in order of preference:

* ``COPIES``: Prime 1 icons that depict the same thing in Echoes.
* ``RECOLORS``: a Prime 1 icon hue-shifted into the Echoes analogue (the charge
  combos from Prime 1's combos, ...).
* ``DRAWN``: shapes with no Prime 1 counterpart (the four beams and the beam ammo
  crystals redrawn after Echoes' own HUD / pickup models), drawn with Pillow.
"""

from __future__ import annotations

import math
import shutil
from collections.abc import Callable
from itertools import pairwise
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageFilter

SIZE = 80
SUPERSAMPLE = 4

REPO_ROOT = Path(__file__).resolve().parents[2]
P1_ICONS = REPO_ROOT / "MultiWorldGG" / "worlds" / "metroidprime" / "assets" / "items"
OUT_DIR = REPO_ROOT / "metroidprime2" / "assets" / "items"

# echoes name -> prime1 file stem
COPIES: dict[str, str] = {
    "chargebeam": "chargebeam",
    "scanvisor": "scanvisor",
    "variasuit": "variasuit",
    "morphball": "morphball",
    "morphballbomb": "morphballbomb",
    "boostball": "boostball",
    "spiderball": "spiderball",
    "powerbomb": "powerbomb",
    "spacejumpboots": "spacejumpboots",
    "grapplebeam": "grapplebeam",
    "missilelauncher": "missilelauncher",
    "missileexpansion": "missileexpansion",
    "supermissile": "supermissile",
    "powerbombexpansion": "powerbombexpansion",
    "energytank": "energytank",
}

# echoes name -> (prime1 stem, target hue 0-360 or None to keep, saturation x, value x)
RECOLORS: dict[str, tuple[str, float | None, float, float]] = {
    # visors
    "combatvisor": ("thermalvisor", 25, 1.6, 1.15),
    "darkvisor": ("xrayvisor", 0, 2.2, 0.8),
    "echovisor": ("scanvisor", 185, 1.0, 1.0),
    # suits
    "darksuit": ("gravitysuit", 265, 0.9, 0.45),
    "lightsuit": ("variasuit", 55, 0.35, 1.3),
    # launchers
    "seekerlauncher": ("missilelauncher", 300, 0.9, 0.95),
}

TRANSLATOR_COLORS = {
    "violettranslator": (150, 90, 230),
    "ambertranslator": (240, 170, 40),
    "emeraldtranslator": (60, 200, 110),
    "cobalttranslator": (60, 110, 230),
}
# Every dark temple key's crystal is red; the ring tint tells the temples apart.
RED_CRYSTAL = (214, 58, 40)
DARK_KEY_COLORS = {
    "darkagonkey": (230, 140, 50),
    "darktorvuskey": (80, 200, 100),
    "ingkey": (170, 90, 220),
}


def _recolor(src: Image.Image, hue: float | None, sat: float, val: float) -> Image.Image:
    rgba = src.convert("RGBA")
    alpha = rgba.getchannel("A")
    h, s, v = rgba.convert("RGB").convert("HSV").split()
    if hue is not None:
        h = h.point(lambda _: int(hue / 360 * 255))
    s = s.point(lambda p: max(0, min(255, int(p * sat))))
    v = v.point(lambda p: max(0, min(255, int(p * val))))
    out = Image.merge("HSV", (h, s, v)).convert("RGB").convert("RGBA")
    out.putalpha(alpha)
    return out


def _canvas() -> tuple[Image.Image, ImageDraw.ImageDraw, int]:
    scale = SUPERSAMPLE
    image = Image.new("RGBA", (SIZE * scale, SIZE * scale), (0, 0, 0, 0))
    return image, ImageDraw.Draw(image), scale


def _finish(image: Image.Image) -> Image.Image:
    return image.resize((SIZE, SIZE), Image.Resampling.LANCZOS)


def _shade(color: tuple[int, int, int], factor: float) -> tuple[int, int, int]:
    return tuple(max(0, min(255, int(c * factor))) for c in color)  # type: ignore[return-value]


def _ring(
    draw: ImageDraw.ImageDraw,
    s: int,
    radii: tuple[float, float],
    width: float,
    color: tuple[int, int, int],
    edge: tuple[int, int, int],
) -> None:
    """A twelve-sided oval band (vertex at top and bottom, like the keys'
    frames) with an edge stroke either side, centered on the canvas."""
    rx, ry = radii
    c = SIZE * s / 2

    def points(a: float, b: float) -> list[tuple[float, float]]:
        angles = [math.radians(90 + 30 * i) for i in range(12)]
        return [(c + a * s * math.cos(angle), c - b * s * math.sin(angle)) for angle in angles]

    stroke = 1.3
    draw.polygon(points(rx, ry), fill=(*edge, 255))
    draw.polygon(points(rx - stroke, ry - stroke), fill=(*color, 255))
    draw.polygon(points(rx - width + stroke, ry - width + stroke), fill=(*edge, 255))
    draw.polygon(points(rx - width, ry - width), fill=(0, 0, 0, 0))


def _draw_temple_key(
    ring: tuple[int, int, int],
    crystal: tuple[int, int, int],
    glow: tuple[int, int, int],
) -> Image.Image:
    """Echoes' key: an egg-shaped crystal held in two concentric twelve-sided
    rings by a crossbar and clasps. The Sky Temple Key has a pale crystal in
    black rings; the dark temple keys have a red crystal, with the rings
    tinted per temple so the three stay apart."""
    image, draw, s = _canvas()
    cx = cy = SIZE * s // 2
    edge = _shade(ring, 0.38)

    # Soft glow behind the crystal.
    halo = Image.new("RGBA", image.size, (0, 0, 0, 0))
    ImageDraw.Draw(halo).ellipse((cx - 22 * s, cy - 26 * s, cx + 22 * s, cy + 26 * s), fill=(*glow, 150))
    image.alpha_composite(halo.filter(ImageFilter.GaussianBlur(5 * s)))
    draw = ImageDraw.Draw(image)

    # Crossbar through both rings, with a clasp either side of the crystal.
    draw.rectangle((1 * s, cy - 1.7 * s, 79 * s, cy + 1.7 * s), fill=(*edge, 255))
    draw.rectangle((1 * s, cy - 0.5 * s, 79 * s, cy + 0.5 * s), fill=(*ring, 255))
    _ring(draw, s, (35, 38.5), 7.5, ring, edge)
    _ring(draw, s, (21.5, 26), 6, ring, edge)
    for x0 in (26.5, 48.5):
        draw.rectangle((x0 * s, cy - 3.2 * s, (x0 + 5) * s, cy + 3.2 * s), fill=(*_shade(ring, 0.25), 255))

    # Egg-shaped faceted crystal: lit left half, shaded right half.
    top = [(40, 21.5), (46.5, 27.5), (49.5, 39), (46.5, 52), (40, 58), (33.5, 52), (30.5, 39), (33.5, 27.5)]
    pts = [((40 + (x - 40) * 1.12) * s, (39 + (y - 39) * 1.12) * s) for x, y in top]
    draw.polygon(pts, fill=(*_shade(crystal, 0.62), 255))
    draw.polygon([pts[0], pts[7], pts[6], pts[5], pts[4]], fill=(*crystal, 255))
    draw.polygon([pts[0], pts[1], (44 * s, 36 * s), (38 * s, 36 * s)], fill=(*_shade(crystal, 1.25), 255))
    draw.line([pts[0], pts[4]], fill=(*_shade(crystal, 1.3), 255), width=int(0.8 * s))
    draw.line([*pts, pts[0]], fill=(*edge, 255), width=int(0.9 * s))
    return _finish(image)


def _draw_screw_attack() -> Image.Image:
    image, draw, s = _canvas()
    cx = cy = SIZE * s // 2
    orange = (250, 160, 40)
    # Three trailing arcs around a bright core: the Screw Attack's spinning
    # sparks.
    for i in range(3):
        start = i * 120 + 10
        outer = (cx - 33 * s, cy - 33 * s, cx + 33 * s, cy + 33 * s)
        inner = (cx - 21 * s, cy - 21 * s, cx + 21 * s, cy + 21 * s)
        for width, color in ((9, _shade(orange, 0.6)), (5, orange), (2, (255, 240, 180))):
            draw.arc(outer, start, start + 85, fill=(*color, 255), width=width * s)
        for width, color in ((7, _shade(orange, 0.6)), (4, orange)):
            draw.arc(inner, start + 40, start + 120, fill=(*color, 255), width=width * s)
    draw.ellipse((cx - 11 * s, cy - 11 * s, cx + 11 * s, cy + 11 * s), fill=(*_shade(orange, 0.6), 255))
    draw.ellipse((cx - 8 * s, cy - 8 * s, cx + 8 * s, cy + 8 * s), fill=(255, 235, 150, 255))
    return _finish(image)


MASK_DIR = Path(__file__).resolve().parent / "beam_masks"
# One scale for all four symbols so they keep the proportions of the source
# sheet (the light beam's halftone fade is what makes its mask the widest).
BEAM_MASK_SCALE = 0.3
BEAM_COLORS = {
    "powerbeam": (226, 112, 56),
    "darkbeam": (208, 154, 230),
    "lightbeam": (232, 246, 255),
    "annihilatorbeam": (172, 98, 236),
}
# Beams whose silhouette has a differently colored middle shape.
BEAM_CORE_COLORS = {"annihilatorbeam": (112, 150, 182)}
# ... which is also stretched sideways about the symbol's axis by this factor.
BEAM_CORE_WIDEN = 1.4


def _center_shape(mask: Image.Image) -> Image.Image:
    """The part of ``mask`` connected to its middle pixel (flood fill on the
    thresholded silhouette), as an alpha mask the same size as ``mask``."""
    binary = mask.point(lambda p: 255 if p > 128 else 0)
    ImageDraw.floodfill(binary, (mask.width // 2, mask.height // 2), 128)
    region = binary.point(lambda p: 255 if p == 128 else 0).filter(ImageFilter.MaxFilter(3))
    return ImageChops.multiply(mask, region)


def _draw_beam(name: str) -> Image.Image:
    """The beam's HUD symbol, colored, centered on the canvas. The shapes are
    traced from ``beam_masks/<name>.png`` (alpha-only silhouettes cut from
    reference art of the in-game icons)."""
    image, _, s = _canvas()
    mask = Image.open(MASK_DIR / f"{name}.png").convert("L")
    layers = [(mask, BEAM_COLORS[name])]
    if name in BEAM_CORE_COLORS:
        core = _center_shape(mask)
        wide = core.resize((round(core.width * BEAM_CORE_WIDEN), core.height), Image.Resampling.LANCZOS)
        widened = Image.new("L", mask.size)
        widened.paste(wide, ((mask.width - wide.width) // 2, 0))
        layers = [(ImageChops.subtract(mask, core), BEAM_COLORS[name]), (widened, BEAM_CORE_COLORS[name])]
    width, height = (max(1, round(d * BEAM_MASK_SCALE * s)) for d in mask.size)
    for layer, color in layers:
        scaled = layer.resize((width, height), Image.Resampling.LANCZOS)
        symbol = Image.new("RGBA", scaled.size, (*color, 255))
        symbol.putalpha(scaled)
        image.alpha_composite(symbol, ((SIZE * s - width) // 2, (SIZE * s - height) // 2))
    return _finish(image)


def _arch(cx: float, base_y: float, half_width: float, apex_y: float, steps: int = 24) -> list[tuple[float, float]]:
    """A pointed (ogive) arch outline, in 80px units."""
    left = _bezier((cx - half_width, base_y), (cx - half_width, apex_y + (base_y - apex_y) * 0.18), (cx, apex_y), steps)
    right = [(2 * cx - x, y) for x, y in reversed(left)]
    return left + right


def _bezier(p0: tuple[float, float], p1: tuple[float, float], p2: tuple[float, float], steps: int):
    return [
        (
            (1 - f) ** 2 * p0[0] + 2 * (1 - f) * f * p1[0] + f**2 * p2[0],
            (1 - f) ** 2 * p0[1] + 2 * (1 - f) * f * p1[1] + f**2 * p2[1],
        )
        for f in (i / steps for i in range(steps + 1))
    ]


def _draw_gravity_boost() -> Image.Image:
    """The Gravity Boost seen straight on (it is not a suit, so no suit
    icon): a pointed steel dome studded with red lights, wrapped by a level
    copper plate with slits and a red octagon light at each end, over a
    brown base holding the round red thruster. Mirrored
    about the vertical axis, like the unit itself."""
    image, draw, s = _canvas()
    cx = SIZE / 2

    def poly(points: list[tuple[float, float]], fill: tuple[int, ...]) -> None:
        draw.polygon([(x * s, y * s) for x, y in points], fill=fill)

    def mirrored(points: list[tuple[float, float]]) -> list[tuple[float, float]]:
        return points + [(2 * cx - x, y) for x, y in reversed(points)]

    def disc(x: float, y: float, r: float, fill: tuple[int, ...]) -> None:
        draw.ellipse(((x - r) * s, (y - r) * s, (x + r) * s, (y + r) * s), fill=fill)

    def octagon(x: float, y: float, r: float) -> list[tuple[float, float]]:
        angles = [math.radians(22.5 + 45 * i) for i in range(8)]
        return [(x + r * math.cos(angle), y + r * math.sin(angle)) for angle in angles]

    outline, brown, copper, copper_lit = (34, 18, 14, 255), (84, 46, 34, 255), (172, 116, 82, 255), (212, 158, 118, 255)
    red, red_lit, red_dark = (214, 54, 28, 255), (255, 150, 104, 255), (110, 24, 14, 255)

    # Copper shell behind the dome (a rim either side), then the steel dome,
    # lit along its centre line and darker toward the edges.
    poly(_arch(cx, 60, 34, 0), outline)
    poly(_arch(cx, 60, 31, 3), (150, 92, 66, 255))
    poly(_arch(cx, 62, 28, 3), outline)
    mask = Image.new("L", image.size, 0)
    ImageDraw.Draw(mask).polygon([(x * s, y * s) for x, y in _arch(cx, 62, 26, 5)], fill=255)
    shading = Image.new("RGBA", image.size)
    shade = ImageDraw.Draw(shading)
    for x in range(image.width):
        k = min(1.0, abs(x / s - cx) / 26) ** 1.4
        color = tuple(round(a + (b - a) * k) for a, b in zip((204, 206, 212), (84, 86, 94), strict=True))
        shade.line([(x, 0), (x, image.height)], fill=(*color, 255))
    image.paste(shading, mask=mask)
    for x, y in ((40, 15), (33, 23), (47, 23), (27, 32), (40, 31), (53, 32)):
        disc(x, y, 2.4, outline)
        disc(x, y, 1.7, red)
    # Level copper band across the dome: slits in the middle, a red light at each end.
    poly([(3, 42), (77, 42), (75, 58), (5, 58)], outline)
    poly([(5, 44), (75, 44), (73, 56), (7, 56)], copper)
    poly([(5, 44), (75, 44), (75, 47), (5, 47)], copper_lit)
    for i in range(3):
        y0 = 49.5 + 2.4 * i
        draw.line([(29 * s, y0 * s), (51 * s, y0 * s)], fill=outline, width=round(1.4 * s))
    for x in (16, 64):
        poly(octagon(x, 51, 6.2), outline)
        poly(octagon(x, 51, 4.8), red)
        disc(x - 1.3, 49.7, 1.4, red_lit)
    # Brown base with the round thruster: metal rim, dark intake ringed by
    # radial vent slats, and a hot glowing core.
    # The base flares out into long flat wings (two stacked shards a side),
    # as on the item model.
    for shard, fill in (
        ([(24, 58), (-1, 65), (1, 73), (30, 70)], (124, 72, 54, 255)),
        ([(26, 66), (0, 76), (5, 80), (38, 75)], (96, 54, 40, 255)),
    ):
        for points in (shard, [(2 * cx - x, y) for x, y in shard]):
            draw.polygon([(x * s, y * s) for x, y in points], fill=fill, outline=outline, width=round(1.3 * s))
    poly([(5, 58), (75, 58), (71, 70), (40, 77), (9, 70)], outline)
    poly([(7, 59.5), (73, 59.5), (69.5, 69), (40, 75), (10.5, 69)], brown)
    ty = 67.5
    disc(cx, ty, 10.2, outline)
    disc(cx, ty, 9, copper_lit)
    disc(cx, ty, 7.4, outline)
    disc(cx, ty, 6.6, red_dark)
    for i in range(14):
        angle = math.radians(360 / 14 * i)
        draw.line(
            [
                ((cx + 3.6 * math.cos(angle)) * s, (ty + 3.6 * math.sin(angle)) * s),
                ((cx + 6.4 * math.cos(angle)) * s, (ty + 6.4 * math.sin(angle)) * s),
            ],
            fill=(232, 96, 60, 255),
            width=round(1.1 * s),
        )
    disc(cx, ty, 3.4, red)
    disc(cx - 0.5, ty - 0.5, 1.9, red_lit)
    return _finish(image)


def _draw_beam_ammo(crystal: tuple[int, int, int]) -> Image.Image:
    image, draw, s = _canvas()
    cx = SIZE * s // 2
    stone = (56, 49, 55, 255)
    stone_hi = (92, 83, 90, 255)

    def poly(points: list[tuple[float, float]], fill: tuple[int, ...]) -> None:
        draw.polygon([(x * s, y * s) for x, y in points], fill=fill)

    # Pedestal: dark column behind the crystal, flared wings, base plate.
    poly([(40, 14), (53, 52), (27, 52)], stone)
    poly([(4, 67), (25, 43), (40, 56), (55, 43), (76, 67), (62, 77), (18, 77)], stone)
    poly([(4, 67), (25, 43), (30, 53), (18, 66)], stone_hi)
    poly([(76, 67), (55, 43), (50, 53), (62, 66)], stone_hi)
    # Floating shards either side, their outer facet catching the crystal's light.
    for mirror in (1, -1):
        def sp(points: list[tuple[float, float]], m: int = mirror) -> list[tuple[float, float]]:
            return [(40 + m * (x - 40), y) for x, y in points]

        poly(sp([(17, 19), (24, 27), (23, 50), (15, 56), (14, 50), (14, 27)]), stone)
        poly(sp([(17, 19), (14, 27), (14, 50), (16, 52), (18, 28)]), (*_shade(crystal, 0.8), 255))
    # Central crystal, lit left, with its chevron cap.
    poly([(40, 10), (50, 27), (51, 52), (46, 63), (34, 63), (29, 52), (30, 27)], (*_shade(crystal, 0.85), 255))
    poly([(40, 10), (30, 27), (29, 52), (34, 63), (40, 63)], (*crystal, 255))
    poly([(40, 14), (45, 28), (44, 54), (40, 60)], (*_shade(crystal, 1.15), 255))
    poly([(25, 15), (40, 2), (55, 15), (50, 17), (40, 9), (30, 17)], stone)
    draw.ellipse((cx - 4 * s, 68 * s, cx + 4 * s, 76 * s), fill=(235, 160, 50, 255))
    draw.ellipse((cx - 2.5 * s, 69.5 * s, cx + 2.5 * s, 74.5 * s), fill=(255, 205, 90, 255))
    return _finish(image)


# --------------------------------------------------------------------------
# Charge combos, translators (drawn after the in-game art)
# --------------------------------------------------------------------------

Point = tuple[float, float]
CLAW_RIM = (128, 134, 150)
CLAW_FILL = (40, 42, 52)
AMBER = (255, 176, 48)


def _mirror(points: list[Point]) -> list[Point]:
    return [(SIZE - x, y) for x, y in points]


def _poly(
    draw: ImageDraw.ImageDraw,
    s: int,
    points: list[Point],
    fill: tuple[int, ...],
    outline: tuple[int, int, int] | None = None,
    width: float = 1.2,
) -> None:
    kwargs = {"outline": (*outline, 255), "width": max(1, round(width * s))} if outline else {}
    draw.polygon([(x * s, y * s) for x, y in points], fill=fill, **kwargs)


def _glow(
    image: Image.Image, s: int, color: tuple[int, int, int], box: tuple[float, ...], blur: float, alpha: int
) -> None:
    layer = Image.new("RGBA", image.size, (0, 0, 0, 0))
    ImageDraw.Draw(layer).ellipse(tuple(v * s for v in box), fill=(*color, alpha))
    image.alpha_composite(layer.filter(ImageFilter.GaussianBlur(blur * s)))


def _draw_claws(draw: ImageDraw.ImageDraw, s: int) -> None:
    """The pair of dark claws with amber lights and the center stem that sit
    under every charge-combo symbol in the game. Black in the game; a dark
    steel with a pale rim here so they survive the dark panel."""
    left: list[Point] = [(25, 55), (33, 64), (28, 78), (17, 72), (20, 62)]
    for claw in (left, _mirror(left)):
        _poly(draw, s, claw, (*CLAW_FILL, 255), CLAW_RIM)
    for x in (25.2, SIZE - 25.2):
        draw.ellipse(((x - 1.6) * s, 65.4 * s, (x + 1.6) * s, 68.6 * s), fill=(*AMBER, 255))
    _poly(draw, s, [(37.6, 55), (42.4, 55), (40.7, 80), (39.3, 80)], (*CLAW_FILL, 255), CLAW_RIM, 0.9)


def _spike(draw: ImageDraw.ImageDraw, s: int, origin: Point, points: list[Point], color: tuple[int, int, int]) -> None:
    """A thin needle bending through ``points`` (offsets from ``origin``),
    thick at the base and tapering to nothing."""
    chain = [origin] + [(origin[0] + dx, origin[1] + dy) for dx, dy in points]
    for i, (a, b) in enumerate(pairwise(chain)):
        width = max(0.6, 3.2 - 1.3 * i)
        draw.line([(a[0] * s, a[1] * s), (b[0] * s, b[1] * s)], fill=(*color, 255), width=round(width * s))


def _draw_sunburst() -> Image.Image:
    """Light-beam combo: a blaze of flat plates (teal fading to white at the
    center, violet-edged) around a pale dagger."""
    image, draw, s = _canvas()
    cx, cy = 40.0, 30.0
    plate_fill, plate_edge = (150, 222, 220, 255), (132, 82, 156)
    plates = [
        [(32, 4), (49, 4), (cx, cy)],
        [(14, 24), (26, 9), (cx, cy)],
        [(4, 25), (4, 37), (cx, cy)],
    ]
    for plate in plates + [_mirror(p) for p in plates[1:]]:
        _poly(draw, s, plate, plate_fill, plate_edge, 1.4)
    _glow(image, s, (255, 255, 255), (cx - 15, cy - 13, cx + 15, cy + 13), 3.5, 255)
    draw = ImageDraw.Draw(image)
    _poly(draw, s, [(cx, 12), (cx + 3.4, 24), (cx, 30), (cx - 3.4, 24)], (216, 220, 228, 255))
    _poly(draw, s, [(cx, 33), (cx + 4.2, 40), (cx, 50), (cx - 4.2, 40)], (255, 255, 255, 255))
    _draw_claws(draw, s)
    return _finish(image)


def _draw_darkburst() -> Image.Image:
    """Dark-beam combo: a dark violet octagon swirled with pale lines and
    ringed with bent thorns."""
    image, draw, s = _canvas()
    cx, cy, r = 40.0, 29.0, 13.5
    thorn = (96, 52, 112)
    for dx, dy, pts in (
        (-7, -10, [(-5, -9), (-14, -15)]),
        (8, -11, [(5, -4), (24, -14)]),
        (-12, 3, [(-14, 1), (-26, 7)]),
        (12, 4, [(12, -3), (26, -2)]),
        (13, 10, [(10, 3), (24, 9)]),
        (-8, 11, [(-8, 5), (-14, 12)]),
    ):
        _spike(draw, s, (cx + dx, cy + dy), pts, thorn)
    angles = [math.radians(22.5 + 45 * i) for i in range(8)]
    octagon = [(cx + r * math.cos(a), cy + r * math.sin(a)) for a in angles]
    _poly(draw, s, octagon, (58, 34, 76, 255), (140, 90, 164), 1.6)
    for box, start, end in (
        ((cx - 8, cy - 8, cx + 4, cy + 4), 200, 340),
        ((cx - 4, cy - 2, cx + 9, cy + 9), 20, 170),
        ((cx - 9, cy - 1, cx + 1, cy + 8), 250, 380),
        ((cx - 3, cy - 9, cx + 8, cy + 2), 100, 250),
    ):
        draw.arc(tuple(v * s for v in box), start, end, fill=(168, 124, 196, 255), width=round(1.3 * s))
    _draw_claws(draw, s)
    return _finish(image)


def _draw_sonic_boom() -> Image.Image:
    """Annihilator combo: a tall beveled octagonal lens with concentric
    ripples in its middle."""
    image, draw, s = _canvas()
    cx, cy = 40.0, 28.0

    def octagon(rx: float, ry: float) -> list[Point]:
        k = 0.5
        return [
            (cx - rx * k, cy - ry), (cx + rx * k, cy - ry), (cx + rx, cy - ry * k), (cx + rx, cy + ry * k),
            (cx + rx * k, cy + ry), (cx - rx * k, cy + ry), (cx - rx, cy + ry * k), (cx - rx, cy - ry * k),
        ]  # fmt: skip

    _poly(draw, s, octagon(17.5, 23), (92, 84, 76, 255))
    _poly(draw, s, octagon(15, 20.5), (176, 170, 150, 255))
    _poly(draw, s, octagon(12.5, 17.5), (236, 234, 216, 255))
    _poly(draw, s, octagon(9.5, 13.5), (250, 250, 242, 255))
    # Concentric ripples, dark at the middle fading to the lens's cream.
    for radius, color in (
        (9.0, (214, 212, 194)), (7.7, (246, 245, 232)), (6.4, (170, 172, 158)), (5.1, (236, 235, 220)),
        (3.8, (128, 130, 118)), (2.5, (206, 205, 190)), (1.3, (92, 94, 84)),
    ):  # fmt: skip
        draw.ellipse(
            ((cx - radius) * s, (cy - radius * 1.4) * s, (cx + radius) * s, (cy + radius * 1.4) * s),
            fill=(*color, 255),
        )
    _draw_claws(draw, s)
    return _finish(image)


# A translator glyph is a small graph of glowing nodes. The two layouts are
# traced from the gate screenshots; each translator color gets one of them
# (or its mirror image) so the four stay distinguishable by shape as well.
GLYPH_A_NODES = {
    "a": (296, 185), "b": (289, 238), "c": (337, 246), "d": (380, 257), "e": (283, 293),
    "f": (328, 300), "g": (372, 305), "h": (275, 345), "i": (320, 353),
}  # fmt: skip
GLYPH_A_EDGES = ("ab", "bc", "cd", "be", "cf", "dg", "ef", "fg", "eh", "fi", "hi")
GLYPH_B_NODES = {
    "a": (844, 143), "b": (890, 145), "c": (848, 188), "d": (890, 190), "e": (793, 238),
    "f": (846, 239), "g": (888, 238), "h": (792, 290), "i": (840, 284), "j": (888, 285),
}  # fmt: skip
GLYPH_B_EDGES = ("ac", "bd", "cd", "cf", "dg", "ef", "fg", "eh", "fi", "gj", "hi", "ij")
TRANSLATOR_GLYPHS = {
    "violettranslator": (GLYPH_A_NODES, GLYPH_A_EDGES, False),
    "ambertranslator": (GLYPH_B_NODES, GLYPH_B_EDGES, False),
    "emeraldtranslator": (GLYPH_A_NODES, GLYPH_A_EDGES, True),
    "cobalttranslator": (GLYPH_B_NODES, GLYPH_B_EDGES, True),
}


def _draw_translator(name: str, color: tuple[int, int, int]) -> Image.Image:
    nodes, edges, flipped = TRANSLATOR_GLYPHS[name]
    xs, ys = [p[0] for p in nodes.values()], [p[1] for p in nodes.values()]
    scale = 56 / max(max(xs) - min(xs), max(ys) - min(ys))
    mid_x, mid_y = (max(xs) + min(xs)) / 2, (max(ys) + min(ys)) / 2
    placed: dict[str, Point] = {}
    for key, (x, y) in nodes.items():
        dx = (x - mid_x) * scale * (-1 if flipped else 1)
        placed[key] = (40 + dx, 40 + (y - mid_y) * scale)

    image, _, s = _canvas()
    lit = tuple(round(c + (255 - c) * 0.55) for c in color)
    halo = Image.new("RGBA", image.size, (0, 0, 0, 0))
    halo_draw = ImageDraw.Draw(halo)
    for edge in edges:
        a, b = placed[edge[0]], placed[edge[1]]
        halo_draw.line([(a[0] * s, a[1] * s), (b[0] * s, b[1] * s)], fill=(*color, 230), width=round(5 * s))
    for x, y in placed.values():
        halo_draw.ellipse(((x - 6) * s, (y - 6) * s, (x + 6) * s, (y + 6) * s), fill=(*color, 230))
    image.alpha_composite(halo.filter(ImageFilter.GaussianBlur(3 * s)))
    draw = ImageDraw.Draw(image)
    for edge in edges:
        a, b = placed[edge[0]], placed[edge[1]]
        draw.line([(a[0] * s, a[1] * s), (b[0] * s, b[1] * s)], fill=(*color, 255), width=round(2.4 * s))
    for x, y in placed.values():
        draw.ellipse(((x - 4.6) * s, (y - 4.6) * s, (x + 4.6) * s, (y + 4.6) * s), fill=(*color, 255))
        draw.ellipse(((x - 2.8) * s, (y - 2.8) * s, (x + 2.8) * s, (y + 2.8) * s), fill=(*lit, 255))
    return _finish(image)


DRAWN: dict[str, Callable[[], Image.Image]] = {
    "gravityboost": _draw_gravity_boost,
    "powerbeam": lambda: _draw_beam("powerbeam"),
    "darkbeam": lambda: _draw_beam("darkbeam"),
    "lightbeam": lambda: _draw_beam("lightbeam"),
    "annihilatorbeam": lambda: _draw_beam("annihilatorbeam"),
    "lightammoexpansion": lambda: _draw_beam_ammo((238, 238, 232)),
    "darkammoexpansion": lambda: _draw_beam_ammo((170, 112, 232)),
    "screwattack": _draw_screw_attack,
    "skytemplekey": lambda: _draw_temple_key((142, 150, 162), (236, 240, 206), (255, 255, 225)),
    "sunburst": _draw_sunburst,
    "darkburst": _draw_darkburst,
    "sonicboom": _draw_sonic_boom,
    **{name: (lambda n=name, c=color: _draw_translator(n, c)) for name, color in TRANSLATOR_COLORS.items()},
    **{
        name: (lambda c=color: _draw_temple_key(c, RED_CRYSTAL, (255, 90, 80)))
        for name, color in DARK_KEY_COLORS.items()
    },
}


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for name, stem in COPIES.items():
        shutil.copyfile(P1_ICONS / f"{stem}.png", OUT_DIR / f"{name}.png")
    for name, (stem, hue, sat, val) in RECOLORS.items():
        _recolor(Image.open(P1_ICONS / f"{stem}.png"), hue, sat, val).save(OUT_DIR / f"{name}.png")
    for name, draw_fn in DRAWN.items():
        draw_fn().save(OUT_DIR / f"{name}.png")
    print(f"wrote {len(list(OUT_DIR.glob('*.png')))} icons to {OUT_DIR}")


if __name__ == "__main__":
    main()
