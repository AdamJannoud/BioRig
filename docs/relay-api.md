# BioRig relay — HTTP API contract (v1)

The relay is the only process that holds the `VERIFIER_ROLE` key. It takes a measurement and a GPS fix, derives
the plot identity itself, queues the registration and signs `mintTree`. This document is the contract between the
relay and any client (the dashboard, from phase 4). It matches `ROUTES` in `relay/service.py`;
`relay/tests/test_service.py::test_the_contract_document_matches_the_route_table` fails if an endpoint or an error
code is added on one side only.

**Unit.** One registration is exactly one tree: 1 registration = 1 row = 1 token. The salt's ordinal is the tree's
ordinal within its H3 cell, and the record carries tree fields (species, one DBH, one biomass).

**Open registration.** Anyone may register. There is no invite gate and no human approval before `verified`; the
limits below are the guard.

## Conventions

- Bodies are JSON (`Content-Type: application/json`), UTF-8, at most 16 384 bytes. Responses are always JSON with
  `Cache-Control: no-store`.
- Times are integer Unix seconds (UTC). Addresses are `0x`-prefixed hex; the relay returns them EIP-55 checksummed.
  Nullifiers and hashes are lowercase `0x`-hex.
- Every refusal has the same shape, and carries more fields where the code says so:

  ```json
  {"error": {"code": "accuracy_too_coarse", "message": "fix.accuracy_m: 41 m is worse than ...", "field": "fix.accuracy_m"}}
  ```

- A `429` always carries a `Retry-After` header (seconds) and `error.retry_after_s` with the same value, plus
  `error.limit` naming the limit that refused.
- A refusal happens before a row is created: the table is a record of real attempts, not a log of rejects.

## Auth

| Surface | Credential | How to get it |
| --- | --- | --- |
| `POST /v1/registrations` | `Authorization: Bearer <session_token>` | `POST /v1/sessions`, no credential needed |
| `GET /v1/registrations/{job_id}`, `GET /v1/plots/{cell}`, `GET /healthz` | none | — |
| `/v1/admin/*` | `Authorization: Bearer <RELAY_ADMIN_TOKEN>` | the operator's secret; when unset the admin surface answers `404` |

A session token is the key the per-session limit is counted on. It is 43 URL-safe characters, returned once, stored
by the relay only as its SHA-256, and valid for `SESSION_TTL_S` (24 h). A session is not an identity: it carries no
wallet, no account and no privilege beyond submitting under its own limit. Session creation is itself limited per IP,
so a script cannot mint fresh sessions to dodge the per-session limit.

## Limits

All config-driven; the defaults are the spec's.

| Limit | Default | Counted on | Variable |
| --- | --- | --- | --- |
| per session token | 3 | registrations created under the session, over its lifetime | `LIMIT_PER_SESSION` |
| per IP | 5 / hour, 20 / day | every `POST /v1/registrations` that reaches the limiter (validation refusals included) | `LIMIT_PER_IP_HOUR`, `LIMIT_PER_IP_DAY` |
| per planter address | 10 / day | registrations created for the address | `LIMIT_PER_PLANTER_DAY` |
| per cell | 4 active | non-rejected registrations in the H3 cell; beyond it `cell_full` | `MAX_TREES_PER_CELL` |
| global | 200 / day | mints this relay broadcast in the last 24 h (minted rows, not submissions) | `LIMIT_GLOBAL_PER_DAY` |
| sessions per IP | 4 / hour | `POST /v1/sessions` | `SESSIONS_PER_IP_HOUR` |
| plot reads per IP | 120 / hour | `GET /v1/plots/{cell}` | `PLOT_READS_PER_IP_HOUR` |

The IP is the TCP peer; `X-Forwarded-For` is honoured only with `TRUST_FORWARDED_FOR=1` (behind a proxy you run).
The global cap is enforced twice: intake refuses with `429` once it is reached, and the worker defers any
`verified` job rather than broadcast past it.

## Idempotency

A registration can never become two rows:

1. **Same `submission_id`, same session** — the existing job is returned, `200`, `"outcome": "replayed"`. Nothing
   is re-validated, no limit is consumed. If the same `submission_id` arrives with a different planter or DBH the
   answer is `409 submission_conflict` naming the existing `job_id`.
2. **Same tree** — a fix within `COLLISION_RADIUS_M` (20 m) of an active registration in the cell's k-ring is the
   same tree, whatever cell it lands in. Same planter: the existing job, `200`, `"outcome": "same_tree"`. Another
   planter: `409 collision` with the distance and the existing token id.
