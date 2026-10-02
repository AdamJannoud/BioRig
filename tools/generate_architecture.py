"""Generate the BioRig end-to-end architecture diagram from the recorded deployment.

    .venv/bin/python tools/generate_architecture.py          # write all three outputs
    .venv/bin/python tools/generate_architecture.py --check  # exit 1 if an output on disk is stale

Outputs:
  assets/BioRig_Architecture_v5.svg   vector source, 2400 px wide
  assets/BioRig_Architecture_v5.svg.sha256  provenance: sha256sum line for the SVG the PNG was rendered with
  BioRig_Architecture_Pro.png         raster, 4800 px wide (4x the design grid), RGB, carrying two PNG tEXt chunks:
    bio-rig-source-svg-sha256         lowercase-hex sha256 of the SVG bytes this raster was rendered with
    bio-rig-generator                 tools/generate_architecture.py

Every address, the chain id, the proxy block and the deploy date are read from dashboard/deployment.json and
the DeployAll broadcast under broadcast/, never typed in here; the two records are cross-checked and the
generator refuses to draw if they disagree. The chain drawn is the record's default chain (--chain-id picks
another recorded one); its name and canonical ERC-6551 registry come from dashboard/chains.json.

Rasterisation route: the diagram is one list of primitives (rect, text, path) in a 1200-unit design grid.
The SVG writer and the Pillow painter both consume that list, so the PNG is rendered from the same source as
the SVG without an SVG rasteriser. None of the usable ones exist here (cairosvg, rsvg-convert and inkscape are
not installed, and ImageMagick's built-in MSVG delegate ignores dash arrays and substitutes fonts), so there
is deliberately no fallback to `convert`. Fonts are the DejaVu faces vendored in assets/fonts/, which keeps the
output byte-identical from run to run and independent of the host's font set. No network access is needed.

The BioRig brandmark beside the title is not redrawn here: it is tools/generate_brand.py's mark() geometry, written
and painted by that module's own _svg_prims and _paint, so the diagram's mark cannot drift from the brand kit.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import html
import io
import json
import math
import re
import sys
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont
from PIL.PngImagePlugin import PngInfo

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from dashboard.config import ChainSelectionError, chain_config, recorded_deployment  # noqa: E402
from tools import generate_brand as brand  # noqa: E402

DEPLOYMENT_JSON = ROOT / "dashboard" / "deployment.json"
BROADCAST_DIR = ROOT / "broadcast" / "DeployAll.s.sol"
SVG_OUT = ROOT / "assets" / "BioRig_Architecture_v5.svg"
SVG_SHA_OUT = SVG_OUT.with_name(SVG_OUT.name + ".sha256")
PNG_OUT = ROOT / "BioRig_Architecture_Pro.png"
FONT_DIR = ROOT / "assets" / "fonts"
# PNG tEXt keys recording which SVG the raster was rendered with; --check requires them to name the fresh SVG.
PNG_SVG_SHA_KEY = "bio-rig-source-svg-sha256"
PNG_GENERATOR_KEY = "bio-rig-generator"
GENERATOR = "tools/generate_architecture.py"

GRID_W, GRID_H = 1200, 1062  # design grid; the SVG is 2x, the PNG 4x
SVG_SCALE = 2
PNG_SCALE = 4
SUPERSAMPLE = 2  # the PNG is painted at PNG_SCALE * SUPERSAMPLE and downsampled, which anti-aliases strokes

# Result of the last full `forge test` run over test/ (16 suites). Not derivable from the deployment record,
# so it is the one number kept by hand: update it when the suite changes.
CONTRACT_TESTS = 175
DASHBOARD_URL = "biorigdemo.streamlit.app"

ADDRESS_RE = re.compile(r"0x[0-9a-fA-F]{40}")


# --------------------------------------------------------------------------- deployment facts

class DeploymentMismatch(ValueError):
    """dashboard/deployment.json and the broadcast record disagree, or the broadcast is incomplete."""


@dataclass(frozen=True)
class Facts:
    chain_id: int
    proxy: str
    proxy_block: int
    core_implementation: str
    registry: str
    account_implementation: str
    deployed_on: dt.date
    chain_name: str

    def addresses(self) -> dict[str, str]:
        return {
            "proxy": self.proxy,
            "core_implementation": self.core_implementation,
            "registry": self.registry,
            "account_implementation": self.account_implementation,
        }


def _word(calldata: bytes, i: int) -> bytes:
    return calldata[4 + 32 * i: 4 + 32 * (i + 1)]


def load_facts(deployment_path: Path = DEPLOYMENT_JSON, broadcast_dir: Path = BROADCAST_DIR,
               chain_id: int | None = None) -> Facts:
    try:
        chain_id, recorded_proxy, recorded_block = recorded_deployment(deployment_path, chain_id)
        chain = chain_config(chain_id)
    except (ValueError, ChainSelectionError) as exc:
        raise DeploymentMismatch(f"{deployment_path.name}: {exc}") from exc
    run = json.loads((broadcast_dir / str(chain_id) / "run-latest.json").read_text())
    if int(run["chain"]) != chain_id:
        raise DeploymentMismatch(f"broadcast chain {run['chain']} != deployment.json chain_id {chain_id}")

    created: dict[str, tuple[str, dict]] = {}
    for tx in run["transactions"]:
        if tx["transactionType"] in ("CREATE", "CREATE2") and tx.get("contractAddress"):
            created[tx.get("contractName") or tx["transactionType"]] = (tx["contractAddress"].lower(), tx)
    for name in ("ERC1967Proxy", "BioRigCoreV5", "ERC6551Account"):
        if name not in created:
            raise DeploymentMismatch(f"broadcast has no {name} creation")
    blocks = {r["contractAddress"].lower(): int(r["blockNumber"], 16)
              for r in run["receipts"] if r.get("contractAddress")}

    proxy, proxy_tx = created["ERC1967Proxy"]
    if proxy != recorded_proxy:
        raise DeploymentMismatch(f"broadcast proxy {proxy} != deployment.json proxy {recorded_proxy}")
    if blocks.get(proxy) != recorded_block:
        raise DeploymentMismatch(f"broadcast proxy block {blocks.get(proxy)} != deployment.json "
                                 f"proxy_deploy_block {recorded_block}")

    # The proxy's constructor args are (implementation, initialize calldata). Reading the registry and account
    # implementation out of initialize(admin, registry, implementation, chainId, bufferPool, uriGenerator)
    # gives the addresses the live proxy was actually wired to, not merely contracts the script created.
    impl_arg, init_hex = proxy_tx["arguments"][0], proxy_tx["arguments"][1]
    init = bytes.fromhex(init_hex[2:])
    registry = "0x" + _word(init, 1)[12:].hex()
    account_impl = "0x" + _word(init, 2)[12:].hex()
    init_chain = int.from_bytes(_word(init, 3), "big")

    core = created["BioRigCoreV5"][0]
    if impl_arg.lower() != core:
        raise DeploymentMismatch(f"proxy points at {impl_arg}, broadcast BioRigCoreV5 is {core}")
    if account_impl != created["ERC6551Account"][0]:
        raise DeploymentMismatch(f"proxy initialised with account impl {account_impl}, "
                                 f"broadcast ERC6551Account is {created['ERC6551Account'][0]}")
    # Where the canonical registry already had code (Celo mainnet) the broadcast holds no CREATE2 at all, so the
    # chain config is what the wiring is checked against; a CREATE2, where there is one, must agree as well.
    if registry != chain.erc6551_registry:
        raise DeploymentMismatch(f"proxy initialised with registry {registry}, chains.json has "
                                 f"{chain.erc6551_registry} for chain {chain_id}")
    if "CREATE2" in created and created["CREATE2"][0] != registry:
        raise DeploymentMismatch(f"proxy initialised with registry {registry}, "
                                 f"broadcast CREATE2 deployed {created['CREATE2'][0]}")
    if init_chain != chain_id:
        raise DeploymentMismatch(f"proxy initialised with chain id {init_chain}, expected {chain_id}")

    deployed_on = dt.datetime.fromtimestamp(int(run["timestamp"]) / 1000, dt.timezone.utc).date()
    return Facts(chain_id, proxy, recorded_block, core, registry, account_impl, deployed_on, chain.name)


# --------------------------------------------------------------------------- primitives

# Light, print-safe palette from the approved plan. green = deployed & verified, amber = roadmap / pending.
INK, BODY, MUTED, ADDR = "#14181f", "#3d4753", "#5b6674", "#2b4f9e"
LIVE, LIVE_BG, ROAD, ROAD_BG = "#1f7a4d", "#eaf6ef", "#9a6400", "#fdf4e3"
BOX_STROKE, EDGE = "#c3cbd6", "#5b6674"

# style -> (face, size in grid units, fill, letter spacing)
STYLES = {
    "title": ("bold", 21, INK, 0.0),
    "t": ("bold", 14, INK, 0.0),
    "b": ("regular", 12, BODY, 0.0),
    "m": ("mono", 10.5, ADDR, 0.0),
    "lbl": ("regular", 11, MUTED, 0.0),
    "band": ("bold", 12, MUTED, 0.96),
    "badge": ("bold", 10.5, ROAD, 0.6),
}
FACES = {"regular": "DejaVuSans.ttf", "bold": "DejaVuSans-Bold.ttf", "mono": "DejaVuSansMono.ttf"}
SVG_FAMILY = {"regular": "'DejaVu Sans',Verdana,Arial,sans-serif",
              "bold": "'DejaVu Sans',Verdana,Arial,sans-serif",
              "mono": "'DejaVu Sans Mono',Menlo,Consolas,monospace"}


@dataclass(frozen=True)
class Rect:
    x: float
    y: float
    w: float
    h: float
    fill: str
    stroke: str | None = None
    sw: float = 1.4
    r: float = 9
    dash: tuple[float, ...] | None = None


@dataclass(frozen=True)
class Text:
    x: float
    y: float  # baseline
    text: str
    style: str
    anchor: str = "start"  # start | middle | end
    fill: str | None = None
    box: str | None = None  # id of the box this text belongs to, for tests


@dataclass(frozen=True)
class Path:
    # ("M", x, y) | ("L", x, y) | ("C", x1, y1, x2, y2, x, y)
    cmds: tuple[tuple, ...]
    stroke: str = EDGE
    sw: float = 1.4
    dash: tuple[float, ...] | None = None
    arrow: bool = True


@dataclass(frozen=True)
class Mark:
    """A brand-kit primitive list (tools/generate_brand.py, 96-unit grid) placed in a size x size square."""
    x: float
    y: float
    size: float
    prims: tuple[tuple, ...]


@dataclass
class Scene:
    w: float
    h: float
    items: list = field(default_factory=list)
    boxes: dict[str, Rect] = field(default_factory=dict)

    def texts(self) -> list[Text]:
        return [i for i in self.items if isinstance(i, Text)]

    def addresses(self) -> list[str]:
        return [a for t in self.texts() for a in ADDRESS_RE.findall(t.text)]


ARROW_LEN, ARROW_HALF = 9.0, 4.2


def _flatten(cmds, steps: int = 32) -> list[tuple[float, float]]:
    pts: list[tuple[float, float]] = []
    for c in cmds:
        if c[0] in ("M", "L"):
            pts.append((c[1], c[2]))
        else:
            x0, y0 = pts[-1]
            x1, y1, x2, y2, x3, y3 = c[1:]
            for i in range(1, steps + 1):
                t = i / steps
                u = 1 - t
                pts.append((u ** 3 * x0 + 3 * u * u * t * x1 + 3 * u * t * t * x2 + t ** 3 * x3,
                            u ** 3 * y0 + 3 * u * u * t * y1 + 3 * u * t * t * y2 + t ** 3 * y3))
    return pts


def _arrow(path: Path) -> tuple[list[tuple[float, float]], tuple]:
    """Arrowhead triangle at the end of the path, and the path's commands shortened so the stroke stops at
    the arrow's base instead of poking through its tip. Shared by both renderers."""
    pts = _flatten(path.cmds)
    (tx, ty) = pts[-1]
    # walk back along the flattened curve to the point ARROW_LEN away, for a stable direction
    bx, by = pts[-2]
    for p in reversed(pts[:-1]):
        bx, by = p
        if math.hypot(tx - bx, ty - by) >= ARROW_LEN:
            break
    d = math.hypot(tx - bx, ty - by) or 1.0
    ux, uy = (tx - bx) / d, (ty - by) / d
    base = (tx - ux * ARROW_LEN, ty - uy * ARROW_LEN)
    tri = [(tx, ty), (base[0] - uy * ARROW_HALF, base[1] + ux * ARROW_HALF),
           (base[0] + uy * ARROW_HALF, base[1] - ux * ARROW_HALF)]
    last = path.cmds[-1]
    stop = (base[0] + ux * 1.5, base[1] + uy * 1.5)
    if last[0] == "C":
        shortened = path.cmds[:-1] + (("C", last[1], last[2], last[3], last[4], *stop),)
    else:
        shortened = path.cmds[:-1] + ((last[0], *stop),)
    return tri, shortened


