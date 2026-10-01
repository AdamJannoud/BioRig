"""Address resolution and chain settings for the BioRig demo dashboard.

Proxy address precedence (first hit wins):
  1. broadcast/DeployAll.s.sol/<chain>/run-latest.json   (the script that actually deployed)
  2. broadcast/DeployBioRig.s.sol/<chain>/run-latest.json (kept in case the script is renamed)
  3. PROXY_ADDRESS from .env, st.secrets or the process environment
  4. dashboard/deployment.json                           (static record of the live deployment)
Anything else fails loudly with ProxyResolutionError, listing every candidate and why it was skipped.

Candidates 1 and 2 need the broadcast artifacts and 3 needs a configured secret, so 4 is what keeps a
hosted deployment rendering from a checkout that has neither.

Chain selection (first hit wins):
  1. CHAIN_ID from .env, st.secrets or the process environment
  2. default_chain_id in dashboard/deployment.json                  (the repo's default chain)
Anything else fails loudly with ChainSelectionError, listing the chains dashboard/chains.json knows. That file
is the per-chain registry (name, RPC, explorer, Blockscout verifier API, canonical ERC-6551 registry); RPC_URL
and EXPLORER_URL override the selected chain's entries, nothing else does, and only when set in the same layer as
CHAIN_ID or a later one: a CHAIN_ID exported over a .env written for another chain drops that file's RPC_URL and
EXPLORER_URL instead of mixing two chains. EXPECTED_CHAIN_ID, DEFAULT_RPC_URL
and DEFAULT_EXPLORER_URL are derived from the default chain's entry, never written here.

Run as `python3 -m dashboard.config get <field>` from the repository root, the selected chain's settings are
printed for the shell scripts, so they read the same registry instead of carrying their own copy.

Secrets never leave this module in printable form: Settings.__repr__ masks the key.
"""
from __future__ import annotations

import json
import os
import re
import sys
from collections.abc import Mapping
from dataclasses import dataclass, field
from dataclasses import replace as _replace
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
CHAINS_FILE = Path(__file__).resolve().parent / "chains.json"
BROADCAST_SCRIPTS = ("DeployAll.s.sol", "DeployBioRig.s.sol")

_ADDRESS_RE = re.compile(r"^0x[0-9a-fA-F]{40}$")

# Settings the dashboard reads, from .env locally or the app's Secrets on a hosted platform.
CONFIG_KEYS = ("RPC_URL", "CHAIN_ID", "EXPLORER_URL", "PRIVATE_KEY", "PROXY_ADDRESS", "PROXY_DEPLOY_BLOCK",
               "ALLOW_MINT")
STATIC_DEPLOYMENT_FILE = Path("dashboard") / "deployment.json"


class ProxyResolutionError(RuntimeError):
    """No usable proxy address in any candidate source."""


class ChainSelectionError(RuntimeError):
    """No chain selected, or the selected chain is not in dashboard/chains.json."""


class PrivateKeyError(ValueError):
    """PRIVATE_KEY is set but is not a 32-byte hex key. Signing is optional, so this never blocks the reads:
    `settings` is the fully resolved configuration with the key dropped (read-only), ready to render.

    The message names the length and the index of the first invalid character, never any part of the value.
    """

    def __init__(self, message: str, settings: "Settings | None" = None):
        super().__init__(message)
        self.settings = settings


_HEX_DIGITS = frozenset("0123456789abcdefABCDEF")
_SECP256K1_N = 0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFEBAAEDCE6AF48A03BBFD25E8CD0364141