3. **Same nullifier** — the nullifier is a pure function of `(cell, tree_ordinal)`, and storage holds
   `UNIQUE(nullifier)` and `UNIQUE(cell, tree_ordinal)`, so a nullifier can be allocated once.
4. **Active on chain, unknown here** — before inserting, the relay asks `isNullifierActive` for the nullifier it
   just allocated. If the chain says active and the store has no row (a lost store, or a mint from outside this
   relay), the mint is recovered with `find_mint`, recorded as a `minted` row, and its state returned
   (`"outcome": "recovered"` for the same planter, `409 collision` for anyone else). Nothing is signed.

The worker applies the same rule to its own retries: before re-broadcasting a `verified` job it asks
`isNullifierActive`; if the mint already happened only the receipt was lost, and the job moves to `minted` without
sending anything.

## The polling path

1. `POST /v1/sessions` → keep `session_token`.
2. `POST /v1/registrations` → `202` with `job.job_id` and `job.state = "submitted"`.
3. Put `job_id` in the page URL (`?job=<id>`) and render from `GET /v1/registrations/{job_id}` on every load: a
   reload mid-flight shows the same job, a reload after the mint shows the token.
4. Poll every 2–5 s while `state` is `submitted` or `verified`; stop at `minted` or `rejected`.

States: `submitted` (row exists, nothing signed) → `verified` (pre-flight `eth_call` passed, payload frozen) →
`minted` (receipt status 1, token id, TBA). `rejected` is terminal with `last_error_code`. A retry is a self-loop on
`verified`: `attempts` counts broadcasts and `next_attempt_at` says when the next one is due (backoff 2 s / 10 s /
45 s, then `broadcast_unconfirmed`).

## Objects

### Job

| Field | Type | Notes |
| --- | --- | --- |
| `job_id` | string, 32 hex | what you poll |
| `submission_id` | string \| null | your correlation id; null on seeded and recovered rows |
| `state` | `"submitted"` \| `"verified"` \| `"minted"` \| `"rejected"` | |
| `cell` | string | H3 resolution-12 index, hex |
| `tree_ordinal` | integer ≥ 0 | the tree's ordinal in its cell |
| `salt` | string | `biorig:v1:<cell>:<tree_ordinal>` (the seeded mainnet pilot keeps `plot-1`) |
| `nullifier` | string, 0x + 64 hex | `keccak256(uint64(cell) ++ utf8(salt))` |
| `planter_address` | string | checksummed; receives the token |
| `tree` | object | `species` string \| null, `dbh_cm` integer, `biomass_kg` number \| null, `co2e_kg` number \| null, `mint_biomass_kg` integer — figures are the relay's own allometry |
| `attempts` | integer | broadcast attempts |
| `next_attempt_at` | integer \| null | when the worker next acts on it |
| `last_error_code` | string \| null | see *Queue codes* |
| `mint` | object \| null | on `minted` only: `token_id` integer, `tba` string, `tx_hash` string, `block` integer — read back from the chain |
| `created_at`, `updated_at` | integer | |
| `verified_at`, `minted_at` | integer \| null | |

Coordinates are personal data: the public job view never carries them. The admin view adds `lat`, `lng`,
`accuracy_m`, `location_source`, `last_error`, `nonce`, `gas_used`, `fee_wei`, `decided_by`, `photo_sha256`,
`client_biomass_kg`, `client_co2e_kg`.

## Endpoints

### POST /v1/sessions

Bootstrap a session token. No body, no credential.

`201`:

```json
{"session_token": "q3V...43 chars", "created_at": 1800000000, "expires_at": 1800086400, "registrations_allowed": 3}
```

Refusals: `429 rate_limited` (`limit: "sessions_per_ip_hour"`).

### POST /v1/registrations

Validate, index, enqueue. Session token required.

Request:

