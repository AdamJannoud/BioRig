"""Record a real broadcast in dashboard/deployment.json, so the dashboard, the diagram and the checks can find it.

Run after `forge script ... --broadcast` has landed, from the repository root:

    .venv/bin/python scripts/record_deployment.py                     # chain from CHAIN_ID / .env
    .venv/bin/python scripts/record_deployment.py --chain-id 42220 --make-default

Reads broadcast/DeployAll.s.sol/<chain>/run-latest.json (or --broadcast PATH), takes the ERC1967Proxy creation
and its block from it, and refuses anything that does not look like a confirmed broadcast: an artifact for a
different chain, a transaction without a successful receipt (a simulation writes none), or a proxy address with
no code on the chain's RPC. Then adds the chain to the per-chain map without touching the other chains. An
existing entry for the same chain is only replaced with --replace.
"""
from __future__ import annotations

import argparse
import json
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from dashboard.config import (REPO_ROOT, STATIC_DEPLOYMENT_FILE, ChainSelectionError, _merged_env,  # noqa: E402
                              _proxy_from_broadcast, record_deployment, select_chain)


def confirmed_proxy(path: Path, chain_id: int) -> tuple[str, int]:
    """(proxy, block) from a broadcast artifact that really landed on `chain_id`, or ValueError why not."""
    data = json.loads(path.read_text())
    if int(data.get("chain", -1)) != chain_id:
        raise ValueError(f"{path} is for chain {data.get('chain')}, not {chain_id}")
    receipts = {r.get("transactionHash"): r for r in data.get("receipts") or []}
    for tx in data.get("transactions") or []:
        rc = receipts.get(tx.get("hash"))
        if rc is None:
            raise ValueError(f"transaction {tx.get('hash')} has no receipt: this artifact is a simulation, "
                             "or the broadcast did not finish (re-run forge with --resume)")
        if str(rc.get("status")) not in ("0x1", "1"):
            raise ValueError(f"transaction {tx.get('hash')} reverted (status {rc.get('status')})")
    proxy, block = _proxy_from_broadcast(path)
    if block is None:
        raise ValueError("the ERC1967Proxy creation has no block number in its receipt")
    return proxy, block


def code_size(rpc_url: str, address: str) -> int:
    body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "eth_getCode", "params": [address, "latest"]})
    req = urllib.request.Request(rpc_url, body.encode(), {"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=20) as resp:
        result = json.load(resp)["result"]
    return (len(result) - 2) // 2


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--chain-id", help="chain to record (default: CHAIN_ID from the environment or .env)")
    parser.add_argument("--broadcast", type=Path, help="artifact to read (default: DeployAll's run-latest.json)")
    parser.add_argument("--deployment-file", type=Path, default=REPO_ROOT / STATIC_DEPLOYMENT_FILE)
    parser.add_argument("--make-default", action="store_true", help="also make this chain the repo default")
    parser.add_argument("--replace", action="store_true", help="overwrite an existing entry for this chain")
    parser.add_argument("--no-rpc", action="store_true", help="skip the eth_getCode check (offline use only)")
    args = parser.parse_args(argv)

    env = _merged_env(REPO_ROOT, None, {})
    if args.chain_id:
        env["CHAIN_ID"] = args.chain_id
    try:
        chain = select_chain(env)
        path = args.broadcast or REPO_ROOT / "broadcast" / "DeployAll.s.sol" / str(chain.chain_id) / "run-latest.json"
        proxy, block = confirmed_proxy(path, chain.chain_id)
        if not args.no_rpc:
            rpc = env.get("RPC_URL") or chain.rpc_url
            size = code_size(rpc, proxy)
            if size == 0:
                raise ValueError(f"{proxy} has no code on {rpc}; refusing to record a deployment the chain lacks")
            print(f"{proxy} has {size} bytes of code on {rpc}")
        data = record_deployment(args.deployment_file, chain.chain_id, proxy, block,
                                 make_default=args.make_default, replace=args.replace)
    except (ChainSelectionError, ValueError, OSError, json.JSONDecodeError) as exc:
        print(f"record_deployment: {exc}", file=sys.stderr)
        return 1
    print(f"recorded {chain.name} ({chain.chain_id}): proxy {proxy} at block {block} -> {args.deployment_file}")
    print(json.dumps(data, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
