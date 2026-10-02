"""The brand kit is a fresh render of tools/generate_brand.py, credited to Adam Jannoud, and the 16 px favicon
keeps its ring open instead of smearing into a blob."""
from pathlib import Path

from PIL import Image

from tools import generate_brand as gb

ROOT = Path(__file__).resolve().parent.parent


def _rgb(hex_: str) -> tuple[int, int, int]:
    return tuple(int(hex_[i:i + 2], 16) for i in (1, 3, 5))


def _near(px, hex_, tol=60) -> bool:
    return sum(abs(a - b) for a, b in zip(px[:3], _rgb(hex_))) <= tol


def test_outputs_on_disk_are_fresh():
    assert gb.stale(gb.outputs()) == []


def test_arc_centre_reproduces_the_plan_geometry():
    # The plan draws the right ring as "M49.4 27 A17 17 0 1 1 49.4 55": a large clockwise arc centred at x ~ 59.
    cx, cy = gb.arc_center(49.4, 27, 49.4, 55, 17)
    assert abs(cx - 59.04) < 0.01 and cy == 41


def test_every_asset_carries_the_credit_and_nothing_else():
    for path in sorted((ROOT / "assets" / "brand").rglob("*.svg")) + sorted(gb.DASHBOARD_BRAND_DIR.glob("*.svg")):
        text = path.read_text()
        assert "Adam Jannoud (AdamJannoud)" in text, path
    for path in sorted((ROOT / "assets" / "brand").glob("*.png")) + [gb.DASHBOARD_BRAND_DIR / "favicon.png"]:
        with Image.open(path) as im:
            assert im.text["Author"] == "Adam Jannoud (AdamJannoud)", path
            assert set(im.text) == {"Author", "Copyright", "bio-rig-generator"}, path


def test_favicon_ring_stays_open_at_16px():
    with Image.open(gb.BRAND_DIR / "favicon-16.png") as im:
        im = im.convert("RGBA")
        assert im.size == (16, 16)
        # centre: the gold node; one ring-gap pixel out: forest; the ring itself: gold; the tile corner: clear.
        assert _near(im.getpixel((8, 8)), gb.GOLD, 120)
        assert _near(im.getpixel((8, 6)), gb.FOREST, 120) or _near(im.getpixel((6, 8)), gb.FOREST, 120)
        assert _near(im.getpixel((8, 4)), gb.GOLD, 120)
        assert im.getpixel((0, 0))[3] < 128


def test_lockup_is_forest_with_a_white_wordmark():
    with Image.open(gb.BRAND_DIR / "biorig-lockup.png") as im:
        im = im.convert("RGB")
        w, h = im.size
        assert _near(im.getpixel((w - 12, h // 2)), gb.FOREST)
        colours = im.crop((w // 2, 0, w, h)).getcolors(maxcolors=1 << 20)
        assert any(_near(c, gb.WHITE, 15) for _, c in colours)
        assert any(_near(c, gb.GOLD_DEEP, 30) for _, c in colours)