def _round_rect(r: Rect) -> list[tuple[float, float]]:
    rad = min(r.r, r.w / 2, r.h / 2)
    pts = [(r.x + rad, r.y)]  # start where an SVG <rect> starts its dash pattern
    corners = [(r.x + r.w - rad, r.y + rad, -90), (r.x + r.w - rad, r.y + r.h - rad, 0),
               (r.x + rad, r.y + r.h - rad, 90), (r.x + rad, r.y + rad, 180)]
    for cx, cy, a0 in corners:
        for i in range(9):
            a = math.radians(a0 + 90 * i / 8)
            pts.append((cx + rad * math.cos(a), cy + rad * math.sin(a)))
    return pts


# --------------------------------------------------------------------------- measuring

@lru_cache(maxsize=None)
def _font(face: str, px: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(str(FONT_DIR / FACES[face]), px)


def text_width(text: str, style: str) -> float:
    """Advance width in grid units, measured with the same face the PNG is painted with."""
    face, size, _, ls = STYLES[style]
    return _font(face, round(size * 64)).getlength(text) / 64 + ls * len(text)


def overflows(scene: Scene) -> list[str]:
    """Texts that spill out of the box they belong to (10 units of right padding). Empty when the layout fits."""
    bad = []
    for t in scene.texts():
        if t.box is None:
            continue
        r = scene.boxes[t.box]
        w = text_width(t.text, t.style)
        left = t.x - {"start": 0, "middle": w / 2, "end": w}[t.anchor]
        if left < r.x + 4 or left + w > r.x + r.w - 6:
            bad.append(f"{t.box}: {t.text!r} is {w:.0f} wide, box interior ends at {r.x + r.w - 6:.0f}")
    return bad


# --------------------------------------------------------------------------- SVG writer

def _n(v: float) -> str:
    return f"{v:.2f}".rstrip("0").rstrip(".")


def _svg_dash(dash) -> str:
    return f' stroke-dasharray="{" ".join(_n(d) for d in dash)}"' if dash else ""


def _d(cmds) -> str:
    return " ".join(c[0] + " ".join(_n(v) for v in c[1:]) for c in cmds)


def render_svg(scene: Scene, scale: int = SVG_SCALE, title: str = "") -> str:
    out = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{_n(scene.w * scale)}" height="{_n(scene.h * scale)}" '
        f'viewBox="0 0 {_n(scene.w)} {_n(scene.h)}" role="img" aria-label="{html.escape(title)}">',
        f"<title>{html.escape(title)}</title>",
        "<!-- Generated by tools/generate_architecture.py from dashboard/deployment.json and "
        "broadcast/DeployAll.s.sol. Do not edit by hand: change the generator and re-run it. -->",
        f'<rect width="{_n(scene.w)}" height="{_n(scene.h)}" fill="#ffffff"/>',
    ]
    for it in scene.items:
        if isinstance(it, Rect):
            stroke = f' stroke="{it.stroke}" stroke-width="{_n(it.sw)}"' if it.stroke else ""
            out.append(f'<rect x="{_n(it.x)}" y="{_n(it.y)}" width="{_n(it.w)}" height="{_n(it.h)}" '
                       f'rx="{_n(it.r)}" fill="{it.fill}"{stroke}{_svg_dash(it.dash)}/>')
        elif isinstance(it, Path):
            cmds = it.cmds
            if it.arrow:
                tri, cmds = _arrow(it)
            out.append(f'<path d="{_d(cmds)}" fill="none" stroke="{it.stroke}" stroke-width="{_n(it.sw)}" '
                       f'stroke-linejoin="round"{_svg_dash(it.dash)}/>')
            if it.arrow:
                pts = " ".join(f"{_n(x)},{_n(y)}" for x, y in tri)
                out.append(f'<polygon points="{pts}" fill="{it.stroke}"/>')
        elif isinstance(it, Text):
            face, size, fill, ls = STYLES[it.style]
            weight = ' font-weight="bold"' if face == "bold" else ""
            spacing = f' letter-spacing="{_n(ls)}"' if ls else ""
            anchor = f' text-anchor="{it.anchor}"' if it.anchor != "start" else ""
            out.append(f'<text x="{_n(it.x)}" y="{_n(it.y)}" font-family="{SVG_FAMILY[face]}" '
                       f'font-size="{_n(size)}"{weight}{spacing}{anchor} fill="{it.fill or fill}">'
                       f"{html.escape(it.text, quote=False)}</text>")
        elif isinstance(it, Mark):
            out.append('<g id="biorig-mark" aria-label="BioRig brandmark">')
            out += brand._svg_prims(list(it.prims), it.size / brand.GRID, it.x, it.y)
            out.append("</g>")
    out.append("</svg>")
    return "\n".join(out) + "\n"


