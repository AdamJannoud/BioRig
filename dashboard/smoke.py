"""Headless proof that the dashboard's chain path works against the live proxy. Read-only: it reads
getTreeStats, derives and cross-checks the token-bound account, and simulates one mintTree with eth_call.
It never broadcasts.

    .venv/bin/python -m dashboard.smoke [--token 1] [--lat -1.2921 --lng 36.8219]
"""
from __future__ import annotations

import argparse
import sys

from . import h3_nullifier
from .chain import Chain, format_tree_stats
from .config import load_settings


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--token", type=int, default=1)
    ap.add_argument("--lat", type=float, default=-1.2921)
    ap.add_argument("--lng", type=float, default=36.8219)
    ap.add_argument("--dbh", type=int, default=24)
    ap.add_argument("--biomass", type=int, default=312)
    args = ap.parse_args(argv)

    settings = load_settings()
    chain = Chain(settings)
    failures = []

    cid = chain.assert_chain()
    print(f"proxy         {chain.proxy}  (resolved from {settings.proxy.source})")
    print(f"chain id      {cid}")
    print(f"signer        {chain.signer}")
    is_verifier = chain.signer_is_verifier()
    print(f"VERIFIER_ROLE {is_verifier}")
    if not is_verifier:
        failures.append("signer lacks VERIFIER_ROLE")

    print(f"\ngetTreeStats({args.token})")
    stats = chain.get_tree_stats(args.token)
    for k, v in format_tree_stats(stats, chain.is_nullifier_active(stats.spatial_nullifier)):
        print(f"  {k:<17}{v}")

    record = chain.find_mint(args.token)
    tba = chain.check_tba(args.token, record)
    print(f"\nmint tx       {record.tx_hash}  block {record.block_number}")
    print(f"planter       {record.planter}")
    print(f"TBA derived   {tba.derived_offline}   (offline CREATE2)")
    print(f"TBA registry  {tba.registry_account}   (ERC6551Registry.account eth_call)")
    print(f"TBA stored    {tba.stored}   (getTreeStats.tbaAddress)")
    print(f"TBA token()   {tba.bound_token}   supports 0x6faff5f1: {tba.supports_6551}")
    expected_bound = (settings.chain_id, chain.proxy, args.token)
    if not tba.ok:
        failures.append("TBA derivations disagree")
    if tba.bound_token != expected_bound or not tba.supports_6551:
        failures.append(f"TBA bound to {tba.bound_token}, expected {expected_bound}")

    head = chain.w3.eth.block_number
    salt = f"smoke-{head}"
    d = h3_nullifier.derive(args.lat, args.lng, salt)
    print(f"\nH3 cell       {d.cell}  (res {d.resolution}, lat {d.lat}, lng {d.lng})")
    print(f"salt          {salt}")
    print(f"nullifier     {d.nullifier_hex}  ({len(d.nullifier)} bytes)")
    print(f"active        {chain.is_nullifier_active(d.nullifier)}")

    sim = chain.simulate_mint(chain.signer, d.nullifier, args.dbh, args.biomass)
    print(f"\nsimulate mintTree({chain.signer}, {d.nullifier_hex[:12]}…, {args.dbh}, {args.biomass})"
          f" from {sim.sender}")
    if sim.ok:
        print(f"  eth_call OK -> would mint tokenId {sim.token_id}; estimated gas {sim.gas:,}")
    else:
        print(f"  eth_call REVERTED: {sim.error}")
        failures.append(f"mint simulation reverted: {sim.error}")

    # the same nullifier as token #1 must be refused: the anti-double-counting rule, live
    dup = chain.simulate_mint(chain.signer, stats.spatial_nullifier, args.dbh, args.biomass)
    print(f"  reuse of token #{args.token}'s nullifier -> {'OK?!' if dup.ok else dup.error}")
    if dup.ok or dup.error != "NullifierInUse()":
        failures.append("reused nullifier was not rejected with NullifierInUse")

    print("\nno transaction was broadcast")
    if failures:
        print("SMOKE FAILED:\n  " + "\n  ".join(failures), file=sys.stderr)
        return 1
    print("SMOKE OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
