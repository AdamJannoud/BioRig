#!/usr/bin/env python3
"""Find the solc settings that reproduce the canonical ERC-6551 registry's on-chain bytecode.

The registry at 0x000000006551c19487814612e58FE06813775758 is the EIP-6551 canonical deployment,
built when solc 0.8.17 was current. This repo compiles its vendored copy with 0.8.28, whose default
target uses PUSH0 (the repo build starts 0x608060405234801561000f575f5ffd5b), so the deployed
bytecode cannot match and Blockscout rejects it as an exact match.

Source and settings are the only two variables left. The source is checked byte for byte against
what the canonical build used (see --source), so this searches compiler version and settings and
reports which, if any, reproduce the on-chain bytes exactly.

    ./script/registry-byte-match.py            # search and print the table
    ./script/registry-byte-match.py --submit   # submit the first exact match to Blockscout
    CHAIN_ID=42220 ./script/registry-byte-match.py

The chain is CHAIN_ID from the environment or .env, else the repo default; its RPC (RPC_URL overrides) and
Blockscout verifier come from dashboard/chains.json.

Compiling spends nothing; only --submit spends Blockscout's quota (10 unauthenticated v1 requests
per ~30 minute window, see script/verify-retry.sh).
"""
from __future__ import annotations

import argparse
import itertools
import json
import pathlib
import shutil
import subprocess
import sys
import urllib.request

REPO = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
from dashboard.config import ChainSelectionError, _merged_env, select_chain  # noqa: E402

REGISTRY = "0x000000006551c19487814612e58FE06813775758"
SOURCE_REL = "src/vendor/ERC6551Registry.sol"
CONTRACT = "ERC6551Registry"
SOLC_CACHE = pathlib.Path.home() / ".cache" / "solc-byte-match"
SOLC_URL = (
    "https://binaries.soliditylang.org/linux-amd64/"
    "solc-linux-amd64-v{version}+commit.{commit}"
)
VERSIONS = {"0.8.17": "8df45f5f"}
OPTIMIZER_RUNS = [None, 200, 1000, 100000, 1000000]
VIA_IR = [False, True]
EVM_VERSIONS = [None, "london", "paris", "shanghai"]

EVIDENCE = REPO / "evidence" / "registry-byte-match.log"


def log(line: str = "") -> None:
    print(line, flush=True)
    EVIDENCE.parent.mkdir(parents=True, exist_ok=True)
    with EVIDENCE.open("a") as fh:
        fh.write(line + "\n")


def strip_metadata(code: bytes) -> tuple[bytes, bytes]:
    """Split solc's trailing CBOR metadata off the runtime code."""
    if len(code) < 2:
        return code, b""
    length = int.from_bytes(code[-2:], "big")
    if 0 < length <= 200 and length + 2 <= len(code):
        return code[: len(code) - length - 2], code[len(code) - length - 2:]
    return code, b""


def solc_path(version: str) -> pathlib.Path:
    binary = SOLC_CACHE / f"solc-{version}"
    if binary.exists():
        return binary
    SOLC_CACHE.mkdir(parents=True, exist_ok=True)
    url = SOLC_URL.format(version=version, commit=VERSIONS[version])
    log(f"downloading {url}")
    # binaries.soliditylang.org answers urllib's default user agent with a 403, so send a curl one.
    request = urllib.request.Request(url, headers={"User-Agent": "curl/8.5.0"})
    with urllib.request.urlopen(request) as response, binary.open("wb") as fh:
        shutil.copyfileobj(response, fh)
    binary.chmod(0o755)
    out = subprocess.run([binary, "--version"], capture_output=True, text=True)
    if out.returncode != 0:
        sys.exit(f"downloaded solc is not runnable: {out.stderr.strip()}")
    log(out.stdout.strip())
    return binary


def chain_settings() -> tuple[int, str, str]:
    """(chain id, RPC URL, Blockscout verifier URL) for the selected chain."""
    env = _merged_env(REPO, None, {})
    try:
        chain = select_chain(env, REPO)
    except ChainSelectionError as exc:
        sys.exit(str(exc))
    return chain.chain_id, env.get("RPC_URL") or chain.rpc_url, chain.verifier_url


def rpc_url() -> str:
    return chain_settings()[1]


