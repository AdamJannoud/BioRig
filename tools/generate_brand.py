"""Generate the BioRig brand kit: brandmark (direction B, the canopy of two rings), lockup and favicons.

    .venv/bin/python tools/generate_brand.py          # write every output
    .venv/bin/python tools/generate_brand.py --check  # exit 1 if an output on disk is stale

Every mark is one list of primitives (ring, arc, line, curve, dot, tile, text) on a 96-unit grid. The SVG writer
and the Pillow painter both consume that list, so each PNG is painted from the same geometry as its SVG; there is
no SVG rasteriser here (see tools/generate_architecture.py for why). The wordmark is set in the vendored DejaVu Sans
Bold, so the lockup raster is independent of the host's fonts.

Outputs, under assets/brand/ (the brand kit) and dashboard/brand/ (what the dashboard serves, kept inside dashboard/
so a hosted checkout that receives only that directory still has its icon):
  biorig-mark.svg / .png (512 px)          the brandmark for light backgrounds
  biorig-mark-reverse.svg / .png (512 px)  the brandmark in gold, for forest and dark backgrounds
  biorig-lockup.svg / .png (4x)            mark + "BioRig." wordmark on a forest tile
  biorig-icon-64.svg, biorig-icon-32.svg   the step-down: two rings at 64 px, one ring at 32 px
  favicon.svg, favicon-16.png, favicon-32.png, favicon.ico
                                           one ring on a forest tile, drawn on the 16 px grid, not scaled down
  dashboard/brand/mark.svg, mark-reverse.svg, favicon.png
                                           the header marks (heavier rings for 22-30 px display) and the tab icon

Palette (Celo gold and forest): GOLD #FCFF52, GOLD_DEEP #E8EC2A, FOREST #023A24.
Brand design and every asset: Adam Jannoud (AdamJannoud). Each SVG and PNG carries that credit.
"""
from __future__ import annotations

import argparse
import io
import math
import sys
from functools import lru_cache
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont
from PIL.PngImagePlugin import PngInfo

ROOT = Path(__file__).resolve().parent.parent
BRAND_DIR = ROOT / "assets" / "brand"
DASHBOARD_BRAND_DIR = ROOT / "dashboard" / "brand"
FONT_BOLD = ROOT / "assets" / "fonts" / "DejaVuSans-Bold.ttf"
GENERATOR = "tools/generate_brand.py"
CREDIT = "BioRig brand. Design and artwork: Adam Jannoud (AdamJannoud). All rights reserved."

GOLD, GOLD_DEEP, GOLD_INK = "#FCFF52", "#E8EC2A", "#1A1C00"
FOREST, FOREST_2 = "#023A24", "#0A5B3A"
WHITE = "#FFFFFF"
GRID = 96
SUPERSAMPLE = 8


# --------------------------------------------------------------------------- geometry

def arc_center(x1, y1, x2, y2, r, sweep_cw=True) -> tuple[float, float]:
    """Centre of the large arc of radius r from (x1, y1) to (x2, y2), drawn clockwise on screen (SVG sweep=1)."""
    mx, my = (x1 + x2) / 2, (y1 + y2) / 2
    half = math.hypot(x2 - x1, y2 - y1) / 2
    h = math.sqrt(r * r - half * half)
    ux, uy = (x2 - x1) / (2 * half), (y2 - y1) / (2 * half)
    # For a large clockwise arc (SVG large-arc=1, sweep=1) the centre sits to the right of the chord, facing along it.
    sign = 1 if sweep_cw else -1
    return mx + sign * h * uy, my - sign * h * ux


def mark(stroke: float = 6, inverse: bool = False, ground: bool = True) -> list[tuple]:
    """Direction B: Celo's interlocking rings as the canopy, a forest trunk, and the biometric node."""
    ring = GOLD if inverse else GOLD_DEEP
    wood = GOLD if inverse else FOREST
    out: list[tuple] = []
    if ground:
        out.append(("quad", (16, 80), (48, 68), (80, 80), wood, 3, 0.55 if inverse else 0.45))
    out += [
        ("line", (48, 80), (48, 54), wood, 5),
        ("arc", (49.4, 27), (49.4, 55), 17, ring, stroke),
        ("ring", (37, 41), 17, ring, stroke),
        ("dot", (48, 61), 5, ring, None if inverse else wood, 2.5),
    ]
    return out


def icon_64() -> list[tuple]:
    return [("arc", (49.4, 27), (49.4, 55), 17, GOLD_DEEP, 7, "butt"),
            ("ring", (37, 41), 17, GOLD_DEEP, 7),
            ("dot", (48, 61), 6, FOREST, None, 0)]


def icon_32() -> list[tuple]:
    return [("ring", (43, 43), 22, GOLD_DEEP, 11), ("dot", (43, 43), 7, FOREST, None, 0)]