def validate_private_key(raw: str | None) -> str | None:
    """`raw` if it is a usable signing key (`0x` + 64 hex digits, or 64 bare hex digits), None if unset.

    Anything else raises PrivateKeyError: wrong length, a non-hex or non-ASCII character, a JSON envelope pasted
    whole. Only character-level checks run on the value, so no codec error can escape from here, and the error
    carries the length and an index, nothing from the value itself.
    """
    if raw is None or not raw.strip():
        return None
    key = raw.strip()
    digits_at = 2 if key.startswith("0x") else 0
    bad = next((i for i, c in enumerate(key) if i >= digits_at and c not in _HEX_DIGITS), None)
    expected = "expected 0x followed by 64 hex digits, or 64 bare hex digits"
    if bad is not None:
        raise PrivateKeyError(f"PRIVATE_KEY is not a hex key: {len(key)} characters, first invalid character at "
                              f"index {bad}; {expected}.")
    if len(key) - digits_at != 64:
        raise PrivateKeyError(f"PRIVATE_KEY has the wrong length: {len(key)} characters with "
                              f"{len(key) - digits_at} hex digits; {expected}.")
    if not 0 < int(key[digits_at:], 16) < _SECP256K1_N:
        raise PrivateKeyError(f"PRIVATE_KEY is out of range for secp256k1: {len(key)} characters, all hex, but "
                              "the value is zero or not below the curve order.")
    return key


@dataclass(frozen=True)
class ChainConfig:
    chain_id: int
    name: str  # human name, shown in the UI and the diagram
    testnet: bool
    native_currency: str
    rpc_url: str
    explorer_url: str  # no trailing slash
    verifier_url: str  # Blockscout API, as forge's --verifier-url wants it
    erc6551_registry: str  # lowercase 0x-hex: the registry the deploy scripts wire into initialize
    erc6551_registry_codehash: str  # keccak256 of its runtime code, so a fork run can tell the canonical one
    faucet_url: str | None = None


_CHAIN_FIELDS = ("name", "testnet", "native_currency", "rpc_url", "explorer_url", "verifier_url",
                 "erc6551_registry", "erc6551_registry_codehash")


def load_chains(path: Path = CHAINS_FILE) -> dict[int, ChainConfig]:
    """Parse the chain registry. A malformed file is a broken checkout, so this raises rather than guessing."""
    try:
        data = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise ChainSelectionError(f"{path.name}: unreadable chain registry ({exc.__class__.__name__}: {exc})") from exc
    chains: dict[int, ChainConfig] = {}
    for key, entry in (data.get("chains") or {}).items() if isinstance(data, dict) else ():
        missing = [f for f in _CHAIN_FIELDS if not isinstance(entry, dict) or entry.get(f) in (None, "")]
        if missing or not str(key).isdigit():
            raise ChainSelectionError(f"{path.name}: chain {key!r} is missing {', '.join(missing) or 'a numeric id'}")
        if not _ADDRESS_RE.match(str(entry["erc6551_registry"])):
            raise ChainSelectionError(f"{path.name}: chain {key} erc6551_registry is not a 20-byte hex address")
        chains[int(key)] = ChainConfig(
            chain_id=int(key), name=entry["name"], testnet=bool(entry["testnet"]),
            native_currency=entry["native_currency"], rpc_url=entry["rpc_url"],
            explorer_url=entry["explorer_url"].rstrip("/"), verifier_url=entry["verifier_url"],
            erc6551_registry=entry["erc6551_registry"].lower(),
            erc6551_registry_codehash=entry["erc6551_registry_codehash"].lower(),
            faucet_url=entry.get("faucet_url") or None)
    if not chains:
        raise ChainSelectionError(f"{path.name}: no chains defined")
    return chains


CHAINS = load_chains()


def _known_chains() -> str:
    return ", ".join(f"{cid} ({c.name})" for cid, c in sorted(CHAINS.items()))


def chain_config(chain_id: int) -> ChainConfig:
    """The registry entry for `chain_id`, or ChainSelectionError naming every chain that does have one."""
    try:
        return CHAINS[int(chain_id)]
    except (KeyError, TypeError, ValueError):
        raise ChainSelectionError(
            f"chain {chain_id!r} is not in dashboard/{CHAINS_FILE.name}; known chains: {_known_chains()}") from None


def _read_deployment_file(path: Path) -> dict:
    if not path.is_file():
        raise ValueError("file not found")
    try:
        data = json.loads(path.read_text())
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise ValueError(f"malformed JSON ({exc.__class__.__name__})") from exc
    if not isinstance(data, dict):
        raise ValueError("not a JSON object")
    return data


def _int_field(data: dict, key: str) -> int | None:
    try:
        return None if data.get(key) is None else int(data[key])
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{key} is not an integer ({data.get(key)!r})") from exc


