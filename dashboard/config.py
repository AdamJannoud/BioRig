"""Address resolution and chain settings for the BioRig demo dashboard.

Proxy address precedence (first hit wins):
  1. broadcast/DeployAll.s.sol/<chain>/run-latest.json   (the script that actually deployed)
  2. broadcast/DeployBioRig.s.sol/<chain>/run-latest.json (kept in case the script is renamed)
  3. PROXY_ADDRESS in .env / the process environment
Anything else fails loudly with ProxyResolutionError, listing every candidate and why it was skipped.

Secrets never leave this module in printable form: Settings.__repr__ masks the key.
"""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
EXPECTED_CHAIN_ID = 11142220
DEFAULT_RPC_URL = "https://forno.celo-sepolia.celo-testnet.org"
DEFAULT_EXPLORER_URL = "https://celo-sepolia.blockscout.com"
BROADCAST_SCRIPTS = ("DeployAll.s.sol", "DeployBioRig.s.sol")

_ADDRESS_RE = re.compile(r"^0x[0-9a-fA-F]{40}$")


class ProxyResolutionError(RuntimeError):
    """No usable proxy address in any candidate source."""


@dataclass(frozen=True)
class Resolution:
    address: str  # lowercase 0x-hex; callers checksum it with web3
    source: str  # human-readable origin, shown in the UI
    deploy_block: int | None = None  # block the proxy was created in, if the broadcast recorded it
    skipped: tuple[str, ...] = ()  # candidates tried before this one, with reasons


def load_dotenv(path: Path) -> dict[str, str]:
    """Parse KEY=VALUE lines. Comments, blanks and malformed lines are ignored; later keys win."""
    env: dict[str, str] = {}
    if not path.is_file():
        return env
    for raw in path.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        if key.startswith("export "):
            key = key[len("export "):].strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        env[key] = value
    return env


def _proxy_from_broadcast(path: Path) -> tuple[str, int | None]:
    """Return (proxy address, deploy block) from a forge broadcast file, or raise ValueError why not."""
    if not path.is_file():
        raise ValueError("file not found")
    try:
        data = json.loads(path.read_text())
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise ValueError(f"malformed JSON ({exc.__class__.__name__})") from exc
    txs = data.get("transactions") if isinstance(data, dict) else None
    if not isinstance(txs, list):
        raise ValueError("no 'transactions' array")
    proxies = [
        t for t in txs
        if isinstance(t, dict)
        and t.get("transactionType") in ("CREATE", "CREATE2")
        and t.get("contractName") == "ERC1967Proxy"
    ]
    if not proxies:
        raise ValueError("no ERC1967Proxy creation in this broadcast")
    tx = proxies[-1]
    addr = str(tx.get("contractAddress") or "")
    if not _ADDRESS_RE.match(addr):
        raise ValueError(f"ERC1967Proxy entry has an invalid contractAddress {addr!r}")
    block = None
    for rc in data.get("receipts") or []:
        if isinstance(rc, dict) and rc.get("transactionHash") == tx.get("hash") and rc.get("blockNumber"):
            bn = rc["blockNumber"]
            block = int(bn, 16) if isinstance(bn, str) else int(bn)
    return addr.lower(), block


def resolve_proxy(repo_root: Path, env: dict[str, str], chain_id: int = EXPECTED_CHAIN_ID) -> Resolution:
    skipped: list[str] = []
    for script in BROADCAST_SCRIPTS:
        path = repo_root / "broadcast" / script / str(chain_id) / "run-latest.json"
        rel = path.relative_to(repo_root)
        try:
            addr, block = _proxy_from_broadcast(path)
        except ValueError as exc:
            skipped.append(f"{rel}: {exc}")
            continue
        return Resolution(addr, str(rel), block, tuple(skipped))

    env_addr = (env.get("PROXY_ADDRESS") or "").strip()
    if env_addr:
        if _ADDRESS_RE.match(env_addr):
            block = env.get("PROXY_DEPLOY_BLOCK", "").strip()
            return Resolution(env_addr.lower(), ".env PROXY_ADDRESS", int(block) if block.isdigit() else None,
                              tuple(skipped))
        skipped.append(f".env PROXY_ADDRESS: not a 20-byte hex address ({env_addr!r})")
    else:
        skipped.append(".env PROXY_ADDRESS: not set")

    raise ProxyResolutionError(
        "Could not resolve the BioRig proxy address. Tried, in order:\n  - "
        + "\n  - ".join(skipped)
        + "\nFix: run script/DeployAll.s.sol with --broadcast, or add PROXY_ADDRESS=0x... to .env."
    )


@dataclass(frozen=True)
class Settings:
    rpc_url: str
    chain_id: int
    explorer_url: str
    proxy: Resolution
    private_key: str | None = field(default=None, repr=False)

    def __repr__(self) -> str:  # never render the key, even by accident in st.write / logs
        key = "set" if self.private_key else "unset"
        return (f"Settings(rpc_url={self.rpc_url!r}, chain_id={self.chain_id}, "
                f"proxy={self.proxy.address} via {self.proxy.source}, private_key=<{key}>)")

    __str__ = __repr__


def load_settings(repo_root: Path = REPO_ROOT, env_file: Path | None = None) -> Settings:
    """Merge .env with the process environment (process wins), then resolve the proxy."""
    env = load_dotenv(env_file or repo_root / ".env")
    for key in ("RPC_URL", "CHAIN_ID", "EXPLORER_URL", "PRIVATE_KEY", "PROXY_ADDRESS", "PROXY_DEPLOY_BLOCK"):
        if os.environ.get(key):
            env[key] = os.environ[key]
    chain_id = int(env.get("CHAIN_ID") or EXPECTED_CHAIN_ID)
    return Settings(
        rpc_url=env.get("RPC_URL") or DEFAULT_RPC_URL,
        chain_id=chain_id,
        explorer_url=(env.get("EXPLORER_URL") or DEFAULT_EXPLORER_URL).rstrip("/"),
        proxy=resolve_proxy(repo_root, env, chain_id),
        private_key=env.get("PRIVATE_KEY") or None,
    )
