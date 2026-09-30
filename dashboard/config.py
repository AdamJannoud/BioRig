"""Address resolution and chain settings for the BioRig demo dashboard.

Proxy address precedence (first hit wins):
  1. broadcast/DeployAll.s.sol/<chain>/run-latest.json   (the script that actually deployed)
  2. broadcast/DeployBioRig.s.sol/<chain>/run-latest.json (kept in case the script is renamed)
  3. PROXY_ADDRESS from .env, st.secrets or the process environment
  4. dashboard/deployment.json                           (static record of the live deployment)
Anything else fails loudly with ProxyResolutionError, listing every candidate and why it was skipped.

Candidates 1 and 2 need the broadcast artifacts and 3 needs a configured secret, so 4 is what keeps a
hosted deployment rendering from a checkout that has neither. The chain id, RPC endpoint and explorer URL
have module-level static defaults for the same reason.

Secrets never leave this module in printable form: Settings.__repr__ masks the key.
"""
from __future__ import annotations

import json
import os
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
EXPECTED_CHAIN_ID = 11142220
DEFAULT_RPC_URL = "https://forno.celo-sepolia.celo-testnet.org"
DEFAULT_EXPLORER_URL = "https://celo-sepolia.blockscout.com"
BROADCAST_SCRIPTS = ("DeployAll.s.sol", "DeployBioRig.s.sol")

_ADDRESS_RE = re.compile(r"^0x[0-9a-fA-F]{40}$")

# Settings the dashboard reads, from .env locally or the app's Secrets on a hosted platform.
CONFIG_KEYS = ("RPC_URL", "CHAIN_ID", "EXPLORER_URL", "PRIVATE_KEY", "PROXY_ADDRESS", "PROXY_DEPLOY_BLOCK",
               "ALLOW_MINT")
STATIC_DEPLOYMENT_FILE = Path("dashboard") / "deployment.json"


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


def hosted_secrets() -> dict[str, str]:
    """Top-level string entries of Streamlit's `st.secrets`, for a hosted deployment.

    Community Cloud and Hugging Face Spaces hand the app a secrets.toml, read through Streamlit, with the
    keys named exactly like the .env variables. Empty when Streamlit is absent or has no secrets file,
    which is the ordinary local case, so this is safe to call unconditionally.
    """
    try:
        import streamlit as st
    except ImportError:
        return {}
    try:
        items = st.secrets.items()
    except Exception:  # no secrets.toml on this machine
        return {}
    return {key: str(value) for key, value in items if isinstance(value, (str, int, float))}


def _flag(value: str | None, default: bool) -> bool:
    """Parse an on/off setting. Unset keeps the default; anything unrecognised counts as off.

    Failing closed matters for ALLOW_MINT: a typo in a public deployment's Secrets must not be the thing that
    re-enables broadcasting from the verifier key.
    """
    if value is None or not str(value).strip():
        return default
    return str(value).strip().lower() in ("1", "true", "yes", "on")


def _proxy_from_deployment(path: Path, chain_id: int) -> tuple[str, int | None]:
    """Return (proxy address, deploy block) from the committed static record, or raise ValueError why not."""
    if not path.is_file():
        raise ValueError("file not found")
    try:
        data = json.loads(path.read_text())
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise ValueError(f"malformed JSON ({exc.__class__.__name__})") from exc
    if not isinstance(data, dict):
        raise ValueError("not a JSON object")
    try:
        recorded_chain = None if data.get("chain_id") is None else int(data["chain_id"])
    except (TypeError, ValueError) as exc:
        raise ValueError(f"chain_id is not an integer ({data.get('chain_id')!r})") from exc
    if recorded_chain is not None and recorded_chain != chain_id:
        raise ValueError(f"records chain {recorded_chain}, not {chain_id}")
    addr = str(data.get("proxy_address") or "")
    if not _ADDRESS_RE.match(addr):
        raise ValueError(f"proxy_address is not a 20-byte hex address ({addr!r})")
    block = data.get("proxy_deploy_block")
    return addr.lower(), int(block) if isinstance(block, int) else None


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

    try:
        addr, block = _proxy_from_deployment(repo_root / STATIC_DEPLOYMENT_FILE, chain_id)
    except ValueError as exc:
        skipped.append(f"{STATIC_DEPLOYMENT_FILE}: {exc}")
    else:
        return Resolution(addr, f"{STATIC_DEPLOYMENT_FILE} (static fallback)", block, tuple(skipped))

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
    allow_mint: bool = True  # False on a public deployment: the simulation stays, the broadcast does not

    def __repr__(self) -> str:  # never render the key, even by accident in st.write / logs
        key = "set" if self.private_key else "unset"
        return (f"Settings(rpc_url={self.rpc_url!r}, chain_id={self.chain_id}, "
                f"proxy={self.proxy.address} via {self.proxy.source}, private_key=<{key}>, "
                f"allow_mint={self.allow_mint})")

    __str__ = __repr__


def load_settings(repo_root: Path = REPO_ROOT, env_file: Path | None = None,
                  secrets: Mapping[str, str] | None = None) -> Settings:
    """Merge .env, hosted secrets and the process environment (last one wins), then resolve the proxy.

    `secrets` defaults to what the platform handed the app (hosted_secrets()); pass a mapping to exercise a
    hosted configuration without a secrets file on disk.
    """
    env = load_dotenv(env_file or repo_root / ".env")
    env.update(hosted_secrets() if secrets is None else secrets)
    for key in CONFIG_KEYS:
        if os.environ.get(key):
            env[key] = os.environ[key]
    chain_id = int(env.get("CHAIN_ID") or EXPECTED_CHAIN_ID)
    return Settings(
        rpc_url=env.get("RPC_URL") or DEFAULT_RPC_URL,
        chain_id=chain_id,
        explorer_url=(env.get("EXPLORER_URL") or DEFAULT_EXPLORER_URL).rstrip("/"),
        proxy=resolve_proxy(repo_root, env, chain_id),
        private_key=env.get("PRIVATE_KEY") or None,
        allow_mint=_flag(env.get("ALLOW_MINT"), True),
    )