def default_chain_id(repo_root: Path = REPO_ROOT) -> int:
    """The repo's default chain: default_chain_id in deployment.json, or chain_id in the older flat record."""
    path = repo_root / STATIC_DEPLOYMENT_FILE
    try:
        data = _read_deployment_file(path)
        chain_id = _int_field(data, "default_chain_id" if "deployments" in data else "chain_id")
    except ValueError as exc:
        chain_id, why = None, str(exc)
    else:
        why = "names no default chain"
    if chain_id is None:
        raise ChainSelectionError(
            f"No chain selected: CHAIN_ID is not set and {STATIC_DEPLOYMENT_FILE} {why}. "
            f"Set CHAIN_ID to one of: {_known_chains()}")
    return chain_id


def select_chain(env: Mapping[str, str], repo_root: Path = REPO_ROOT) -> ChainConfig:
    """Explicit CHAIN_ID wins, then the repo's default chain; either way it has to be a registered chain."""
    raw = str(env.get("CHAIN_ID") or "").strip()
    if not raw:
        return chain_config(default_chain_id(repo_root))
    if not raw.isdigit():
        raise ChainSelectionError(f"CHAIN_ID {raw!r} is not an integer; known chains: {_known_chains()}")
    return chain_config(int(raw))


def _default_chain_or_none() -> ChainConfig | None:
    try:
        return chain_config(default_chain_id())
    except ChainSelectionError:  # resolved again, loudly, by select_chain when a caller actually needs it
        return None


# Kept for callers that predate the registry; all three follow the default chain's entry.
_DEFAULT_CHAIN = _default_chain_or_none()
EXPECTED_CHAIN_ID = _DEFAULT_CHAIN.chain_id if _DEFAULT_CHAIN else None
DEFAULT_RPC_URL = _DEFAULT_CHAIN.rpc_url if _DEFAULT_CHAIN else None
DEFAULT_EXPLORER_URL = _DEFAULT_CHAIN.explorer_url if _DEFAULT_CHAIN else None


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
    """Return (proxy address, deploy block) from the committed static record, or raise ValueError why not.

    The record is a per-chain map (`deployments`, keyed by chain id). The older flat shape, one deployment with
    `chain_id` beside it, is still read, so a record written before the map existed keeps resolving.
    """
    data = _read_deployment_file(path)
    if "deployments" in data:
        deployments = data["deployments"]
        if not isinstance(deployments, dict):
            raise ValueError("deployments is not a JSON object")
        entry = deployments.get(str(chain_id))
        if not isinstance(entry, dict):
            recorded = ", ".join(sorted(deployments)) or "none"
            raise ValueError(f"no deployment recorded for chain {chain_id} (recorded: {recorded})")
    else:
        recorded_chain = _int_field(data, "chain_id")
        if recorded_chain is not None and recorded_chain != chain_id:
            raise ValueError(f"records chain {recorded_chain}, not {chain_id}")
        entry = data
    addr = str(entry.get("proxy_address") or "")
    if not _ADDRESS_RE.match(addr):
        raise ValueError(f"proxy_address is not a 20-byte hex address ({addr!r})")
    block = entry.get("proxy_deploy_block")
    return addr.lower(), int(block) if isinstance(block, int) else None


def recorded_deployment(path: Path, chain_id: int | None = None) -> tuple[int, str, int | None]:
    """(chain id, proxy, deploy block) the static record holds for `chain_id`, or for its default chain when
    `chain_id` is None. ValueError, with the reason, when the record has no such deployment."""
    if chain_id is None:
        data = _read_deployment_file(path)
        chain_id = _int_field(data, "default_chain_id" if "deployments" in data else "chain_id")
        if chain_id is None:
            raise ValueError("names no default chain")
    proxy, block = _proxy_from_deployment(path, chain_id)
    return chain_id, proxy, block