def favicon() -> list[tuple]:
    """Below 32 px the canopy collapses to one ring on a forest tile, drawn on the 16 px grid."""
    return [("tile", 22, FOREST), ("ring", (48, 48), 21, GOLD, 13), ("dot", (48, 48), 6, GOLD, None, 0)]


@lru_cache(maxsize=None)
def _font(px: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(str(FONT_BOLD), px)


WORD_PX, WORD_TRACK = 21, -0.03 * 21
MARK_PX, PAD_X, PAD_Y, GAP = 34, 16, 13, 6


def _word_width(text: str) -> float:
    f = _font(WORD_PX * 16)
    return sum(f.getlength(ch) / 16 + WORD_TRACK for ch in text) - WORD_TRACK


def lockup_size() -> tuple[float, float]:
    return PAD_X + MARK_PX + GAP + _word_width("BioRig.") + PAD_X, PAD_Y * 2 + MARK_PX


# --------------------------------------------------------------------------- SVG writer

def _n(v: float) -> str:
    return f"{v:.2f}".rstrip("0").rstrip(".")


def _svg_prims(prims: list[tuple], k: float = 1.0, dx: float = 0, dy: float = 0, size: float = GRID) -> list[str]:
    def p(x, y):
        return f"{_n(dx + x * k)} {_n(dy + y * k)}"

    out = []
    for prim in prims:
        kind = prim[0]
        if kind == "tile":
            _, rx, fill = prim
            out.append(f'<rect x="{_n(dx)}" y="{_n(dy)}" width="{_n(size * k)}" height="{_n(size * k)}" '
                       f'rx="{_n(rx * k)}" fill="{fill}"/>')
        elif kind == "quad":
            _, a, c, b, color, w, op = prim
            out.append(f'<path d="M{p(*a)} Q{p(*c)} {p(*b)}" fill="none" stroke="{color}" '
                       f'stroke-width="{_n(w * k)}" stroke-linecap="round" opacity="{_n(op)}"/>')
        elif kind == "line":
            _, a, b, color, w = prim
            out.append(f'<path d="M{p(*a)} L{p(*b)}" fill="none" stroke="{color}" stroke-width="{_n(w * k)}" '
                       f'stroke-linecap="round"/>')
        elif kind == "arc":
            _, a, b, r, color, w, *cap = prim
            out.append(f'<path d="M{p(*a)} A{_n(r * k)} {_n(r * k)} 0 1 1 {p(*b)}" fill="none" stroke="{color}" '
                       f'stroke-width="{_n(w * k)}" stroke-linecap="{cap[0] if cap else "round"}"/>')
        elif kind == "ring":
            _, c, r, color, w = prim
            out.append(f'<circle cx="{_n(dx + c[0] * k)}" cy="{_n(dy + c[1] * k)}" r="{_n(r * k)}" fill="none" '
                       f'stroke="{color}" stroke-width="{_n(w * k)}"/>')
        elif kind == "dot":
            _, c, r, fill, stroke, sw = prim
            s = f' stroke="{stroke}" stroke-width="{_n(sw * k)}"' if stroke else ""
            out.append(f'<circle cx="{_n(dx + c[0] * k)}" cy="{_n(dy + c[1] * k)}" r="{_n(r * k)}" '
                       f'fill="{fill}"{s}/>')
        else:
            raise ValueError(kind)
    return out


def svg_doc(prims: list[tuple], label: str, size: int = GRID) -> str:
    body = "\n  ".join(_svg_prims(prims))
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{size}" height="{size}" viewBox="0 0 {GRID} {GRID}" '
            f'role="img" aria-label="{label}">\n  <title>{label}</title>\n  <desc>{CREDIT}</desc>\n'
            f'  {body}\n</svg>\n')


def lockup_svg() -> str:
    w, h = lockup_size()
    k = MARK_PX / GRID
    marks = "\n  ".join(_svg_prims(mark(inverse=True), k, PAD_X, PAD_Y))
    word_w = _word_width("BioRig")
    x = PAD_X + MARK_PX + GAP
    base = h / 2 + WORD_PX * 0.36
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{_n(w)}" height="{_n(h)}" viewBox="0 0 {_n(w)} {_n(h)}" '
            f'role="img" aria-label="BioRig">\n  <title>BioRig</title>\n  <desc>{CREDIT}</desc>\n'
            f'  <rect width="{_n(w)}" height="{_n(h)}" rx="12" fill="{FOREST}"/>\n  {marks}\n'
            f'  <text x="{_n(x)}" y="{_n(base)}" font-family="DejaVu Sans, -apple-system, \'Segoe UI\', sans-serif" '
            f'font-size="{WORD_PX}" font-weight="700" letter-spacing="{_n(WORD_TRACK)}" fill="{WHITE}">'
            f'<tspan textLength="{_n(word_w)}">BioRig</tspan><tspan fill="{GOLD_DEEP}">.</tspan></text>\n</svg>\n')


