# relay — the BioRig verifier relay

The one process that holds the `VERIFIER_ROLE` key. A planter's client sends a trunk measurement and a GPS fix; the
relay derives the H3 cell, allocates the tree's ordinal in it, derives the nullifier, queues the registration and
signs `mintTree`. The planter never holds CELO and never signs.

This is phases 0–3 of the live-registration spec: the relay exists and is proven locally. The dashboard still has
its own signing path; phase 4 (rewiring `planter_view` to post here and deleting `PRIVATE_KEY`, `ALLOW_MINT`,
`send_mint` and `_register` from `dashboard/`) and phase 5 (a live registration) are separate, reviewed steps.

The HTTP contract is [`docs/relay-api.md`](../docs/relay-api.md).

## Rules it enforces

- **One registration is one tree** (1 row = 1 token). The salt's ordinal is a tree ordinal within the cell.
- **R1** The client sends no nullifier, reference, salt, cell, ordinal or biomass; any of them is refused.
- **R2** `salt = "biorig:v1:" + cell + ":" + ordinal`, the ordinal allocated under the cell's write lock together
  with the insert; `UNIQUE(cell, tree_ordinal)` and `UNIQUE(nullifier)` back it in storage.
- **R3** Occupancy is judged in metres: every active registration in the cell's k-ring (k=2, 19 cells, at 20 m),
  by haversine. Within `COLLISION_RADIUS_M` (20 m) it is the same tree: same planter gets the existing job, another
  planter is refused with the distance and the existing token id.
- **R4** A fix whose accuracy is worse than `MAX_ACCURACY_M` (30 m), or whose coordinates fail a range check, is
  refused, not rounded.
- **R5** At most `MAX_TREES_PER_CELL` (4) active registrations per cell, then `cell_full`; plus a polygon denylist.
  Registration is open (no invite, no human approval before `verified`), so a full cell is refused rather than
  queued for review.

The relay recomputes allometry from DBH itself (`dashboard.allometry`) and only compares a client estimate.

## Layout

| File | What it owns |
| --- | --- |
| `config.py` | the environment, fail-closed: no key → refuse to start; unrecognised `DRY_RUN`/`PAUSED` → refuse |
| `validate.py` | every client field; refusals with codes, never clamps |
| `plot_index.py` | cell derivation, salt allocation under the cell lock, k-ring occupancy, collision, ceiling, denylist |
| `store.py` | SQLite in WAL mode, migrations, the queue queries, sessions and the rate-limit ledger |
| `machine.py` | the four states, attempts, backoff, `next_attempt_at`, the single worker |
| `broadcaster.py` | the chain protocol and its web3 implementation: pre-flight, `isNullifierActive` recovery before any re-broadcast, `find_mint` |
| `service.py` | the route table, auth, limits, health; `http.server` only |
| `__main__.py` | `python -m relay` |
| `seed.py` | the one-time mainnet pilot row |
| `migrations/` | `001_registrations.sql`, `002_sessions_limits.sql` |

It reuses `dashboard.h3_nullifier`, `dashboard.allometry`, `dashboard.config` (chain registry, proxy resolution, key
validation) and `dashboard.chain` (reads and the hardened log walk). `dashboard/__init__.py` is empty and those
modules import Streamlit only inside `hosted_secrets()`, which the relay never calls; a test asserts Streamlit stays
out of `sys.modules`. No runtime dependency is added: the root `requirements.txt` already carries everything.

## Running it

```bash
export RELAY_VERIFIER_KEY=0x...        # the VERIFIER_ROLE key, from the platform's secret store
export RELAY_CHAIN_ID=11142220         # default: dashboard/deployment.json's default chain (42220)
export RELAY_DB=/srv/relay/relay.db    # default relay/var/relay.db (gitignored); never /tmp
export DRY_RUN=1                       # everything up to the pre-flight, nothing signed
.venv/bin/python -m relay --check      # boot assertion only: chain id + hasRole(VERIFIER_ROLE, signer)
.venv/bin/python -m relay              # serve on 127.0.0.1:8787 with one worker
```

Boot refuses (non-zero exit, reason on stderr) when the key is missing or malformed (2), the RPC is another chain or
the signer lacks `VERIFIER_ROLE` or the chain cannot be read (3), or the store belongs to another chain (4).

| Variable | Default | |
| --- | --- | --- |
| `RELAY_VERIFIER_KEY` | — (required) | never logged, never returned |
| `RELAY_ADMIN_TOKEN` | unset → admin surface off | ≥ 32 chars of `[A-Za-z0-9_-]` |
| `RELAY_CHAIN_ID`, `RELAY_RPC_URL`, `PROXY_ADDRESS` | from `dashboard/chains.json` / `deployment.json` | |
| `RELAY_HOST`, `RELAY_PORT` | `127.0.0.1`, `8787` | |
| `DRY_RUN`, `PAUSED`, `TRUST_FORWARDED_FOR` | off | strict on/off |
| `MAX_FEE_GWEI` | 250 | hard cap on `maxFeePerGas` (the pilot paid 200.0011 gwei) |
| `COLLISION_RADIUS_M`, `MAX_ACCURACY_M`, `MAX_TREES_PER_CELL` | 20, 30, 4 | |
| `LIMIT_PER_SESSION`, `LIMIT_PER_IP_HOUR`, `LIMIT_PER_IP_DAY`, `LIMIT_PER_PLANTER_DAY`, `LIMIT_GLOBAL_PER_DAY` | 3, 5, 20, 10, 200 | |
| `SESSIONS_PER_IP_HOUR`, `SESSION_TTL_S`, `PLOT_READS_PER_IP_HOUR` | 4, 86400, 120 | not in the spec's table: the session bootstrap needs them |
| `SESSIONS_GLOBAL_HOUR` | 30 | sessions minted per hour across the whole relay: bounds rotating `X-BioRig-Install-Id` (the per-caller limits count it when sent; see docs/relay-api.md) |
| `FIX_MAX_AGE_S`, `FIX_MAX_FUTURE_S` | 600, 60 | the fix freshness window |
| `BIOMASS_TOLERANCE_REL`, `BIOMASS_TOLERANCE_ABS_KG` | 0.02, 0.5 | client estimate vs the relay's |
| `BACKOFF_S`, `STUCK_AFTER_S` | `2,10,45`, 300 | attempts = len(backoff) + 1 |
| `RELAY_SPECIES` | `unspecified` | the allowlist; allometry uses the dashboard's single wood density |
| `DENYLIST_FILE` | unset | JSON list of `[lat, lng]` polygons |

## Seeding the mainnet pilot

Token 1 on Celo mainnet was minted before the index existed, so the index is seeded from its mint record (cell,
coordinates, salt and nullifier from `tools/demo_facts.json`; token, tx, block, TBA and figures from `DEPLOY.md`):

```bash
.venv/bin/python -m relay.seed --db relay/var/relay.db                        # prints the row, writes nothing
.venv/bin/python -m relay.seed --db relay/var/relay.db --apply-mainnet-pilot  # writes it, once
```

It refuses a store bound to any chain but 42220 and is idempotent.

## Tests

```bash
.venv/bin/python -m pytest relay/tests -q
```

No test touches a network or holds a real key: `tests/conftest.py`'s `FakeBroadcaster` stands in for the chain.
`scripts/verify-demo.sh` step 2 collects this suite with the dashboard's and the tools'.
