"""One-time seed: the Celo mainnet pilot tree (token 1), inserted before the index goes live.

The chain stores the nullifier and not the cell, so the index cannot be rebuilt by re-deriving; the mint record is
the seed. Every value below is read from, or copied verbatim out of, a committed record, named beside it:

- cell, coordinates, resolution, salt and nullifier: tools/demo_facts.json, key "demo_h3" (read at run time, and the
  nullifier re-derived from the cell and salt through dashboard.h3_nullifier as a check).
- token id, planter, tx, block, gas, fee, DBH, biomass, TBA and the mint timestamp: DEPLOY.md, "The first mainnet
  tree" (the mintTree call, its tx line, and the getTreeStats(1) read-back), restated in
  docs/prezenti-proposal.md section 5.2 ("The first Celo mainnet mint").

Nothing here is invented. accuracy_m, species and the relay-computed biomass/CO2e were never recorded for this tree,
so they stay NULL rather than being made up.

    python -m relay.seed --db relay/var/relay.db --apply-mainnet-pilot

It refuses without both flags, refuses a store bound to any chain but 42220, and is idempotent (an existing row with
the pilot's nullifier is left as it is).
"""
from __future__ import annotations

import argparse
import json
import sys
import uuid
from pathlib import Path

from dashboard.config import REPO_ROOT
from dashboard.h3_nullifier import derive

from .store import Registration, Store, StoreError

MAINNET_CHAIN_ID = 42220
DEMO_FACTS = REPO_ROOT / "tools" / "demo_facts.json"

# DEPLOY.md, "The first mainnet tree":
#   cast send "$PROXY" "mintTree(address,bytes32,uint96,uint96)" 0xD314e37F... 0xb7a55a6b...d741 10 20
#   Tx 0x70476c02...97f7, block 78992489, status 0x1, 270,077 gas, 0.054015697 CELO at 200.0011 gwei.
#   getTreeStats(1) -> (10, 20, 1790893247, 0x453e8952..., true, 0xb7a55a6b...d741)
PILOT_TOKEN_ID = 1
PILOT_PLANTER = "0xD314e37FD8538fe66231EE670B74C9428d03feEa"
PILOT_MINT_NULLIFIER = "0xb7a55a6b1b7e4fe0fba76f303772cba7fdf3715d4030e3fcd91ed297c756d741"  # mintTree's 2nd arg
PILOT_DBH_CM = 10
PILOT_BIOMASS_KG = 20
PILOT_TX = "0x70476c02ef1af918a213eec63472e6cdbabcedd50193cdd6a7a89a09527797f7"
PILOT_BLOCK = 78992489
PILOT_GAS_USED = 270077
PILOT_FEE_WEI = 54_015_697_000_000_000  # 0.054015697 CELO
PILOT_TBA = "0x453e89520DB8f374CFCeA95625B99DF5d4F1256A"
PILOT_MINTED_AT = 1790893247  # getTreeStats(1).lastUpdated, set by mintTree to the mint block's timestamp
PILOT_TREE_ORDINAL = 0  # the plan: "insert that row (state minted, plot index 0, salt plot-1 as recorded)"
PILOT_JOB_ID = uuid.uuid5(uuid.NAMESPACE_URL, "biorig:42220:token:1").hex  # deterministic, so re-seeding is a no-op


def pilot_row(facts_path: Path = DEMO_FACTS) -> dict:
    h3f = json.loads(facts_path.read_text())["demo_h3"]
    d = derive(h3f["lat"], h3f["lng"], h3f["salt"], h3f["resolution"])
    if d.cell != h3f["cell"] or d.nullifier_hex != h3f["nullifier"]:
        raise ValueError(f"{facts_path.name} demo_h3 does not re-derive: {d.cell} {d.nullifier_hex}")
    if h3f["nullifier"] != PILOT_MINT_NULLIFIER:
        raise ValueError(f"{facts_path.name} demo_h3 nullifier is not the one DEPLOY.md's mainnet mint carried")
    return {
        "id": PILOT_JOB_ID, "submission_id": None, "session_id": None,
        "nullifier": h3f["nullifier"], "cell": h3f["cell"], "tree_ordinal": PILOT_TREE_ORDINAL,
        "salt": h3f["salt"], "lat": h3f["lat"], "lng": h3f["lng"], "accuracy_m": None,
        "location_source": "record", "fix_captured_at": None, "species": None,
        "dbh_cm": PILOT_DBH_CM, "biomass_kg": None, "co2e_kg": None, "mint_biomass_kg": PILOT_BIOMASS_KG,
        "planter_address": PILOT_PLANTER, "state": "minted", "token_id": PILOT_TOKEN_ID, "tba": PILOT_TBA,
        "tx_hash": PILOT_TX, "block": PILOT_BLOCK, "gas_used": PILOT_GAS_USED, "fee_wei": str(PILOT_FEE_WEI),
        "created_at": PILOT_MINTED_AT, "updated_at": PILOT_MINTED_AT, "minted_at": PILOT_MINTED_AT,
        "decided_by": "seed:DEPLOY.md first mainnet tree",
    }


def seed_pilot(store: Store) -> tuple[Registration, bool]:
    """Insert the pilot row into a mainnet store. Returns (row, inserted)."""
    bound = store.meta("chain_id")
    if bound is None or int(bound) != MAINNET_CHAIN_ID:
        raise StoreError(f"the pilot tree is a chain {MAINNET_CHAIN_ID} record; this store is bound to "
                         f"{bound or 'no chain'}")
    row = pilot_row()
    existing = store.by_nullifier(row["nullifier"])
    if existing is not None:
        return existing, False
    return store.insert(row), True


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m relay.seed", description="seed the mainnet pilot tree")
    parser.add_argument("--db", required=True, type=Path, help="the relay store to seed (no default, on purpose)")
    parser.add_argument("--apply-mainnet-pilot", action="store_true", help="required: actually write the row")
    args = parser.parse_args(argv)
    if not args.apply_mainnet_pilot:
        print("relay.seed: dry by default; pass --apply-mainnet-pilot to write. The row would be:", file=sys.stderr)
        print(json.dumps(pilot_row(), indent=2))
        return 1
    store = Store(args.db)
    if store.meta("chain_id") is None:
        store.bind_chain(MAINNET_CHAIN_ID)
    try:
        row, inserted = seed_pilot(store)
    except StoreError as exc:
        print(f"relay.seed: {exc}", file=sys.stderr)
        return 2
    print(f"{'inserted' if inserted else 'already present'}: token {row.token_id} in cell {row.cell}, "
          f"ordinal {row.tree_ordinal}, job {row.id}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