# --------------------------------------------------------------------------- Pillow painter

def _rgba(color: str, opacity: float = 1.0) -> tuple[int, int, int, int]:
    c = color.lstrip("#")
    return int(c[0:2], 16), int(c[2:4], 16), int(c[4:6], 16), round(255 * opacity)


def _cap(dr, x, y, w, fill):
    dr.ellipse([x - w / 2, y - w / 2, x + w / 2, y + w / 2], fill=fill)


def _paint(im: Image.Image, prims: list[tuple], k: float, dx: float = 0, dy: float = 0, size: float = GRID):
    """Paint primitives onto an RGBA image already at supersampled scale k (pixels per grid unit)."""
    for prim in prims:
        layer = Image.new("RGBA", im.size, (0, 0, 0, 0))
        dr = ImageDraw.Draw(layer)
        kind = prim[0]
        op = 1.0
        if kind == "tile":
            _, rx, fill = prim
            dr.rounded_rectangle([dx, dy, dx + size * k - 1, dy + size * k - 1], radius=rx * k, fill=_rgba(fill))
        elif kind == "quad":
            _, a, c, b, color, w, op = prim
            pts = []
            for i in range(65):
                t = i / 64
                x = (1 - t) ** 2 * a[0] + 2 * (1 - t) * t * c[0] + t * t * b[0]
                y = (1 - t) ** 2 * a[1] + 2 * (1 - t) * t * c[1] + t * t * b[1]
                pts.append((dx + x * k, dy + y * k))
            dr.line(pts, fill=_rgba(color), width=round(w * k), joint="curve")
            for x, y in (pts[0], pts[-1]):
                _cap(dr, x, y, w * k, _rgba(color))
        elif kind == "line":
            _, a, b, color, w = prim
            pa, pb = (dx + a[0] * k, dy + a[1] * k), (dx + b[0] * k, dy + b[1] * k)
            dr.line([pa, pb], fill=_rgba(color), width=round(w * k))
            for x, y in (pa, pb):
                _cap(dr, x, y, w * k, _rgba(color))
        elif kind == "arc":
            _, a, b, r, color, w, *cap = prim
            cx, cy = arc_center(*a, *b, r)
            start = math.degrees(math.atan2(a[1] - cy, a[0] - cx))
            end = math.degrees(math.atan2(b[1] - cy, b[0] - cx))
            box = [dx + (cx - r - w / 2) * k, dy + (cy - r - w / 2) * k,
                   dx + (cx + r + w / 2) * k, dy + (cy + r + w / 2) * k]
            dr.arc(box, start, end, fill=_rgba(color), width=round(w * k))
            if not cap or cap[0] == "round":
                for x, y in (a, b):
                    _cap(dr, dx + x * k, dy + y * k, w * k, _rgba(color))
        elif kind == "ring":
            _, c, r, color, w = prim
            box = [dx + (c[0] - r - w / 2) * k, dy + (c[1] - r - w / 2) * k,
                   dx + (c[0] + r + w / 2) * k, dy + (c[1] + r + w / 2) * k]
            dr.ellipse(box, outline=_rgba(color), width=round(w * k))
        elif kind == "dot":
            _, c, r, fill, stroke, sw = prim
            rr = r + (sw / 2 if stroke else 0)
            box = [dx + (c[0] - rr) * k, dy + (c[1] - rr) * k, dx + (c[0] + rr) * k, dy + (c[1] + rr) * k]
            dr.ellipse(box, fill=_rgba(stroke or fill))
            if stroke:
                ri = r - sw / 2
                dr.ellipse([dx + (c[0] - ri) * k, dy + (c[1] - ri) * k, dx + (c[0] + ri) * k, dy + (c[1] + ri) * k],
                           fill=_rgba(fill))
        else:
            raise ValueError(kind)
        if op < 1:
            alpha = layer.getchannel("A").point(lambda v: round(v * op))
            layer.putalpha(alpha)
        im.alpha_composite(layer)


def _png_bytes(im: Image.Image) -> bytes:
    info = PngInfo()
    info.add_text("Author", "Adam Jannoud (AdamJannoud)")
    info.add_text("Copyright", CREDIT)
    info.add_text("bio-rig-generator", GENERATOR)
    buf = io.BytesIO()
    im.save(buf, format="PNG", optimize=False, compress_level=9, pnginfo=info)
    return buf.getvalue()


def render_square(prims: list[tuple], px: int) -> Image.Image:
    ss = px * SUPERSAMPLE
    im = Image.new("RGBA", (ss, ss), (0, 0, 0, 0))
    _paint(im, prims, ss / GRID)
    return im.resize((px, px), Image.LANCZOS)