def record_deployment(path: Path, chain_id: int, proxy_address: str, proxy_deploy_block: int,
                      make_default: bool = False, replace: bool = False) -> dict:
    """Add one chain's deployment to the static record and return the new contents (also written to `path`).

    A flat record is migrated to the per-chain map first. An existing entry for the chain is only overwritten
    with `replace`, so re-running this after a redeploy is a decision rather than an accident.
    """
    chain_config(chain_id)  # refuse a chain the rest of the repo cannot talk to
    if not _ADDRESS_RE.match(proxy_address):
        raise ValueError(f"proxy_address is not a 20-byte hex address ({proxy_address!r})")
    data = _read_deployment_file(path) if path.exists() else {"deployments": {}}
    if "deployments" not in data:
        flat_chain = _int_field(data, "chain_id")
        if flat_chain is None:
            raise ValueError("flat record without chain_id; cannot tell which chain it belongs to")
        data = {"default_chain_id": flat_chain, "deployments": {str(flat_chain): {
            "proxy_address": str(data["proxy_address"]).lower(),
            "proxy_deploy_block": data.get("proxy_deploy_block")}}}
    deployments = data["deployments"]
    existing = deployments.get(str(chain_id))
    entry = {"proxy_address": proxy_address.lower(), "proxy_deploy_block": int(proxy_deploy_block)}
    if existing and existing != entry and not replace:
        raise ValueError(f"chain {chain_id} already records proxy {existing.get('proxy_address')}; "
                         "pass replace=True (--replace) to overwrite it")
    deployments[str(chain_id)] = entry
    data["deployments"] = dict(sorted(deployments.items(), key=lambda kv: int(kv[0])))
    if make_default or data.get("default_chain_id") is None:
        data["default_chain_id"] = int(chain_id)
    data = {"default_chain_id": data["default_chain_id"], "deployments": data["deployments"]}
    path.write_text(json.dumps(data, indent=2) + "\n")
    return data


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


def resolve_proxy(repo_root: Path, env: dict[str, str], chain_id: int | None = None) -> Resolution:
    if chain_id is None:
        chain_id = select_chain(env, repo_root).chain_id
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
    chain: ChainConfig | None = None  # the registry entry chain_id selected

    @property
    def chain_name(self) -> str:
        return self.chain.name if self.chain else f"chain {self.chain_id}"

    def __repr__(self) -> str:  # never render the key, even by accident in st.write / logs
        key = "set" if self.private_key else "unset"
        return (f"Settings(rpc_url={self.rpc_url!r}, chain_id={self.chain_id}, "
                f"proxy={self.proxy.address} via {self.proxy.source}, private_key=<{key}>, "
                f"allow_mint={self.allow_mint})")

    __str__ = __repr__


def _merged_env_layers(repo_root: Path, env_file: Path | None,
                       secrets: Mapping[str, str] | None) -> tuple[dict[str, str], dict[str, int]]:
    """The merged settings, and for each key the layer it came from: 0 .env, 1 secrets, 2 process environment."""
    env = load_dotenv(env_file or repo_root / ".env")
    layers = dict.fromkeys(env, 0)
    for key, value in (hosted_secrets() if secrets is None else secrets).items():
        env[key], layers[key] = value, 1
    for key in CONFIG_KEYS:
        if os.environ.get(key):
            env[key], layers[key] = os.environ[key], 2
    return env, layers


def _merged_env(repo_root: Path, env_file: Path | None, secrets: Mapping[str, str] | None) -> dict[str, str]:
    return _merged_env_layers(repo_root, env_file, secrets)[0]


def _chain_override(env: Mapping[str, str], layers: Mapping[str, int], key: str) -> str | None:
    """`key` (RPC_URL, EXPLORER_URL) if it was set alongside the chain choice or above it, else None.

    An RPC_URL in .env was written for .env's CHAIN_ID; once a higher layer picks another chain it no longer applies.
    """
    value = (env.get(key) or "").strip()
    if not value:
        return None
    chain_layer = layers.get("CHAIN_ID", -1) if str(env.get("CHAIN_ID") or "").strip() else -1
    return value if layers.get(key, -1) >= chain_layer else None


def network_settings(repo_root: Path = REPO_ROOT, env_file: Path | None = None,
                     secrets: Mapping[str, str] | None = None) -> tuple[ChainConfig, str, str, dict[str, str]]:
    """(selected chain, RPC URL, explorer URL, merged env), applying the overrides that belong to that chain."""
    env, layers = _merged_env_layers(repo_root, env_file, secrets)
    chain = select_chain(env, repo_root)
    rpc_url = _chain_override(env, layers, "RPC_URL") or chain.rpc_url
    explorer_url = (_chain_override(env, layers, "EXPLORER_URL") or chain.explorer_url).rstrip("/")
    return chain, rpc_url, explorer_url, env