| Field | Type | Rule |
| --- | --- | --- |
| `submission_id` | string | required; 1–64 of `[A-Za-z0-9_-]`; correlation only |
| `planter_address` | string | required; 0x + 40 hex; mixed case must pass EIP-55; not the zero address |
| `fix.lat` | number | required; −90…90; `0,0` refused |
| `fix.lng` | number | required; −180…180 |
| `fix.accuracy_m` | number | required; > 0 and ≤ `MAX_ACCURACY_M` (30) |
| `fix.captured_at` | integer | required; Unix seconds, no older than `FIX_MAX_AGE_S` (600), no more than 60 s ahead |
| `tree.species` | string | required; on the relay's allowlist (`RELAY_SPECIES`, default `unspecified`) |
| `tree.dbh_cm` | integer | required; 2…120 (the planter's slider range) |
| `client_estimate.biomass_kg`, `client_estimate.co2e_kg` | number | optional; compared with the relay's figure, never used |
| `photo_sha256` | string | optional; 64 lowercase hex |

Any other field is `unknown_field`. A **nullifier, reference, salt, cell, ordinal, biomass or token id** at any
level is `forbidden_field`: the relay derives the plot identity and the figures, the client never chooses them.

```json
{"submission_id": "a1b2", "planter_address": "0xD314e37FD8538fe66231EE670B74C9428d03feEa",
 "fix": {"lat": -1.2903, "lng": 36.8219, "accuracy_m": 8, "captured_at": 1800000000},
 "tree": {"species": "unspecified", "dbh_cm": 10},
 "client_estimate": {"biomass_kg": 19.9}}
```

Responses:

| Status | Body | When |
| --- | --- | --- |
| `202` | `{"job": Job, "outcome": "created"}` | a new tree, state `submitted` |
| `200` | `{"job": Job, "outcome": "replayed"}` | same session and `submission_id` |
| `200` | `{"job": Job, "outcome": "same_tree", "distance_m": number}` | same planter within the collision radius |
| `200` | `{"job": Job, "outcome": "recovered", "distance_m": number}` | allocated nullifier already active on chain, recovered |
| `409` | `collision` with `distance_m`, `collision_radius_m`, `existing: {cell, tree_ordinal, state, token_id}` | another planter's tree within the radius |

Refusals: `400 invalid_json`, `invalid_field`, `missing_field`, `unknown_field`, `forbidden_field`;
`401 session_required`, `session_invalid`, `session_expired`; `409 submission_conflict`, `collision`;
`415 unsupported_media_type`; `422 out_of_range`, `accuracy_too_coarse`, `fix_stale`, `fix_in_future`,
`species_not_allowed`, `dbh_out_of_bounds`, `estimate_mismatch`, `denylisted_area`, `cell_full`;
`429 rate_limited` (`per_ip_hour`, `per_ip_day`, `per_session`, `per_planter_day`, `global_per_day`);
`503 chain_unavailable`, `recovery_pending`, `index_inconsistent`.

### GET /v1/registrations/{job_id}

The job, for the reload path. No credential: the 128-bit job id is the capability.

`200 {"job": Job}`. Refusals: `404 job_not_found`.

### GET /v1/plots/{cell}

Occupancy for the pre-check, so a planter is told before measuring that the plot is taken. `{cell}` is a
resolution-12 H3 index in hex.

`200`:

```json
{"cell": "8c7a6e42ca207ff", "resolution": 12, "active": 1, "max_trees_per_cell": 4, "full": false,
 "neighbourhood_active": 1, "collision_radius_m": 20.0,
 "trees": [{"tree_ordinal": 0, "state": "minted", "token_id": 1}]}
```

`neighbourhood_active` counts active registrations in the cell's k-ring, the set the collision test searches.
Refusals: `400 invalid_cell`; `429 rate_limited` (`plot_reads_per_ip_hour`).

### GET /healthz

Liveness plus the signer's role. `200` while the signer holds `VERIFIER_ROLE`, `503` once a re-check (at most every
60 s) finds it does not.

```json
{"status": "ok", "chain_id": 42220, "proxy": "0x04db...4e64", "signer": "0x...", "signer_is_verifier": true,
 "role_checked_at": 1800000000, "dry_run": false, "paused": false,
 "queue": {"submitted": 0, "verified": 0, "minted": 1, "rejected": 0},
 "oldest_verified_age_s": null, "stuck": 0, "mints_24h": 0, "global_per_day": 200,
 "spend_24h_wei": "0", "schema_version": 2}
```

`status` is `degraded` when any job has sat in `verified` longer than `STUCK_AFTER_S` (300 s) — the alert that
matters — or the role check failed.

### GET /v1/admin/jobs

Admin token. Query: `state` (one of the four) or `stuck=1`. `200 {"jobs": [Job + admin fields]}`.
Refusals: `400 invalid_field`, `401 admin_required`, `404 not_found` (admin disabled).

### POST /v1/admin/jobs/{job_id}/reject

Admin token. Body `{"reason": "1-200 characters"}`. Moves a `submitted` or never-broadcast `verified` job to
`rejected` with `last_error_code: "operator_rejected"`, `decided_by: "admin"`. A job with `attempts > 0` is
refused `409 broadcast_in_history`: something was sent, so only the worker, which re-checks the chain, may end it.
Refusals: `400 invalid_field`, `401 admin_required`, `404 job_not_found`, `409 invalid_transition`,
`broadcast_in_history`.

### POST /v1/admin/jobs/{job_id}/retry