# --------------------------------------------------------------------------- PNG painter

def _dashed(pts, pattern):
    """Split a polyline into the 'on' runs of a dash pattern, continuing the pattern across vertices."""
    runs, cur = [], [pts[0]]
    idx, left, on = 0, pattern[0], True
    for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
        seg = math.hypot(x1 - x0, y1 - y0)
        pos = 0.0
        while seg - pos > left:
            pos += left
            p = (x0 + (x1 - x0) * pos / seg, y0 + (y1 - y0) * pos / seg)
            if on:
                cur.append(p)
                runs.append(cur)
            cur = [p]
            on = not on
            idx = (idx + 1) % len(pattern)
            left = pattern[idx]
        left -= seg - pos
        cur.append((x1, y1))
    if on and len(cur) > 1:
        runs.append(cur)
    return runs


def _stroke(dr: ImageDraw.ImageDraw, pts, color: str, sw: float, dash, k: float) -> None:
    width = max(1, round(sw * k))
    scaled = [(x * k, y * k) for x, y in pts]
    runs = _dashed(scaled, [d * k for d in dash]) if dash else [scaled]
    for run in runs:
        dr.line(run, fill=color, width=width, joint="curve")


def render_png(scene: Scene, scale: int = PNG_SCALE, supersample: int = SUPERSAMPLE,
               source_svg_sha256: str | None = None) -> bytes:
    k = scale * supersample
    im = Image.new("RGB", (round(scene.w * k), round(scene.h * k)), "#ffffff")
    dr = ImageDraw.Draw(im)
    for it in scene.items:
        if isinstance(it, Rect):
            pts = _round_rect(it)
            dr.polygon([(x * k, y * k) for x, y in pts], fill=it.fill)
            if it.stroke:
                _stroke(dr, pts + [pts[0]], it.stroke, it.sw, it.dash, k)
        elif isinstance(it, Path):
            cmds, tri = it.cmds, None
            if it.arrow:
                tri, cmds = _arrow(it)
            _stroke(dr, _flatten(cmds), it.stroke, it.sw, it.dash, k)
            if tri:
                dr.polygon([(x * k, y * k) for x, y in tri], fill=it.stroke)
        elif isinstance(it, Text):
            face, size, fill, ls = STYLES[it.style]
            font = _font(face, round(size * k))
            color = it.fill or fill
            if not ls:
                dr.text((it.x * k, it.y * k), it.text, font=font, fill=color,
                        anchor={"start": "ls", "middle": "ms", "end": "rs"}[it.anchor])
                continue
            w = text_width(it.text, it.style)
            x = (it.x - {"start": 0, "middle": w / 2, "end": w}[it.anchor]) * k
            for ch in it.text:
                dr.text((x, it.y * k), ch, font=font, fill=color, anchor="ls")
                x += font.getlength(ch) + ls * k
        elif isinstance(it, Mark):
            # brand._paint composites one full-canvas RGBA layer per primitive, so it is given only the mark's
            # own square (a few hundred px) rather than the supersampled diagram, and the result is pasted back.
            box = (round(it.x * k), round(it.y * k), round((it.x + it.size) * k), round((it.y + it.size) * k))
            tile = im.crop(box).convert("RGBA")
            brand._paint(tile, list(it.prims), (box[2] - box[0]) / brand.GRID)
            im.paste(tile.convert("RGB"), box[:2])
    im = im.resize((round(scene.w * scale), round(scene.h * scale)), Image.LANCZOS)
    info = None
    if source_svg_sha256 is not None:
        info = PngInfo()
        info.add_text(PNG_SVG_SHA_KEY, source_svg_sha256)
        info.add_text(PNG_GENERATOR_KEY, GENERATOR)
    buf = io.BytesIO()
    im.save(buf, format="PNG", optimize=False, compress_level=9, pnginfo=info)
    return buf.getvalue()


