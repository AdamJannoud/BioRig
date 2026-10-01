"""The dashboard's committed ABIs and the canonical registry init code must be what the source builds, and the gate
that says so must be able to fail.

Every negative control runs against copies: a minimal tree in tmp_path (the three built artefacts, the three
committed ABIs and the registry .bin) for the per-entry checks, and a full copy of the checkout for the one
control that matters most, which edits a contract without rebuilding and shows the gate's own `forge build` is what
catches it. Each copy is shown to pass before it is broken, so a red result cannot be a broken copy.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from tools import check_artefacts as A

ROOT = Path(__file__).resolve().parent.parent
CLI = ROOT / "tools" / "check_artefacts.py"
CORE = A.ABI_DIR / "BioRigCoreV5.json"
PROBE = "auditProbeAddedAfterTheBuild"


def cli(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(CLI), *args], capture_output=True, text=True, timeout=600)


def stale_lines(root: Path, specs=None) -> list[str]:
    return A.check_abis(root, specs) + A.check_registry_bin(root)


@pytest.fixture
def tree(tmp_path) -> Path:
    """The gate's inputs copied into tmp_path: build artefacts, committed ABIs, registry init code."""
    for contract, _ in A.ABI_SPECS:
        for rel in (A.OUT_DIR / f"{contract}.sol" / f"{contract}.json", A.ABI_DIR / f"{contract}.json"):
            (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(ROOT / rel, tmp_path / rel)
    (tmp_path / A.REGISTRY_BIN).parent.mkdir(parents=True)
    shutil.copyfile(ROOT / A.REGISTRY_BIN, tmp_path / A.REGISTRY_BIN)
    assert stale_lines(tmp_path) == []  # the copies pass before they are broken
    assert A.main(["--root", str(tmp_path), "--no-build"]) == 0
    return tmp_path


def edit_core(root: Path, fn) -> list[str]:
    path = root / CORE
    abi = json.loads(path.read_text())
    path.write_bytes(A.render_abi(fn(abi)))
    assert A.main(["--root", str(root), "--no-build"]) == 1
    return A.check_abis(root)


# ---- the committed artefacts are fresh

def test_constants_match_deploy_common():
    """The gate's CREATE2 inputs are DeployCommon's, so the offline check is the same require it makes."""
    sol = (ROOT / "script" / "DeployCommon.sol").read_text()
    for name in ("NICKS_FACTORY", "CANONICAL_REGISTRY", "CANONICAL_SALT"):
        assert re.search(rf"\b{name} = {getattr(A, name)};", sol), name
    assert f'CANONICAL_INIT_CODE_PATH = "{A.REGISTRY_BIN.as_posix()}"' in sol


def test_registry_bin_derives_the_canonical_registry():
    assert A.check_registry_bin(ROOT) == []
    assert A.create2_address(A.NICKS_FACTORY, A.CANONICAL_SALT, (ROOT / A.REGISTRY_BIN).read_bytes()) == \
        A.CANONICAL_REGISTRY


def test_pristine_checkout_passes_the_cli():
    """Control 1: the real CLI, internal forge build included, on this checkout."""
    run = cli()
    assert (run.returncode, run.stderr) == (0, "")


def test_pruned_specs_select_exactly_the_named_functions():
    for contract, names in A.ABI_SPECS:
        committed = json.loads((ROOT / A.ABI_DIR / f"{contract}.json").read_text())
        if names is None:
            assert committed == A.built_abi(ROOT, contract)
        else:
            assert [(e["type"], e["name"]) for e in committed] == [("function", n) for n in names]


# ---- the checks above can fail

def test_deleted_entry_is_caught(tree):
    """Control 2."""
    problems = edit_core(tree, lambda abi: [e for e in abi if e.get("name") != "mintTree"])
    assert problems == [f"stale: {CORE}: function mintTree(address,bytes32,uint96,uint96) is missing from the "
                        f"committed file (the build adds it)"]


def test_stale_signature_is_caught(tree):
    """Control 3: mintTree's initialDBH committed as uint256 while the source says uint96."""
    def stale(abi):
        mint = next(e for e in abi if e.get("name") == "mintTree")
        dbh = next(i for i in mint["inputs"] if i["name"] == "initialDBH")
        assert dbh["type"] == "uint96"
        dbh["type"] = dbh["internalType"] = "uint256"
        return abi
    problems = edit_core(tree, stale)
    assert problems == [f"stale: {CORE}: function mintTree(address,bytes32,uint96,uint96) changed "
                        f"(committed function mintTree(address,bytes32,uint256,uint96))"]


def test_invented_entry_is_caught(tree):
    """Control 4."""
    invented = {"type": "function", "name": "drainTreasury", "inputs": [], "outputs": [],
                "stateMutability": "nonpayable"}
    problems = edit_core(tree, lambda abi: abi + [invented])
    assert problems == [f"stale: {CORE}: function drainTreasury() is committed but the source no longer exposes it"]


def test_reordered_entries_are_caught(tree):
    """Control 5: same entries, two swapped."""
    def swap(abi):
        abi[1], abi[2] = abi[2], abi[1]
        return abi
    built = A.built_abi(tree, "BioRigCoreV5")
    problems = edit_core(tree, swap)
    assert len(problems) == 1 and "entry order differs from the build" in problems[0], problems
    assert A.signature(built[1]) in problems[0] and A.signature(built[2]) in problems[0]


def test_pruned_name_the_source_lost_is_caught(tree, monkeypatch):
    """Control 6: the dashboard calls a function on ERC6551Account that the built ABI does not have."""
    specs = (("ERC6551Account", ("supportsInterface", "token", "executeCall")),)
    monkeypatch.setattr(A, "ABI_SPECS", specs)
    assert A.check_abis(tree) == ["stale: dashboard/abi/ERC6551Account.json: the dashboard calls function "
                                  "executeCall, the source no longer exposes it"]
    assert A.main(["--root", str(tree), "--no-build"]) == 1
    before = (tree / A.ABI_DIR / "ERC6551Account.json").read_bytes()
    assert A.main(["--root", str(tree), "--no-build", "--write"]) == 1  # refuses rather than drop the call
    assert (tree / A.ABI_DIR / "ERC6551Account.json").read_bytes() == before


def test_pruned_file_missing_a_named_entry_is_caught(tree):
    path = tree / A.ABI_DIR / "ERC6551Registry.json"
    path.write_bytes(A.render_abi([]))
    assert A.check_abis(tree) == ["stale: dashboard/abi/ERC6551Registry.json: function account(address,bytes32,"
                                  "uint256,address,uint256) is missing from the committed file (the dashboard "
                                  "calls it)"]


def test_flipped_registry_byte_is_caught(tree):
    """Control 7."""
    path = tree / A.REGISTRY_BIN
    code = bytearray(path.read_bytes())
    code[len(code) // 2] ^= 0x01
    path.write_bytes(bytes(code))
    problems = A.check_registry_bin(tree)
    assert len(problems) == 1 and "not the canonical registry" in problems[0], problems
    assert A.main(["--root", str(tree), "--no-build"]) == 1


def test_write_on_a_pristine_tree_is_byte_identical(tree):
    """Control 8: --write regenerates exactly the bytes committed at HEAD."""
    for contract, _ in A.ABI_SPECS:
        (tree / A.ABI_DIR / f"{contract}.json").unlink()
    assert A.main(["--root", str(tree), "--no-build", "--write"]) == 0
    for contract, _ in A.ABI_SPECS:
        rel = (A.ABI_DIR / f"{contract}.json").as_posix()
        head = subprocess.run(["git", "show", f"HEAD:{rel}"], cwd=ROOT, capture_output=True, check=True).stdout
        assert (tree / rel).read_bytes() == head, rel


def test_layout_drift_is_caught(tree):
    path = tree / CORE
    path.write_text(json.dumps(json.loads(path.read_text()), indent=2))
    assert A.check_abis(tree) == [f"stale: {CORE} holds the right entries but not in the generator's layout"]


def test_missing_build_artefact_is_a_setup_failure(tree):
    shutil.rmtree(tree / A.OUT_DIR)
    assert A.main(["--root", str(tree), "--no-build"]) == 2


def test_missing_forge_or_root_is_a_setup_failure(tree, monkeypatch):
    assert A.main(["--root", str(tree / "nowhere"), "--no-build"]) == 2
    monkeypatch.setattr(A.shutil, "which", lambda _: None)
    assert A.main(["--root", str(tree)]) == 2


def test_failed_build_is_a_setup_failure(tree):
    (tree / "src").mkdir()
    (tree / "src" / "Broken.sol").write_text("pragma solidity 0.8.28;\ncontract Broken { function f( }\n")
    (tree / "foundry.toml").write_text((ROOT / "foundry.toml").read_text())
    assert A.main(["--root", str(tree)]) == 2


# ---- control 9: the internal build is what closes the hole

@pytest.fixture(scope="module")
def full_copy(tmp_path_factory) -> Path:
    """Everything but .git and .venv, so forge build in the copy succeeds; asserted pristine-clean first."""
    dst = tmp_path_factory.mktemp("checkout") / "bio-rig"
    shutil.copytree(ROOT, dst, symlinks=True,
                    ignore=shutil.ignore_patterns(".git", ".venv", "__pycache__", ".pytest_cache"))
    run = cli("--root", str(dst))
    assert (run.returncode, run.stderr) == (0, ""), run.stderr
    return dst


def test_internal_build_catches_an_unbuilt_source_change(full_copy):
    src = full_copy / "src" / "BioRigCoreV5.sol"
    text = src.read_text()
    assert text.rstrip().endswith("}") and PROBE not in text
    src.write_text(text.rstrip()[:-1]
                   + f"\n    function {PROBE}() external pure returns (uint256) {{\n        return 1;\n    }}\n}}\n")

    # out/ still holds the pre-edit build: skipping the build, the gate sees nothing wrong. This is the hole.
    skipped = cli("--root", str(full_copy), "--no-build")
    assert (skipped.returncode, skipped.stderr) == (0, ""), skipped.stderr

    # The default run builds first, and the new function surfaces as an entry the committed ABI lacks.
    gated = cli("--root", str(full_copy))
    assert gated.returncode == 1, gated.stderr
    assert gated.stderr.splitlines() == [f"stale: {CORE}: function {PROBE}() is missing from the committed file "
                                         f"(the build adds it)"]

    # That build refreshed out/, so now even --no-build sees it: the build, not anything else, made the difference.
    after = cli("--root", str(full_copy), "--no-build")
    assert after.returncode == 1 and PROBE in after.stderr

    # And the one-command fix: --write picks the function up and the gate goes green again.
    assert cli("--root", str(full_copy), "--write").returncode == 0
    assert PROBE in (full_copy / CORE).read_text()
    final = cli("--root", str(full_copy))
    assert (final.returncode, final.stderr) == (0, ""), final.stderr