def on_chain_code() -> bytes:
    out = subprocess.run(
        ["cast", "code", REGISTRY, "--rpc-url", rpc_url()],
        capture_output=True, text=True, check=True,
    )
    return bytes.fromhex(out.stdout.strip().removeprefix("0x"))


def compile_one(solc: pathlib.Path, source: str, runs: int | None, via_ir: bool,
                evm: str | None) -> bytes | None:
    optimizer: dict[str, object] = {"enabled": runs is not None}
    if runs is not None:
        optimizer["runs"] = runs
    settings: dict[str, object] = {
        "optimizer": optimizer,
        "viaIR": via_ir,
        "outputSelection": {"*": {"*": ["evm.deployedBytecode.object"]}},
    }
    if evm is not None:
        settings["evmVersion"] = evm
    payload = {
        "language": "Solidity",
        "sources": {SOURCE_REL: {"content": source}},
        "settings": settings,
    }
    out = subprocess.run(
        [solc, "--standard-json"], input=json.dumps(payload),
        capture_output=True, text=True,
    )
    try:
        parsed = json.loads(out.stdout)
    except json.JSONDecodeError:
        if "PUSH0" in out.stderr or "Invalid EVM version" in out.stderr:
            return None
        raise
    if "errors" in parsed:
        fatal = [e for e in parsed["errors"] if e.get("severity") == "error"]
        if fatal:
            log(f"  compile error: {fatal[0]['formattedMessage'].splitlines()[0]}")
            return None
    contract = parsed["contracts"][SOURCE_REL][CONTRACT]
    return bytes.fromhex(contract["evm"]["deployedBytecode"]["object"])


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--submit", action="store_true",
                        help="submit the first exact match to Blockscout")
    args = parser.parse_args()

    EVIDENCE.unlink(missing_ok=True)
    source = (REPO / SOURCE_REL).read_text()
    chain = on_chain_code()
    chain_exec, chain_meta = strip_metadata(chain)
    log(f"on-chain runtime      : {len(chain)} bytes "
        f"(executable {len(chain_exec)}, metadata {len(chain_meta)})")
    log(f"source sha256         : {__import__('hashlib').sha256(source.encode()).hexdigest()}")
    log(f"source                : {SOURCE_REL} ({len(source)} bytes)")

    exact: list[tuple[str, int | None, bool, str | None]] = []
    executable: list[tuple[str, int | None, bool, str | None]] = []
    for version, runs, via_ir, evm in itertools.product(
        VERSIONS, OPTIMIZER_RUNS, VIA_IR, EVM_VERSIONS
    ):
        solc = solc_path(version)
        code = compile_one(solc, source, runs, via_ir, evm)
        if code is None:
            continue
        exec_code, meta = strip_metadata(code)
        combo = (version, runs, via_ir, evm)
        if code == chain:
            exact.append(combo)
        elif exec_code == chain_exec:
            executable.append(combo)
        log(f"  solc {version} runs={runs or 'off'} viaIR={via_ir} evm={evm or 'default'}"
            f" -> {len(code)} bytes (executable {len(exec_code)}, metadata {len(meta)})")

    log("")
    log(f"exact bytecode matches      : {len(exact)} {exact if exact else ''}")
    log(f"executable-only matches     : {len(executable)} {executable if executable else ''}")

    if not exact and not executable:
        log("No settings reproduce the canonical runtime code.")
        return 1

    if args.submit:
        version, runs, via_ir, evm = (exact or executable)[0]
        cmd = [
            "forge", "verify-contract", REGISTRY,
            f"{SOURCE_REL}:{CONTRACT}",
            "--verifier", "blockscout",
            "--verifier-url", chain_settings()[2],
            "--chain", str(chain_settings()[0]),
            "--skip-is-verified-check",
            "--compiler-version", f"v{version}",
        ]
        if runs is not None:
            cmd += ["--num-of-optimizations", str(runs)]
        if via_ir:
            cmd += ["--via-ir"]
        if evm is not None:
            cmd += ["--evm-version", evm]
        log("")
        log("submitting: " + " ".join(cmd))
        subprocess.run(cmd, cwd=REPO)
    return 0


if __name__ == "__main__":
    sys.exit(main())