# --------------------------------------------------------------------------- the diagram

COL_W = 320
COL_A, COL_B, COL_C = 56, 440, 824  # three columns, 64-unit gutters, 32-unit margins inside the bands
ROW_H = 112
MARK_X, MARK_Y, MARK_SIZE = 28, 12, 54  # header brandmark: top aligned with the legend, clear of band 1 at y 90
KINDS = {  # box kind -> (fill, stroke, stroke width, dash)
    "live": (LIVE_BG, LIVE, 1.6, None),
    "plain": ("#ffffff", BOX_STROKE, 1.4, None),
    "road": (ROAD_BG, ROAD, 1.4, (5, 4)),
}


def _box(sc: Scene, bid: str, x, y, w, h, kind: str, title: str, lines: list[tuple[str, str]]) -> None:
    fill, stroke, sw, dash = KINDS[kind]
    sc.boxes[bid] = Rect(x, y, w, h, fill, stroke, sw, 9, dash)
    sc.items.append(sc.boxes[bid])
    sc.items.append(Text(x + 18, y + 25, title, "t", box=bid))
    for i, (style, text) in enumerate(lines):
        sc.items.append(Text(x + 18, y + 47 + 18 * i, text, style, box=bid))


def _pill(sc: Scene, bid: str, x, baseline, text: str, anchor: str = "start") -> float:
    w = text_width(text, "badge") + 14
    if anchor == "end":
        x -= w
    sc.items.append(Rect(x, baseline - 12, w, 17, ROAD_BG, ROAD, 1.1, 8.5, (3, 2)))
    sc.items.append(Text(x + 7, baseline, text, "badge", box=bid))
    return w


