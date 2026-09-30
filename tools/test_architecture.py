"""The architecture diagram must print exactly the deployed addresses, and nothing it prints may drift.

Expected addresses are read here straight from dashboard/deployment.json and the DeployAll broadcast, not
through the generator's own loader, so a bug in the loader cannot make the test agree with itself. Three
things are checked against that record: the generator's scene, the SVG committed to the repo, and the pixels
of the committed PNG (each address is cropped out of the raster and read back with tesseract).
"""
from __future__ import annotations

import dataclasses
import io
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest
from PIL import Image

from tools import generate_architecture as G

ROOT = Path(__file__).resolve().parent.parent
ADDRESS_RE = re.compile(r"0x[0-9a-fA-F]{40}")


def recorded_addresses(deployment_path: Path = ROOT / "dashboard" / "deployment.json") -> dict[str, str]:
    deployment = json.loads(deployment_path.read_text())
    run = json.loads((ROOT / "broadcast" / "DeployAll.s.sol" / str(deployment["chain_id"])
                      / "run-latest.json").read_text())
    by_name = {tx.get("contractName") or tx["transactionType"]: tx["contractAddress"].lower()
               for tx in run["transactions"] if tx["transactionType"] in ("CREATE", "CREATE2")}
    return {
        "proxy": deployment["proxy_address"].lower(),
        "core_implementation": by_name["BioRigCoreV5"],
        "account_implementation": by_name["ERC6551Account"],
        "registry": by_name["CREATE2"],  # the canonical registry, deployed by the script through CREATE2
    }


def address_mismatches(printed: list[str], expected: dict[str, str]) -> list[str]:
    """Every printed address must be a recorded one, and every recorded one must be printed."""
    printed_l = [a.lower() for a in printed]
    wanted = set(expected.values())
    problems = [f"printed but not in the deployment record: {a}" for a in printed_l if a not in wanted]
    problems += [f"{name} {a} is not printed" for name, a in expected.items() if a not in printed_l]
    return problems


@pytest.fixture(scope="module")
def expected() -> dict[str, str]:
    return recorded_addresses()


@pytest.fixture(scope="module")
def scene() -> G.Scene:
    return G.build_scene(G.load_facts())


def test_deployment_record_agrees_with_broadcast(expected):
    run = json.loads((ROOT / "broadcast/DeployAll.s.sol/11142220/run-latest.json").read_text())
    proxies = [tx["contractAddress"].lower() for tx in run["transactions"]
               if tx["transactionType"] == "CREATE" and tx.get("contractName") == "ERC1967Proxy"]
    assert proxies == [expected["proxy"]]
    assert len(set(expected.values())) == 4


def test_scene_prints_exactly_the_recorded_addresses(scene, expected):
    assert address_mismatches(scene.addresses(), expected) == []
    assert len(scene.addresses()) == 4


def test_each_address_is_on_the_right_box(scene, expected):
    on_box = {t.box: t.text for t in scene.texts() if ADDRESS_RE.fullmatch(t.text)}
    assert on_box["proxy"] == expected["proxy"]
    assert on_box["core"] == expected["core_implementation"]
    registry_box = [t.text for t in scene.texts() if t.box == "registry" and ADDRESS_RE.fullmatch(t.text)]
    assert registry_box == [expected["registry"], expected["account_implementation"]]


def test_committed_svg_prints_exactly_the_recorded_addresses(expected):
    svg = G.SVG_OUT.read_text()
    assert address_mismatches(ADDRESS_RE.findall(svg), expected) == []


@pytest.mark.skipif(shutil.which("tesseract") is None, reason="tesseract not installed (apt-get install tesseract-ocr)")
def test_committed_png_pixels_read_back_as_the_recorded_addresses(scene, expected):
    im = Image.open(G.PNG_OUT).convert("L")
    assert im.size == (G.GRID_W * G.PNG_SCALE, G.GRID_H * G.PNG_SCALE)
    k = G.PNG_SCALE
    read = []
    for t in scene.texts():
        if not ADDRESS_RE.search(t.text):
            continue
        w = G.text_width(t.text, t.style)
        crop = im.crop((int((t.x - 3) * k), int((t.y - 12) * k), int((t.x + w + 3) * k), int((t.y + 4) * k)))
        buf = io.BytesIO()
        crop.save(buf, "PNG")
        out = subprocess.run(
            ["tesseract", "stdin", "stdout", "--psm", "7", "-c", "tessedit_char_whitelist=0123456789abcdefABCDEFx"],
            input=buf.getvalue(), capture_output=True, check=True).stdout.decode().strip()
        read.append(out)
    assert address_mismatches(read, expected) == [], read


def test_committed_outputs_are_a_fresh_render():
    """Byte-for-byte: the PNG and SVG on disk are what the generator produces now from the current record."""
    assert G.main(["--check"]) == 0


def test_svg_render_is_deterministic(scene):
    assert G.render_svg(scene, title=G.TITLE) == G.render_svg(G.build_scene(G.load_facts()), title=G.TITLE)


def test_layout_fits(scene):
    assert G.overflows(scene) == []


def test_roadmap_boxes_are_badged(scene):
    for bid in ("accrual", "buffer", "rails", "demand"):
        assert "[ROADMAP]" in [t.text for t in scene.texts() if t.box == bid], bid
    assert "address stored, no routing" in [t.text for t in scene.texts() if t.box == "buffer"]


def test_dashboard_is_marked_pending_and_prints_no_url(scene):
    dash = [t.text for t in scene.texts() if t.box == "dashboard"]
    assert "[IN PROGRESS]" in dash
    everything = " ".join(t.text for t in scene.texts())
    for banned in ("streamlit.app", "http", "://", "www.", "hf.space"):
        assert banned not in everything
    svg_text = " ".join(re.findall(r"<text[^>]*>([^<]*)</text>", G.SVG_OUT.read_text()))
    assert "streamlit.app" not in svg_text and "://" not in svg_text


def test_no_v4_name_survives(scene):
    everything = " ".join(t.text for t in scene.texts())
    assert "V4" not in everything
    assert "BioRigCoreV5" in everything


# ---- the checks above can fail

def test_corrupted_address_is_caught(scene, expected):
    bad = dict(expected, proxy=expected["proxy"][:-1] + ("0" if expected["proxy"][-1] != "0" else "1"))
    assert address_mismatches(scene.addresses(), bad) != []
    facts = G.load_facts()
    drifted = G.build_scene(dataclasses.replace(facts, registry="0x" + "ab" * 20))
    assert address_mismatches(drifted.addresses(), expected) != []


def test_generator_refuses_a_record_that_disagrees_with_the_broadcast(tmp_path):
    record = json.loads((ROOT / "dashboard" / "deployment.json").read_text())
    record["proxy_address"] = "0x" + "11" * 20
    path = tmp_path / "deployment.json"
    path.write_text(json.dumps(record))
    with pytest.raises(G.DeploymentMismatch, match="proxy"):
        G.load_facts(deployment_path=path)