def render_lockup(scale: int = 4) -> Image.Image:
    w, h = lockup_size()
    ss = scale * SUPERSAMPLE
    W, H = math.ceil(w * scale), math.ceil(h * scale)
    im = Image.new("RGBA", (W * SUPERSAMPLE, H * SUPERSAMPLE), (0, 0, 0, 0))
    ImageDraw.Draw(im).rounded_rectangle([0, 0, im.width - 1, im.height - 1], radius=12 * ss, fill=_rgba(FOREST))
    _paint(im, mark(inverse=True), MARK_PX / GRID * ss, PAD_X * ss, PAD_Y * ss)
    dr = ImageDraw.Draw(im)
    f = _font(round(WORD_PX * ss))
    x = (PAD_X + MARK_PX + GAP) * ss
    base = (h / 2 + WORD_PX * 0.36) * ss
    for ch in "BioRig.":
        dr.text((x, base), ch, font=f, fill=_rgba(GOLD_DEEP if ch == "." else WHITE), anchor="ls")
        x += f.getlength(ch) + WORD_TRACK * ss
    return im.resize((W, H), Image.LANCZOS)


def render_ico() -> bytes:
    buf = io.BytesIO()
    big = render_square(favicon(), 48)
    big.save(buf, format="ICO", sizes=[(16, 16), (32, 32), (48, 48)],
             append_images=[render_square(favicon(), 16), render_square(favicon(), 32)])
    return buf.getvalue()


# --------------------------------------------------------------------------- outputs

def outputs() -> dict[Path, bytes]:
    """Every file this generator owns, path -> bytes."""
    b, d = BRAND_DIR, DASHBOARD_BRAND_DIR
    label = "BioRig brandmark: two interlocking gold rings forming a canopy over a forest trunk and a biometric node"
    out = {
        b / "biorig-mark.svg": svg_doc(mark(), label).encode(),
        b / "biorig-mark-reverse.svg": svg_doc(mark(inverse=True), label).encode(),
        b / "biorig-lockup.svg": lockup_svg().encode(),
        b / "biorig-icon-64.svg": svg_doc(icon_64(), "BioRig icon, 64 px", 64).encode(),
        b / "biorig-icon-32.svg": svg_doc(icon_32(), "BioRig icon, 32 px", 32).encode(),
        b / "favicon.svg": svg_doc(favicon(), "BioRig favicon", 16).encode(),
        b / "biorig-mark.png": _png_bytes(render_square(mark(), 512)),
        b / "biorig-mark-reverse.png": _png_bytes(render_square(mark(inverse=True), 512)),
        b / "biorig-lockup.png": _png_bytes(render_lockup()),
        b / "favicon-16.png": _png_bytes(render_square(favicon(), 16)),
        b / "favicon-32.png": _png_bytes(render_square(favicon(), 32)),
        b / "favicon.ico": render_ico(),
        d / "mark.svg": svg_doc(mark(stroke=7, ground=False), label, 30).encode(),
        d / "mark-reverse.svg": svg_doc(mark(stroke=7, inverse=True, ground=False), label, 30).encode(),
        d / "favicon.png": _png_bytes(render_square(favicon(), 64)),
    }
    return out


def _rel(p: Path) -> str:
    return str(p.relative_to(ROOT))


def stale(files: dict[Path, bytes]) -> list[str]:
    """SVGs must match a fresh render byte for byte; rasters must decode at the expected size and carry the
    generator's provenance chunk (a Pillow/FreeType rebuild can move edge pixels, so they are not byte-compared)."""
    problems = []
    for path, data in files.items():
        if not path.exists():
            problems.append(f"missing: {_rel(path)}")
        elif path.suffix == ".svg":
            if path.read_bytes() != data:
                problems.append(f"stale: {_rel(path)}")
        else:
            try:
                with Image.open(path) as have, Image.open(io.BytesIO(data)) as want:
                    have.load()
                    ok = have.size == want.size and (path.suffix == ".ico"
                                                     or getattr(have, "text", {}).get("bio-rig-generator") == GENERATOR)
            except Exception as e:  # noqa: BLE001 - any decode failure means the file is not usable
                problems.append(f"bad: {_rel(path)} does not decode ({e})")
                continue
            if not ok:
                problems.append(f"stale: {_rel(path)} size or provenance differs from a fresh render")
    return problems


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--check", action="store_true", help="exit 1 if an output is missing or stale")
    args = ap.parse_args(argv)
    files = outputs()
    if args.check:
        problems = stale(files)
        for p in problems:
            print(p, file=sys.stderr)
        return 1 if problems else 0
    for path, data in files.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    print(f"wrote {len(files)} files under {_rel(BRAND_DIR)}/ and {_rel(DASHBOARD_BRAND_DIR)}/")
    return 0


if __name__ == "__main__":
    sys.exit(main())
