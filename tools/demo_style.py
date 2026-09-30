"""Palette, fonts, caption band and shared drawing helpers for the explainer video.

Every scene draws on a 1920x1080 canvas in this coordinate space; --draft downsizes the finished frame.
Colours mirror the dashboard's dark tokens so the video and the live demo read as one piece.
"""
from __future__ import annotations

import math
from functools import lru_cache
from pathlib import Path

import matplotlib
from PIL import Image, ImageDraw, ImageFont

W, H = 1920, 1080

BG = (14, 17, 22)
SURFACE = (23, 27, 34)
RULE = (38, 44, 54)
FIELD = (32, 38, 48)
TEXT = (230, 233, 239)
MUTED = (139, 149, 163)
ACCENT = (47, 109, 246)
CELO = (252, 255, 82)  # Celo prosperity yellow, used only for the Celo badge
OK = (74, 222, 128)
OK_BG = (16, 51, 31)
WARN = (251, 191, 36)
WARN_BG = (58, 42, 8)
BAD = (248, 113, 113)
GREEN = (52, 168, 83)

_FONT_DIR = Path(matplotlib.get_data_path()) / "fonts" / "ttf"


@lru_cache(maxsize=None)
def font(size: int, bold: bool = False, mono: bool = False) -> ImageFont.FreeTypeFont:
    name = ("DejaVuSansMono" if mono else "DejaVuSans") + ("-Bold" if bold else "") + ".ttf"
    return ImageFont.truetype(str(_FONT_DIR / name), size)


# --------------------------------------------------------------------------- timing helpers

def clamp01(x: float) -> float:
    return 0.0 if x < 0 else 1.0 if x > 1 else x


def ease(x: float) -> float:
    """Smoothstep-style ease in/out on [0, 1]."""
    x = clamp01(x)
    return x * x * (3 - 2 * x)


def ramp(t: float, start: float, dur: float = 0.6) -> float:
    """0 before start, eased 0->1 over dur seconds, then 1."""
    return ease((t - start) / dur) if dur > 0 else float(t >= start)


def window(t: float, start: float, end: float, fade: float = 0.5) -> float:
    """Opacity for an element visible between start and end, fading in and out."""
    return min(ramp(t, start, fade), 1.0 - ramp(t, end - fade, fade))


def mix(c1, c2, a: float):
    return tuple(int(round(x + (y - x) * a)) for x, y in zip(c1, c2))


def fade(color, a: float, bg=BG):
    """Colour blended toward the background: cheap opacity without an alpha layer."""
    return mix(bg, color, clamp01(a))


# --------------------------------------------------------------------------- drawing

def new_canvas() -> tuple[Image.Image, ImageDraw.ImageDraw]:
    img = Image.new("RGB", (W, H), BG)
    return img, ImageDraw.Draw(img)


def text(d: ImageDraw.ImageDraw, xy, s: str, size: int, color=TEXT, *, bold=False, mono=False,
         anchor="la", a: float = 1.0, bg=BG) -> None:
    if a <= 0.01:
        return
    d.text(xy, s, font=font(size, bold, mono), fill=fade(color, a, bg), anchor=anchor)


def box(d, xy, *, fill=SURFACE, outline=RULE, width=2, radius=16, a: float = 1.0) -> None:
    if a <= 0.01:
        return
    d.rounded_rectangle(xy, radius=radius, fill=fade(fill, a), outline=fade(outline, a), width=width)


def arrow(d, p0, p1, progress: float, color=ACCENT, width=5, head=18) -> None:
    """Line from p0 toward p1, drawn to `progress` of its length, with a head once complete enough."""
    progress = clamp01(progress)
    if progress <= 0.01:
        return
    x0, y0 = p0
    x1, y1 = p1
    xe, ye = x0 + (x1 - x0) * progress, y0 + (y1 - y0) * progress
    d.line([(x0, y0), (xe, ye)], fill=color, width=width)
    if progress > 0.2:
        ang = math.atan2(y1 - y0, x1 - x0)
        pts = [(xe, ye),
               (xe - head * math.cos(ang - 0.45), ye - head * math.sin(ang - 0.45)),
               (xe - head * math.cos(ang + 0.45), ye - head * math.sin(ang + 0.45))]
        d.polygon(pts, fill=color)


def pill(d, xy, label: str, *, fg=OK, bg=OK_BG, size=24, a: float = 1.0) -> None:
    x, y = xy
    f = font(size, bold=True)
    w = d.textlength(label, font=f)
    box(d, (x, y, x + w + 36, y + size + 22), fill=bg, outline=bg, radius=(size + 22) // 2, a=a)
    text(d, (x + 18, y + 10), label, size, fg, bold=True, a=a)


def hexagon(d, center, r, *, fill=None, outline=ACCENT, width=3, a: float = 1.0) -> None:
    cx, cy = center
    pts = [(cx + r * math.cos(math.radians(60 * k + 30)), cy + r * math.sin(math.radians(60 * k + 30)))
           for k in range(6)]
    d.polygon(pts, fill=fade(fill, a) if fill else None, outline=fade(outline, a), width=width)


def wrap(s: str, size: int, max_width: int, *, bold=False, mono=False) -> list[str]:
    f = font(size, bold, mono)
    words, lines, cur = s.split(), [], ""
    for w in words:
        trial = f"{cur} {w}".strip()
        if f.getlength(trial) <= max_width or not cur:
            cur = trial
        else:
            lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines


# --------------------------------------------------------------------------- chrome: header, captions, progress

CAPTION_TOP = H - 170


def header(d, segment_no: int, title: str, time_label: str) -> None:
    text(d, (80, 60), f"{segment_no} / 4", 26, MUTED, mono=True)
    text(d, (180, 56), title.upper(), 30, TEXT, bold=True)
    text(d, (W - 80, 60), time_label, 26, MUTED, mono=True, anchor="ra")
    d.line([(80, 112), (W - 80, 112)], fill=RULE, width=2)


def caption_band(d, captions: list[tuple[float, float, str]], t: float) -> None:
    """Burned-in captions: a band above the progress bar, one cue at a time, faded at its edges."""
    d.rectangle((0, CAPTION_TOP, W, H - 16), fill=SURFACE)
    d.line([(0, CAPTION_TOP), (W, CAPTION_TOP)], fill=RULE, width=2)
    for start, end, cue in captions:
        if start <= t < end:
            a = window(t, start, end, 0.35)
            lines = wrap(cue, 38, W - 320)
            y0 = CAPTION_TOP + (H - 16 - CAPTION_TOP) // 2 - len(lines) * 25
            for i, line in enumerate(lines):
                text(d, (W // 2, y0 + i * 50), line, 38, TEXT, anchor="ma", a=a, bg=SURFACE)
            break


def progress(d, global_t: float, total: float, boundaries: list[float]) -> None:
    d.rectangle((0, H - 16, W, H), fill=RULE)
    d.rectangle((0, H - 16, int(W * clamp01(global_t / total)), H), fill=ACCENT)
    for b in boundaries:
        x = int(W * b / total)
        d.rectangle((x - 2, H - 16, x + 2, H), fill=BG)


def mmss(seconds: float) -> str:
    s = int(seconds)
    return f"{s // 60:02d}:{s % 60:02d}"