Admin token. Makes a `submitted` or `verified` job due now (it does not reset `attempts`). `200 {"job": ...}`.
Refusals: `401 admin_required`, `404 job_not_found`, `409 invalid_transition`.

### POST /v1/admin/pause

Admin token. The worker stops taking work (persisted in the store, survives a restart). Intake stays open; jobs wait
in `submitted`. `200 {"paused": true}`. The contract's own pause is the separate, on-chain stop.

### POST /v1/admin/resume

Admin token. Clears the runtime pause. `200 {"paused": bool, "paused_by_env": bool}` — `PAUSED=1` in the
environment still holds the worker until the process is restarted without it.

## Error codes

| Status | Code | Reason |
| --- | --- | --- |
| 400 | `invalid_json` | body missing or not JSON |
| 400 | `invalid_field` | a field has the wrong type or format (`error.field` names it) |
| 400 | `missing_field` | a required field is absent |
| 400 | `unknown_field` | a field the contract does not define |
| 400 | `forbidden_field` | the client sent a nullifier, reference, salt, cell, ordinal, biomass or token id |
| 400 | `invalid_cell` | not a resolution-12 H3 cell |
| 401 | `session_required` | no bearer token on `POST /v1/registrations` |
| 401 | `session_invalid` | unknown session token |
| 401 | `session_expired` | the session outlived `SESSION_TTL_S` |
| 401 | `admin_required` | missing or wrong admin token |
| 404 | `not_found` | no such endpoint (also: admin surface disabled) |
| 404 | `job_not_found` | no job with this id |
| 405 | `method_not_allowed` | known path, other method; `Allow` header lists the right one |
| 409 | `collision` | another planter's tree within `COLLISION_RADIUS_M` |
| 409 | `submission_conflict` | a `submission_id` reused for a different registration |
| 409 | `invalid_transition` | an admin action on a job in a state it does not apply to |
| 409 | `broadcast_in_history` | admin reject of a job that has been broadcast |
| 413 | `body_too_large` | body over 16 384 bytes |
| 415 | `unsupported_media_type` | body not `application/json` |
| 422 | `out_of_range` | coordinates or accuracy outside their range |
| 422 | `accuracy_too_coarse` | `fix.accuracy_m` worse than `MAX_ACCURACY_M`; refused, not rounded |
| 422 | `fix_stale` | the fix is older than `FIX_MAX_AGE_S` |
| 422 | `fix_in_future` | the fix is timestamped ahead of the relay's clock |
| 422 | `species_not_allowed` | `tree.species` not on the allowlist (`error.allowed` lists it) |
| 422 | `dbh_out_of_bounds` | `tree.dbh_cm` outside 2–120 |
| 422 | `estimate_mismatch` | the client's estimate disagrees with the relay's beyond tolerance: a stale or tampered client |
| 422 | `denylisted_area` | the fix is inside an excluded polygon |
| 422 | `cell_full` | the cell already holds `MAX_TREES_PER_CELL` active registrations |
| 429 | `rate_limited` | a limit refused; `error.limit` names it, `Retry-After` says when |
| 500 | `internal` | a bug; the request may be retried with the same `submission_id` |
| 503 | `chain_unavailable` | the chain could not be asked whether the plot is taken |
| 503 | `recovery_pending` | the allocated nullifier is active on chain but its mint record is not readable yet |
| 503 | `index_inconsistent` | the allocator found a row it should not have; nothing was written |

### Queue codes (`job.last_error_code`)

| Code | State | Meaning |
| --- | --- | --- |
| `chain_unavailable` | submitted / verified | a chain read failed; retried after backoff |
| `send_failed`, `receipt_timeout`, `receipt_unreadable`, `reverted_on_chain`, `no_mint_event`, `fee_above_cap` | verified | a broadcast attempt that did not end in a confirmed receipt; retried after backoff, `isNullifierActive` checked first |
| `receipt_unrecovered` | verified | the nullifier is active but its log was not found yet; asked again |
| `tx_pending` | verified | budget spent, but an earlier send's nonce has not settled, so it could still mine |
| `dry_run` | verified | `DRY_RUN=1`: pre-flight passed, nothing signed |
| `daily_cap` | verified | the global cap is reached; deferred until the oldest mint ages out |
| `preflight_revert` | rejected | the `eth_call` reverted (`last_error` carries the decoded reason) |
| `broadcast_unconfirmed` | rejected | the retry budget is spent with no confirmed mint |
| `nullifier_taken` | rejected | the nullifier is active for another planter |
| `operator_rejected` | rejected | an operator rejected it before anything was sent |