def load_settings(repo_root: Path = REPO_ROOT, env_file: Path | None = None,
                  secrets: Mapping[str, str] | None = None) -> Settings:
    """Merge .env, hosted secrets and the process environment (last one wins), then select the chain and
    resolve the proxy.

    `secrets` defaults to what the platform handed the app (hosted_secrets()); pass a mapping to exercise a
    hosted configuration without a secrets file on disk.

    A PRIVATE_KEY that is set but malformed raises PrivateKeyError carrying the same settings without a key, so
    a caller that only reads can carry on read-only and say why signing is off.
    """
    chain, rpc_url, explorer_url, env = network_settings(repo_root, env_file, secrets)
    settings = Settings(
        rpc_url=rpc_url,
        chain_id=chain.chain_id,
        explorer_url=explorer_url,
        proxy=resolve_proxy(repo_root, env, chain.chain_id),
        private_key=None,
        allow_mint=_flag(env.get("ALLOW_MINT"), True),
        chain=chain,
    )
    try:
        key = validate_private_key(env.get("PRIVATE_KEY"))
    except PrivateKeyError as exc:
        exc.settings = settings
        raise
    return _replace(settings, private_key=key)


def main(argv: list[str] | None = None) -> int:
    """`get <field>`: print one setting of the selected chain (CHAIN_ID from the environment or .env, else the
    repo default). `env`: print that chain's network block for a .env file, straight from the registry.
    `chains`: list the registry. For the shell scripts and the runbook; never prints a secret."""
    import argparse

    parser = argparse.ArgumentParser(prog="python3 -m dashboard.config", description=main.__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)
    get = sub.add_parser("get", help="print one field of the selected chain")
    get.add_argument("field", choices=("chain_id", *_CHAIN_FIELDS, "faucet_url", "proxy_address",
                                       "proxy_deploy_block"))
    get.add_argument("--chain-id", help="select this chain instead of CHAIN_ID / the repo default")
    env_cmd = sub.add_parser("env", help="print CHAIN_ID, RPC_URL, VERIFIER_URL, EXPLORER_URL for a .env file")
    env_cmd.add_argument("--chain-id", help="select this chain instead of CHAIN_ID / the repo default")
    sub.add_parser("chains", help="list every registered chain")
    args = parser.parse_args(argv)

    try:
        if args.cmd == "chains":
            default = _default_chain_or_none()
            for cid, c in sorted(CHAINS.items()):
                print(f"{cid}\t{c.name}\t{c.rpc_url}\t{c.explorer_url}{'  (default)' if c is default else ''}")
            return 0
        env = _merged_env(REPO_ROOT, None, {})
        if args.chain_id:
            env["CHAIN_ID"] = args.chain_id
        chain = select_chain(env)
        if args.cmd == "env":
            print(f"# {chain.name}, from dashboard/{CHAINS_FILE.name}\nCHAIN_ID={chain.chain_id}\n"
                  f"RPC_URL={chain.rpc_url}\nVERIFIER=blockscout\nVERIFIER_URL={chain.verifier_url}\n"
                  f"EXPLORER_URL={chain.explorer_url}")
            return 0
        if args.field in ("proxy_address", "proxy_deploy_block"):
            addr, block = _proxy_from_deployment(REPO_ROOT / STATIC_DEPLOYMENT_FILE, chain.chain_id)
            value = addr if args.field == "proxy_address" else block
        else:
            value = getattr(chain, args.field)
    except (ChainSelectionError, ValueError) as exc:
        print(f"dashboard.config: {exc}", file=sys.stderr)
        return 1
    if value is None:
        print(f"dashboard.config: {args.field} is not set for chain {chain.chain_id}", file=sys.stderr)
        return 1
    print(str(value).lower() if isinstance(value, bool) else value)
    return 0


if __name__ == "__main__":
    sys.exit(main())
