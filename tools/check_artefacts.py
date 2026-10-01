"""Gate the dashboard's committed ABIs and the canonical registry init code against the source they derive from.

    .venv/bin/python tools/check_artefacts.py             # forge build, then exit 1 if a committed artefact is stale
    .venv/bin/python tools/check_artefacts.py --write     # forge build, then regenerate dashboard/abi/*.json
    .venv/bin/python tools/check_artefacts.py --no-build  # skip forge build: only when out/ is known fresh

Artefacts checked:
  dashboard/abi/<Contract>.json   loaded at runtime by dashboard/chain.py:load_abi(). Each must equal, entry for
                                  entry and in order, the `.abi` forge writes to out/<Contract>.sol/<Contract>.json,
                                  pruned to the functions ABI_SPECS names (None keeps the whole ABI). The file is
                                  json.dumps(abi, indent=1) with no trailing newline, which is how the copies were
                                  first committed, so --write on a pristine tree changes no byte.
  script/data/ERC6551Registry.canonical.bin
                                  the EIP-6551 registry creation code DeployCommon._deployCanonicalRegistry() sends
                                  through Nick's factory. Its CREATE2 address under CANONICAL_SALT must be
                                  CANONICAL_REGISTRY: the same require DeployCommon makes at deploy time, evaluated
                                  offline so a bad file fails here instead of mid-deploy.

The check runs `forge build` first. Without it out/ can trail src/, and an edited contract whose ABI was never
regenerated passes against the stale build it was compared with: exactly the hole this gate exists to close.
No RPC call is made anywhere.

Exit status: 0 clean, 1 a committed artefact is stale (or --write could not produce one), 2 setup failure (no such
root, forge missing, the build failing, or a build artefact absent).
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

from eth_utils import keccak, to_checksum_address

ROOT = Path(__file__).resolve().parent.parent

# (contract, functions the dashboard calls); None means the dashboard gets the whole ABI. Pruning keeps
# `type == "function"` entries with these names, in the order the build emits them.
ABI_SPECS: tuple[tuple[str, tuple[str, ...] | None], ...] = (
    ("BioRigCoreV5", None),
    ("ERC6551Account", ("supportsInterface", "token")),
    ("ERC6551Registry", ("account",)),
)
ABI_DIR = Path("dashboard") / "abi"  # relative to --root
OUT_DIR = Path("out")
REGISTRY_BIN = Path("script") / "data" / "ERC6551Registry.canonical.bin"

# Copied from script/DeployCommon.sol; test_artefacts.py asserts the two still agree.
NICKS_FACTORY = "0x4e59b44847b379578588920cA78FbF26c0B4956C"
CANONICAL_REGISTRY = "0x000000006551c19487814612e58FE06813775758"
CANONICAL_SALT = "0x0000000000000000000000000000000000000000fd8eb4e1dca713016c518e31"


class SetupError(RuntimeError):
    """The gate cannot run at all: no forge, a failed build, or a build artefact missing."""


# --------------------------------------------------------------------------- ABIs

def build(root: Path) -> None:
    forge = shutil.which("forge")
    if forge is None:
        raise SetupError("forge not on PATH (install foundry, or pass --no-build if out/ is known fresh)")
    run = subprocess.run([forge, "build"], cwd=root, capture_output=True, text=True)
    if run.returncode != 0:
        tail = "\n".join((run.stdout + run.stderr).strip().splitlines()[-20:])
        raise SetupError(f"forge build failed in {root} (exit {run.returncode}):\n{tail}")


def built_abi(root: Path, contract: str) -> list[dict]:
    path = root / OUT_DIR / f"{contract}.sol" / f"{contract}.json"
    if not path.exists():
        raise SetupError(f"{path} missing; run forge build (or drop --no-build)")
    return json.loads(path.read_text())["abi"]


def expected_abi(built: list[dict], names: tuple[str, ...] | None) -> tuple[list[dict], list[str]]:
    """(the ABI the dashboard file should hold, named functions the build no longer exposes)."""
    if names is None:
        return built, []
    kept = [e for e in built if e["type"] == "function" and e["name"] in names]
    present = {e["name"] for e in kept}
    return kept, [n for n in names if n not in present]


def render_abi(abi: list[dict]) -> bytes:
    return json.dumps(abi, indent=1).encode()


def signature(e: dict) -> str:
    args = ",".join(_type(i) for i in e.get("inputs", []))
    return f"{e['type']} {e.get('name', '')}({args})".replace(" (", "(")


def _type(param: dict) -> str:
    t = param["type"]
    if t.startswith("tuple"):
        return "(" + ",".join(_type(c) for c in param.get("components", [])) + ")" + t[len("tuple"):]
    return t


def _keyed(abi: list[dict]) -> list[tuple[tuple, dict]]:
    """Key each entry by (type, name, n-th occurrence) so an overload or a changed signature still pairs up with
    its counterpart instead of reading as one removal plus one addition."""
    seen: dict[tuple, int] = {}
    out = []
    for e in abi:
        base = (e["type"], e.get("name", ""))
        seen[base] = seen.get(base, 0) + 1
        out.append(((*base, seen[base]), e))
    return out


def abi_problems(label: str, expected: list[dict], committed: list[dict], pruned: bool) -> list[str]:
    """One `stale:` line per entry that differs between the committed ABI and the one derived from the build."""
    want, have = dict(_keyed(expected)), dict(_keyed(committed))
    problems = []
    for k, e in have.items():
        if k not in want:
            problems.append(f"stale: {label}: {signature(e)} is committed but the source no longer exposes it")
    for k, e in want.items():
        if k in have and have[k] != e:
            problems.append(f"stale: {label}: {signature(e)} changed (committed {signature(have[k])}"
                            + (")" if signature(have[k]) != signature(e) else ", outputs/mutability/names differ)"))
    for k, e in want.items():
        if k not in have:
            what = "the dashboard calls it" if pruned else "the build adds it"
            problems.append(f"stale: {label}: {signature(e)} is missing from the committed file ({what})")
    order_want = [k for k, _ in _keyed(expected) if k in have]
    order_have = [k for k, _ in _keyed(committed) if k in want]
    if order_want != order_have:
        moved = [signature(want[k]) for k, j in zip(order_want, order_have) if k != j]
        problems.append(f"stale: {label}: entry order differs from the build ({', '.join(moved)} out of place)")
    return problems


def check_abis(root: Path, specs=None) -> list[str]:
    problems = []
    for contract, names in ABI_SPECS if specs is None else specs:
        label = str(ABI_DIR / f"{contract}.json")
        expected, gone = expected_abi(built_abi(root, contract), names)
        problems += [f"stale: {label}: the dashboard calls function {n}, the source no longer exposes it"
                     for n in gone]
        path = root / ABI_DIR / f"{contract}.json"
        if not path.exists():
            problems.append(f"stale: {label} missing")
            continue
        raw = path.read_bytes()
        try:
            committed = json.loads(raw)
        except json.JSONDecodeError as exc:
            problems.append(f"stale: {label} is not JSON ({exc})")
            continue
        entry_problems = abi_problems(label, expected, committed, pruned=names is not None)
        problems += entry_problems
        if not entry_problems and not gone and raw != render_abi(expected):
            problems.append(f"stale: {label} holds the right entries but not in the generator's layout")
    return problems


def write_abis(root: Path, specs=None) -> tuple[list[str], list[str]]:
    """(paths written, problems). A pruned spec naming a function the build lacks is not written: the file
    would silently drop a call the dashboard makes."""
    written, problems = [], []
    for contract, names in ABI_SPECS if specs is None else specs:
        label = str(ABI_DIR / f"{contract}.json")
        expected, gone = expected_abi(built_abi(root, contract), names)
        if gone:
            problems += [f"stale: {label}: the dashboard calls function {n}, the source no longer exposes it "
                         f"(not written)" for n in gone]
            continue
        path = root / ABI_DIR / f"{contract}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(render_abi(expected))
        written.append(label)
    return written, problems


# --------------------------------------------------------------------------- canonical registry init code

def create2_address(factory: str, salt: str, init_code: bytes) -> str:
    digest = keccak(b"\xff" + bytes.fromhex(factory[2:]) + bytes.fromhex(salt[2:]) + keccak(init_code))
    return to_checksum_address(digest[12:])


def check_registry_bin(root: Path) -> list[str]:
    path = root / REGISTRY_BIN
    if not path.exists():
        return [f"stale: {REGISTRY_BIN} missing"]
    got = create2_address(NICKS_FACTORY, CANONICAL_SALT, path.read_bytes())
    if got != to_checksum_address(CANONICAL_REGISTRY):
        return [f"stale: {REGISTRY_BIN} deploys to {got} through Nick's factory with the canonical salt, "
                f"not the canonical registry {CANONICAL_REGISTRY} (DeployCommon would revert)"]
    return []


# --------------------------------------------------------------------------- CLI

def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--write", action="store_true", help="regenerate dashboard/abi/*.json from the current build")
    ap.add_argument("--no-build", action="store_true", help="skip `forge build`; only when out/ is known fresh")
    ap.add_argument("--root", type=Path, default=ROOT, help="checkout to operate on (default: this repo)")
    args = ap.parse_args(argv)
    root = args.root.resolve()
    try:
        if not root.is_dir():
            raise SetupError(f"{root} is not a directory")
        if not args.no_build:
            build(root)
        if args.write:
            written, problems = write_abis(root)
            if written:
                print(f"wrote {', '.join(written)}")
        else:
            problems = check_abis(root)
    except SetupError as exc:
        print(f"setup: {exc}", file=sys.stderr)
        return 2
    problems += check_registry_bin(root)
    for p in problems:
        print(p, file=sys.stderr)
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