def _band(sc: Scene, y, h, fill, stroke, dash, label: str, note: str | None) -> None:
    sc.items.append(Rect(24, y, 1152, h, fill, stroke, 1.2, 12, dash))
    sc.items.append(Text(44, y + 24, label, "band"))
    if note:
        sc.items.append(Text(44, y + 41, note, "lbl"))


def _edge(sc: Scene, *cmds, road: bool = False, dash=None, arrow: bool = True) -> None:
    if road:
        sc.items.append(Path(tuple(cmds), stroke=ROAD, dash=(5, 4), arrow=arrow))
    else:
        sc.items.append(Path(tuple(cmds), dash=dash, arrow=arrow))


def _label(sc: Scene, x, y, text: str, anchor: str = "start") -> None:
    sc.items.append(Text(x, y, text, "lbl", anchor))


def build_scene(f: Facts) -> Scene:
    sc = Scene(GRID_W, GRID_H)
    A, B, C, W = COL_A, COL_B, COL_C, COL_W

    # ---- brandmark + title + legend
    # The header is white, where the light mark's GOLD_DEEP rings wash out, so it is the reverse (gold) mark on a
    # forest tile: the same treatment as the lockup and the favicon.
    sc.items.append(Mark(MARK_X, MARK_Y, MARK_SIZE, (("tile", 20, brand.FOREST), *brand.mark(inverse=True))))
    tx = MARK_X + MARK_SIZE + 14
    sc.items.append(Text(tx, 38, "BioRig — end-to-end system architecture", "title"))
    _label(sc, tx, 60, f"{f.chain_name} · chain id {f.chain_id} · deployed {f.deployed_on.day} "
                       f"{f.deployed_on:%b %Y} · all four contracts verified on Blockscout")
    sc.boxes["legend"] = Rect(862, 12, 310, 66, "#f5f7fa", "#d8dde5", 1.0, 8)
    sc.items.append(sc.boxes["legend"])
    sc.items.append(Rect(876, 22, 16, 11, LIVE_BG, LIVE, 1.4, 3))
    sc.items.append(Text(900, 32, f"deployed & verified on {f.chain_name}", "lbl", box="legend"))
    sc.items.append(Rect(876, 40, 16, 11, ROAD_BG, ROAD, 1.2, 3, (3, 2)))
    sc.items.append(Text(900, 50, "roadmap — not implemented", "lbl", box="legend"))
    sc.items.append(Rect(876, 58, 16, 11, "#ffffff", BOX_STROKE, 1.2, 3))
    sc.items.append(Text(900, 68, "off-chain, or not yet publicly hosted", "lbl", box="legend"))

    # ---- band 1: off-chain edge capture
    _band(sc, 90, 214, "#fbfcfe", "#e2e7ee", (7, 5), "OFF-CHAIN / EDGE CAPTURE — MOBILE dMRV",
          "untrusted tier: no component here is executed or verified by the contract")
    y1 = 146
    _box(sc, "mobile", A, y1, W, ROW_H, "plain", "Mobile client — Android / iOS", [
        ("b", "budget smartphone; DBH + biomass"),
        ("b", "measured on device by monocular"),
        ("b", "depth estimation"),
        ("lbl", "Edge AI · no server round trip"),
    ])
    _box(sc, "h3", B, y1, W, ROW_H, "plain", "H3 spatial nullifier", [
        ("m", "keccak256(uint64(h3Cell) ++ plotSalt)"),
        ("b", "res-12 cell (≈ 307 m²) → bytes32"),
        ("lbl", "landholder privacy: exact GPS never"),
        ("lbl", "leaves the device"),
    ])
    _box(sc, "prover", C, y1, W, ROW_H, "plain", "zk-ML prover — off-chain witness", [
        ("b", "biometric growth vector → attestation"),
        ("b", "anti-Sybil / double-count defence"),
        ("lbl", "witness stays off-chain: the contract"),
        ("lbl", "verifies no proof (trust = VERIFIER_ROLE)"),
    ])
    _edge(sc, ("M", A + W, y1 + 44), ("L", B, y1 + 44))
    _label(sc, (A + W + B) / 2, y1 + 37, "GPS", "middle")
    _edge(sc, ("M", B + W, y1 + 44), ("L", C, y1 + 44))
    _label(sc, (B + W + C) / 2, y1 + 37, "nullifier", "middle")
    yb = y1 + ROW_H
    _edge(sc, ("M", A + 160, yb), ("C", A + 160, yb + 34, C + 160, yb + 34, C + 160, yb + 1))
    _label(sc, A + 200, yb + 38, "biometric vectors")

    # ---- handoff into the chain
    y2 = 390
    _label(sc, 610, 322, "verifier-signed tx · nullifier + DBH + biomass")

    # ---- band 2: on-chain execution
    _band(sc, 332, 358, "#f4fbf6", "#bfe0cb", None, f"ON-CHAIN EXECUTION — {f.chain_name.upper()}",
          f"chain id {f.chain_id} · UUPS upgradeable · {CONTRACT_TESTS} contract tests green")
    _edge(sc, ("M", 600, yb), ("L", 600, y2))  # after the band, so the band's fill does not cover it
    _box(sc, "access", A, y2, W, ROW_H, "live", "Access control", [
        ("b", "mintTree / updateTreeGrowth /"),
        ("b", "reportMortality"),
        ("m", "onlyRole(VERIFIER_ROLE)"),
        ("lbl", "the trust boundary: no proof is checked"),
    ])
    _box(sc, "proxy", B, y2, W, ROW_H, "live", "ERC1967Proxy — live entry point", [
        ("m", f.proxy),
        ("b", f"deployed in block {f.proxy_block}"),
        ("lbl", "the only address anyone integrates"),
        ("lbl", "against"),
    ])
    _box(sc, "nft", C, y2, W, ROW_H, "live", "ERC-721 dynamic NFT", [
        ("b", "1 token = 1 monitored tree"),
        ("m", "getTreeStats(tokenId) → DBH, biomass, TBA"),
        ("lbl", "tokenURI grows with the tree"),
        ("lbl", "(I-6 setBaseURI)"),
    ])
    y3 = y2 + ROW_H + 28
    _box(sc, "registry", A, y3, W, ROW_H, "live", "Canonical ERC-6551 registry", [
        ("m", f.registry),
        ("b", "account implementation"),
        ("m", f.account_implementation),
    ])
    _box(sc, "core", B, y3, W, ROW_H, "live", "BioRigCoreV5 — implementation", [
        ("m", f.core_implementation),
        ("b", "nullifier registry: a plot mints once"),
        ("lbl", "revert NullifierInUse on replay"),
        ("lbl", "mintTree calls registry.createAccount"),
    ])
    _box(sc, "tba", C, y3, W, ROW_H, "live", "Token-bound account (TBA)", [
        ("b", "one smart wallet per tree, deployed"),
        ("b", "by the registry at CREATE2 salt"),
        ("m", "keccak256(tokenId ++ planter ++ nullifier)"),
    ])
    _edge(sc, ("M", A + W, y2 + 56), ("L", B, y2 + 56))
    _label(sc, (A + W + B) / 2, y2 + 49, "gates", "middle")
    _edge(sc, ("M", B + W, y2 + 56), ("L", C, y2 + 56))
    _label(sc, (B + W + C) / 2, y2 + 49, "mint", "middle")
    _edge(sc, ("M", 600, y2 + ROW_H), ("L", 600, y3))
    _label(sc, 610, y3 - 9, "delegatecall (UUPS)")
    _edge(sc, ("M", B, y3 + 56), ("L", A + W, y3 + 56))
    _label(sc, (A + W + B) / 2, y3 + 49, "call", "middle")
    _edge(sc, ("M", C + 160, y3), ("L", C + 160, y2 + ROW_H), dash=(2, 3))
    _label(sc, C + 170, y3 - 9, "token() → this NFT")
    yb3 = y3 + ROW_H
    _edge(sc, ("M", A + 160, yb3), ("C", A + 160, yb3 + 42, C + 160, yb3 + 42, C + 160, yb3 + 1))
    _label(sc, 600, yb3 + 21, "createAccount deploys one TBA per token", "middle")

    # ---- band 3: roadmap
    y4 = 770
    _band(sc, 712, 194, "#fffdf7", "#e8c47a", (9, 6), "PROTOCOL & DOWNSTREAM — ROADMAP",
          "none of this is in BioRigCoreV5 today; drawn to show intent, badged so it cannot be read as shipped")
    rw, gap = 254, 24
    xs = [A + i * (rw + gap) for i in range(4)]
    road = [
        ("accrual", "TBA carbon accrual", ["micro-streamed offsets as", "verified biomass increases"], None),
        ("buffer", "Buffer pool — 20%", ["solvency deduction against", "natural mortality / pestilence"],
         "address stored, no routing"),
        ("rails", "ReFi data rails", ["Toucan / Flowcarbon ingest", "from the same tree records"], None),
        ("demand", "Demand side", ["Scope 3 enterprise buyers", "routing capital to stewards"], None),
    ]
    for x, (bid, title, lines, note) in zip(xs, road):
        _box(sc, bid, x, y4, rw, 116, "road", title,
             [("b", t) for t in lines] + ([("lbl", note)] if note else []))
        _pill(sc, bid, x + 18, y4 + 104, "[ROADMAP]")
    _edge(sc, ("M", 470, yb3), ("L", 470, y4), road=True)
    _label(sc, 478, 705, "bufferPool: an address, nothing routed")
    _edge(sc, ("M", 1060, yb3), ("L", 1060, y4), road=True)

    # ---- band 4: client interfaces
    _band(sc, 926, 124, "#f7f9fd", "#c9d5ea", None, "CLIENT & DEMONSTRATION INTERFACES", None)
    _label(sc, 1144, 950, "reads the proxy over eth_call: getTreeStats, tokenURI", "end")
    y5 = 962
    _box(sc, "dashboard", A, y5, 1088, 76, "plain", "Streamlit demo dashboard — read-only by default", [
        ("b", "live telemetry read from the proxy · H3 res-12 cell simulation"),
        ("b", "offline TBA derivation · server-side signing, no key in the browser"),
    ])
    # The public host is live, so the card carries the address a reviewer can actually open.
    _pill(sc, "dashboard", A + 1088 - 18, y5 + 25, "[LIVE]", anchor="end")
    sc.items.append(Text(A + 1088 - 18, y5 + 47, DASHBOARD_URL, "lbl", "end", box="dashboard"))
    sc.items.append(Text(A + 1088 - 18, y5 + 65, "public, no sign-in required", "lbl", "end", box="dashboard"))
    _edge(sc, ("M", A + 1088, y5 + 38), ("L", 1162, y5 + 38), ("L", 1162, y2 + 90), ("L", C + W, y2 + 90))
    return sc


