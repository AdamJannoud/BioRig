"""The architecture diagram must print exactly the deployed addresses, and nothing it prints may drift.

Expected addresses are read here straight from dashboard/deployment.json and the DeployAll broadcast, not
through the generator's own loader, so a bug in the loader cannot make the test agree with itself. Three
things are checked against that record: the generator's scene, the SVG committed to the repo, and the pixels
of the committed PNG (each address is cropped out of the raster and read back with tesseract).

The registry address comes from the chain's entry in dashboard/chains.json. A broadcast only carries a CREATE2
for it where the script had to deploy it (Celo Sepolia); where the canonical registry already had code (Celo
mainnet) there is none, and a synthetic mainnet record below proves the diagram still draws.
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

from dashboard.config import chain_config
from tools import generate_architecture as G

ROOT = Path(__file__).resolve().parent.parent
ADDRESS_RE = re.compile(r"0x[0-9a-fA-F]{40}")


DEPLOYMENT_JSON = ROOT / "dashboard" / "deployment.json"
BROADCAST_DIR = ROOT / "broadcast" / "DeployAll.s.sol"
SEPOLIA, MAINNET = 11142220, 42220
ALFAJORES = 44787  # shut down and never recorded here: the stand-in for "no deployment recorded for this chain"


def recorded_chain(deployment_path: Path = DEPLOYMENT_JSON) -> tuple[int, dict]:
    """(default chain id, its entry) from the per-chain record."""
    deployment = json.loads(deployment_path.read_text())
    chain_id = int(deployment["default_chain_id"])
    return chain_id, deployment["deployments"][str(chain_id)]


def recorded_addresses(deployment_path: Path = DEPLOYMENT_JSON, broadcast_dir: Path = BROADCAST_DIR) -> dict[str, str]:
    chain_id, entry = recorded_chain(deployment_path)
    run = json.loads((broadcast_dir / str(chain_id) / "run-latest.json").read_text())
    by_name = {tx.get("contractName") or tx["transactionType"]: tx["contractAddress"].lower()
               for tx in run["transactions"] if tx["transactionType"] in ("CREATE", "CREATE2")}
    registry = chain_config(chain_id).erc6551_registry
    if "CREATE2" in by_name:  # the script deployed the registry itself; it must have landed where config says
        assert by_name["CREATE2"] == registry, (by_name["CREATE2"], registry)
    return {
        "proxy": entry["proxy_address"].lower(),
        "core_implementation": by_name["BioRigCoreV5"],
        "account_implementation": by_name["ERC6551Account"],
        "registry": registry,
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
    chain_id, _ = recorded_chain()
    run = json.loads((BROADCAST_DIR / str(chain_id) / "run-latest.json").read_text())
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
    facts = G.load_facts()
    assert G.render_svg(scene, title=G.title(facts)) == G.render_svg(G.build_scene(facts), title=G.title(facts))


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
    record = json.loads(DEPLOYMENT_JSON.read_text())
    record["deployments"][str(record["default_chain_id"])]["proxy_address"] = "0x" + "11" * 20
    path = tmp_path / "deployment.json"
    path.write_text(json.dumps(record))
    with pytest.raises(G.DeploymentMismatch, match="proxy"):
        G.load_facts(deployment_path=path)


# ---- a chain whose broadcast has no CREATE2 (the canonical registry was already there)

def _word(n: int) -> str:
    return f"{n:064x}"


@pytest.fixture
def mainnet_record(tmp_path) -> tuple[Path, Path]:
    """A synthetic Celo mainnet record: the Sepolia broadcast re-keyed to 42220, minus its CREATE2, with the
    proxy's initialize calldata carrying chain id 42220. Lives in tmp_path only; nothing is committed."""
    run = json.loads((BROADCAST_DIR / str(SEPOLIA) / "run-latest.json").read_text())
    run["chain"] = MAINNET
    run["transactions"] = [tx for tx in run["transactions"] if tx["transactionType"] != "CREATE2"]
    proxy_tx = next(tx for tx in run["transactions"] if tx.get("contractName") == "ERC1967Proxy"
                    and tx["transactionType"] == "CREATE")
    init = proxy_tx["arguments"][1]
    start = 2 + 8 + 64 * 3  # 0x, selector, then admin / registry / implementation words
    assert int(init[start:start + 64], 16) == SEPOLIA
    proxy_tx["arguments"][1] = init[:start] + _word(MAINNET) + init[start + 64:]
    broadcast_dir = tmp_path / "broadcast"
    (broadcast_dir / str(MAINNET)).mkdir(parents=True)
    (broadcast_dir / str(MAINNET) / "run-latest.json").write_text(json.dumps(run))
    _, entry = recorded_chain()
    deployment = tmp_path / "deployment.json"
    deployment.write_text(json.dumps({"default_chain_id": MAINNET, "deployments": {str(MAINNET): entry}}))
    return deployment, broadcast_dir


def test_chain_without_create2_takes_the_registry_from_chain_config(mainnet_record):
    deployment, broadcast_dir = mainnet_record
    run = json.loads((broadcast_dir / str(MAINNET) / "run-latest.json").read_text())
    assert [tx for tx in run["transactions"] if tx["transactionType"] == "CREATE2"] == []
    expected = recorded_addresses(deployment, broadcast_dir)
    assert expected["registry"] == chain_config(MAINNET).erc6551_registry == \
        "0x000000006551c19487814612e58fe06813775758"

    facts = G.load_facts(deployment, broadcast_dir)
    assert (facts.chain_id, facts.chain_name, facts.registry) == (MAINNET, "Celo mainnet", expected["registry"])
    scene = G.build_scene(facts)
    assert address_mismatches(scene.addresses(), expected) == []
    texts = [t.text for t in scene.texts()]
    assert any(t.startswith("Celo mainnet · chain id 42220 · deployed") for t in texts)
    assert "Celo Sepolia" not in " ".join(texts) and "11142220" not in " ".join(texts)
    assert "deployment on Celo mainnet" in G.title(facts)


def test_generator_refuses_a_registry_the_chain_config_does_not_name(mainnet_record):
    deployment, broadcast_dir = mainnet_record
    path = broadcast_dir / str(MAINNET) / "run-latest.json"
    run = json.loads(path.read_text())
    proxy_tx = next(tx for tx in run["transactions"] if tx.get("contractName") == "ERC1967Proxy"
                    and tx["transactionType"] == "CREATE")
    init = proxy_tx["arguments"][1]
    start = 2 + 8 + 64  # the registry word
    proxy_tx["arguments"][1] = init[:start] + "00" * 12 + "ab" * 20 + init[start + 64:]
    path.write_text(json.dumps(run))
    with pytest.raises(G.DeploymentMismatch, match="chains.json has 0x000000006551c19487814612e58fe06813775758"):
        G.load_facts(deployment, broadcast_dir)


def test_generator_refuses_a_chain_with_no_recorded_deployment():
    # Mainnet used to be the unrecorded case here; it is recorded as of 1 October 2026, so this pins the refusal with a
    # chain that has no entry at all.
    with pytest.raises(G.DeploymentMismatch, match=f"no deployment recorded for chain {ALFAJORES}"):
        G.load_facts(chain_id=ALFAJORES)