def title(f: Facts) -> str:
    return ("BioRig end-to-end system architecture: off-chain mobile dMRV capture, the on-chain BioRigCoreV5 "
            f"deployment on {f.chain_name} with its addresses, the roadmap protocol tier, and the demo dashboard.")


def render_all(facts: Facts | None = None) -> tuple[str, bytes]:
    facts = facts or load_facts()
    scene = build_scene(facts)
    bad = overflows(scene)
    if bad:
        raise ValueError("layout overflow:\n  " + "\n  ".join(bad))
    svg = render_svg(scene, title=title(facts))
    return svg, render_png(scene, source_svg_sha256=hashlib.sha256(svg.encode()).hexdigest())


def svg_provenance(svg: bytes) -> str:
    """The sidecar's content: one sha256sum-format line naming the SVG the PNG was rendered alongside."""
    return f"{hashlib.sha256(svg).hexdigest()}  {SVG_OUT.name}\n"


def _rel(p: Path) -> str:
    return str(p.relative_to(ROOT)) if p.is_relative_to(ROOT) else str(p)


def png_problem(path: Path) -> str | None:
    """Why the PNG on disk is unusable, or None: it must exist, decode, and be the expected pixel size."""
    if not path.exists():
        return "missing"
    try:
        with Image.open(path) as im:
            im.load()
            size = im.size
    except Exception as e:  # noqa: BLE001 - any decode failure means the file is not a usable raster
        return f"does not decode ({e})"
    want = (GRID_W * PNG_SCALE, GRID_H * PNG_SCALE)
    return None if size == want else f"is {size[0]}x{size[1]} px, expected {want[0]}x{want[1]}"


def png_provenance_matches(path: Path, svg: bytes) -> bool:
    """The decodable PNG on disk carries tEXt chunks naming this generator and the sha256 of these SVG bytes."""
    with Image.open(path) as im:
        im.load()
        text = getattr(im, "text", {})
    return (text.get(PNG_SVG_SHA_KEY) == hashlib.sha256(svg).hexdigest()
            and text.get(PNG_GENERATOR_KEY) == GENERATOR)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--check", action="store_true", help="exit 1 if the SVG or its sha256 sidecar differs from a fresh render, or the PNG is unusable or lacks matching provenance")
    ap.add_argument("--chain-id", type=int, help="draw this recorded chain instead of deployment.json's default")
    args = ap.parse_args(argv)
    svg, png = render_all(load_facts(chain_id=args.chain_id))
    if args.check:
        # The PNG is not byte-compared: a rebuilt environment (same vendored fonts, different Pillow/FreeType
        # build) was measured to move 1,284 of 20,394,000 pixels (max channel delta 78), all on glyph edges, with
        # the SVG still byte-identical. Provenance replaces byte equality: the SVG must be a fresh render and the
        # sidecar must name it, and the PNG's tEXt chunks must carry that SVG's sha256 (a raster re-saved by
        # anything but this generator loses them); the raster's content stays anchored by the OCR read-back in
        # test_architecture.py.
        problems = []
        if not SVG_OUT.exists() or SVG_OUT.read_bytes() != svg.encode():
            problems.append(f"stale: {_rel(SVG_OUT)}")
        if not SVG_SHA_OUT.exists() or SVG_SHA_OUT.read_text() != svg_provenance(svg.encode()):
            problems.append(f"stale: {_rel(SVG_SHA_OUT)} does not record the sha256 of a fresh SVG render")
        bad_png = png_problem(PNG_OUT)
        if bad_png:
            problems.append(f"bad: {_rel(PNG_OUT)} {bad_png}")
        elif not png_provenance_matches(PNG_OUT, svg.encode()):
            problems.append(f"stale: {_rel(PNG_OUT)} provenance chunk missing or does not match the current SVG")
        for p in problems:
            print(p, file=sys.stderr)
        return 1 if problems else 0
    SVG_OUT.parent.mkdir(parents=True, exist_ok=True)
    SVG_OUT.write_bytes(svg.encode())
    SVG_SHA_OUT.write_text(svg_provenance(svg.encode()))
    PNG_OUT.write_bytes(png)
    print(f"wrote {_rel(SVG_OUT)} ({len(svg)} bytes), {_rel(SVG_SHA_OUT)} and {_rel(PNG_OUT)} ({len(png)} bytes)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
