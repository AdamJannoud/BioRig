# BioRig — Project Milestone and Roadmap Report

**Project:** BioRig — mobile-first dMRV and proof-of-growth infrastructure on Celo
**Owner, author and sole deployer:** Adam Jannoud (AdamJannoud)
**Repository:** `AdamJannoud/BioRig`, public — audited at `f6f2045`, the tip as it stood when the audit ran; commits have landed since, all in the carrier record, the gate or the documentation (see the delta note below), and this edition is re-attested against the head it carries. Read the live head with `git ls-remote origin refs/heads/main`; this edition deliberately does not pin it
**Networks:** Celo mainnet (chain id 42220) — production; Celo Sepolia (11142220) — testnet
**Report date:** 3 October 2026 (refreshes the 2 October 2026 edition)
**Scope:** complete project audit, live verification sweep, and forward roadmap

**Identifiers:** commit hashes in this edition were re-pointed on 8 October 2026 to the history produced by that day's repo-wide identity normalisation — hashes and identity fields changed; trees, subjects and dates did not. Counts and command outputs are the capture they were recorded from, and Section 3.3 records the normalisation itself.

> **Basis of this report.** This is the 2 October 2026 report carried forward and re-audited at `f6f2045`.
> Every figure below was re-read on 3 October 2026 — chain state over RPC against two public Celo
> endpoints, repository state over git and the remote, and every suite, check script and gate executed in
> a checkout of that commit with no tracked changes. Nothing is carried over from the 2 October text
> unless it was re-derived here, and where a claim could not be re-derived it says so. The re-audit found
> statements in the 2 October edition that were wrong when they were made — most materially, the git
> history does carry co-author trailers, and the proxy and account code sizes were mis-stated — and each
> is corrected in place and set out in Section 3.9.
>
> **Delta since the audit.** Nine commits landed between `f6f2045` and `ed14bfa`, the head when this
> note was written, and none of them touches the contract, the deployment scripts or any on-chain
> state: `575e4d9` (the milestone report docx, the mainnet deployment plan and `FINDINGS.md` become
> carriers), `33ac692` (the doc-path allowlist), `083e74a` (the two demo videos and the contract
> source doc become carriers — thirteen in all), `b3ec3f5` (step 7 refuses a short or
> duplicate-padded carrier record), `a95dcf4` (the branding sweep, which changed `.gitignore`,
> `docs/relay-api.md` and `relay/tests/test_edge.py`, recorded in Section 3.9), `3226bf1` (this
> document re-pointed structurally), `5fd10ff` (this note and the deployment plan's delta list
> corrected), `6902d7c` (the tree-diameter slider's thumb pinned to its value, dashboard only) and
> `ed14bfa` (that pin scoped to the widget, so both thumb markers agree). The range is bounded at
> both ends so it cannot go stale: commits after `ed14bfa` are not counted here. Read the live head
> with `git ls-remote origin refs/heads/main`. This edition states the audit as it was run at
> `f6f2045` and attests the carrier record at the head.

---

## 1. Executive summary

### 1.1 Where the project stands

BioRig is live on Celo mainnet and has moved its first real tree. The core contract is an upgradeable
(UUPS) ERC-721 in which one token is one planted, monitored tree; every mint carries a 32-byte spatial
nullifier so a plot cannot be registered twice, and every tree gets an ERC-6551 token-bound account
created through the canonical registry. The deployment, the migration of administration to a Safe
multisig, the separation of the minting role from custody, and the first pilot mint are all done on
chain and recorded in the repository. None of that on-chain state has moved since 2 October: the
contract still holds exactly one tree, and the roles, the Safe and the buffer-pool address read back
exactly as they did.

What moved between 2 and 3 October is the path a tree takes to reach the chain. Thirty-seven commits
added a registration relay (`relay/`) — the one process meant to hold the minting key, which derives a
plot's identity itself and signs `mintTree` — and an Android MRV app (`mobile/android`) that walks a
planter through a three-step registration and queues it on the phone until there is signal. A debug
build of the app is published to reviewers. The dashboard gained a Home landing page and a full restyle,
and the release process gained three gates: a clean-clone proof on every push to `main`, a carrier gate
that holds every published copy (the proposal, the architecture diagram in three forms, the APK) to the
source it was made from, and a documentation sweep that fails on any path, command, port or variable the
docs name but the tree does not back.

The project is therefore past the "does it work" stage for the Alpha v1 pilot, and the registration path
for the next trees now exists in code. The open work is the roadmap: put the relay into live service and
move from one tree to many, put real measurement data behind `dbh` and `biomass` instead of the pilot's
placeholder values, finish the operating console, and automate the reward flows that currently exist as
design.

### 1.2 The live mainnet deployment

Read over RPC at block `79125988` on 3 October 2026 (block time 11:25:46 UTC, gas price 202.5 gwei at
read time), and cross-read at block `79126079` on a second public endpoint with identical results:

| Item | Value | Verified how |
| --- | --- | --- |
| Chain id | `42220` (Celo mainnet) | `cast chain-id` |
| ERC1967Proxy — the address to use | `0x04Db169dDF8AbB80943161C01B2a71DC40384E64` | proxy code 163 bytes |
| BioRigCoreV5 (implementation) | `0xdb3a450b85D48E6e6552dB2b32aD75a7ac590c60` | ERC-1967 implementation slot |
| ERC-6551 account implementation | `0x65D18C960170ca2B4936c62945bA0e827e5cCd2B` | embedded in the token-bound account's own code |
| ERC-6551 registry (canonical) | `0x000000006551c19487814612e58FE06813775758` | reused, not deployed |
| Paused | `false` | `paused()` |

The proxy holds 163 bytes of code (the 2 October edition said 139; see Section 3.9) and its
implementation slot resolves to the deployed `BioRigCoreV5`, so the live address a user interacts with
is the proxy and its logic is upgradeable.

### 1.3 Who holds what

Read with `hasRole` on the proxy, address by address, on 3 October 2026:

| Holder | `DEFAULT_ADMIN_ROLE` | `UPGRADER_ROLE` | `VERIFIER_ROLE` |
| --- | --- | --- | --- |
| Celo Safe `0x3B36b3446fCB0729B0046520156933E56352D551` | **true** | **true** | false |
| Deployer hot key `0x1DB0084Db70bF8D0E06c1785D693Fc6a95317890` | false | false | **true** |
| Safe owner EOA `0xD314e37FD8538fe66231EE670B74C9428d03feEa` | false | false | false |

This is the mode-B architecture agreed on 1 October 2026 and it is what is actually on chain:

- **Custody of the contract** (upgrade and role administration) sits with the Safe. The Safe is 1-of-1
  with `threshold = 1`, its sole owner is the plain EOA `0xD314e37FD8538fe66231EE670B74C9428d03feEa`,
  its `nonce` is 1 after the owner swap, and the deployer hot key is not an owner — so the key that
  sends transactions cannot upgrade the contract or grant roles.
- **Minting** stays with the deployer hot key, because there is no dedicated verifier key yet. This is
  the deliberate compromise in mode B. The Safe holds `DEFAULT_ADMIN_ROLE`, so it can grant
  `VERIFIER_ROLE` to a dedicated key and revoke it from the deployer at any time without another
  handover. The relay added since 2 October is built to be the one holder of that role; on mainnet today
  no address but the deployer holds it, so a relay minting on mainnet would sign with the deployer key
  until the Safe grants the role to a key of its own (Section 4.3).
- The hot key is also still the `bufferPool` address (`bufferPool()` returns it), which is the
  recipient of the 20% buffer-pool split once that flow is implemented. It is an address, not a role.

### 1.4 The first mainnet tree

| Item | Value |
| --- | --- |
| Token | `1` — exactly one tree exists; `getTreeStats(2)` reverts `InvalidTree` |
| Owner | `0xD314e37FD8538fe66231EE670B74C9428d03feEa` |
| Mint transaction | `0x70476c02ef1af918a213eec63472e6cdbabcedd50193cdd6a7a89a09527797f7` |
| Block | `78992489` |
| Gas | 270,077 — 0.054015697 CELO at 200.0011 gwei |
| Stats | dbh `10`, biomass `20`, timestamp `1790893247`, alive `true` |
| Token-bound account | `0x453e89520DB8f374CFCeA95625B99DF5d4F1256A` |
| Nullifier (H3-derived) | `0xb7a55a6b1b7e4fe0fba76f303772cba7fdf3715d4030e3fcd91ed297c756d741` — active |

The token, owner, stats, account and nullifier were read live; the transaction, block and gas were
re-read from the transaction's receipt (Section 5.3). The tree is minted but its `dbh` and `biomass` are
the pilot's placeholder values (10 and 20), not measurements. Putting real data behind them is roadmap
phase B, and this report does not describe the pilot tree as more than it is.

### 1.5 Verification status

Re-run in a checkout of `f6f2045` with no tracked changes, on 3 October 2026:

| Check | Result |
| --- | --- |
| `forge test` | 181 tests passed, 0 failed, 17 suites, 11.02 s |
| `pytest dashboard tools relay` | 440 passed, 141.39 s |
| `pytest dashboard tools relay --chain-id 42220` | 412 passed, 130.69 s |
| Android `:core:test` (JVM, no SDK) | 49 tests passed, build successful, plus its three cross-checks against the repository's Python |
| `scripts/verify-demo.sh` (acceptance gate, ten steps) | exit 0, `ALL DEMO CHECKS PASSED` — the third run of the day; the first two failures are explained in Section 3.7 |
| Carrier gate, `tools/check_carriers.py` | all seven published carriers match their recorded sources; three local copies match the record byte for byte |
| Live chain read-back | all addresses, roles and token state above agree with `dashboard/deployment.json`, the broadcast records and the documents |

The acceptance gate is the single command that ties the pieces together: it checks the source tree is
untouched, runs the unit tests (now including the relay's), reads the live chain, drives a real browser
against the dashboard, runs both mainnet fork rehearsals, re-renders the explainer video, asserts the
roadmap label is in the rendered pixels, checks no secret is committed, holds the published carriers to
their source and sweeps the documents for anything they name that does not exist.


## 2. Comprehensive chronological record

Dates and times are UTC. Commit subjects are quoted from the repository; hashes are the current
(post-rewrite) ones. The history was rewritten once, on 1 October 2026, to set every commit's author
and committer to Adam Jannoud with content untouched, so a hash quoted in an older document may no
longer resolve — the repository itself is the record. Every hash quoted in Sections 2.1 to 2.8 was
re-resolved for this refresh and carries the time shown.

### 2.1 Repository origin — 25 to 27 September 2026

| Date | Commit | What it was |
| --- | --- | --- |
| 25 Sep 15:27 | `545a1b6` | Initial commit |
| 25 Sep 15:29 | `d2d5f29` | Source upload — `BioRigV3.sol` and the first architecture raster |
| 26 Sep 15:14 | `88479ec` | System architecture diagram added |
| 26 Sep 15:32 | `a7c49b0` | `BioRigCoreV4` upgraded to `BioRigCoreV6` |
| 27 Sep 17:37 | `ffa5826` | `BioRigV3` refactored with updated imports |

### 2.2 Baseline, independent audit and hardening — 30 September 2026

The audited contract arrived as `BioRigCoreV5`. The first commit of the working round keeps the
received source verbatim plus a pristine .orig copy, which is what makes every later claim about the
contract checkable against its own starting point.

| Time | Commit | What it was |
| --- | --- | --- |
| 14:58 | `98517fc` | Baseline: `BioRigCoreV5` as received, plus pristine .orig copy |
| 15:13 | `77fd34c` | Foundry suite added; defect fixed — `mintTree` accepted `address(0)` for the token-bound account |
| 15:15 | `0d5c478` | `FINDINGS.md`; a vacuity-guard `afterInvariant` that misfired on shrunk sequences dropped |
| 15:18 | `18d15f9` | Independent reproduction of hypothesis H1 against the verbatim original |
| 17:35–20:14 | `41e926b`, `27d086c`, `6380d2a`, `a50f65e` | ERC-6551 support, hardened contract, suite and audit findings |
| 19:20–23:09 | `3896f87`, `37e8852`, `b3b4358`, `e88cf89`, `8bd7866`, `e14eab7`, `ad3b94e` | Celo Sepolia deployment tooling: one-command `DeployAll` through the canonical registry, executed deployment recorded, explorer verification pipeline and its runbook |
| 21:23 | `2a5490b` | Issue I-6 closed: settable `_baseTokenURI` and a `_baseURI()` override |
| 21:35–21:52 | `69a8caf`, `7ea558e`, `db52814`, `97174d5` | Demo dashboard (Streamlit, `web3.py`, server-side verifier signing, H3 nullifier, TBA cross-check) and the 90-second explainer generator; `verify-demo.sh` introduced, with a pixel-level assertion that the roadmap label is burned into the rendered frame |
| 22:19–23:50 | `d3135cf`, `fee46b9`, `d56b8b5`, `7911216`, `2f37847`, `3b372a1` | Dashboard made deployable on a free public host; reconciliation with the remote; architecture diagram v5 generated from the deployment record |

**Outcome of the round:** the suite grew from the received state to a full Foundry suite with an
independent reproduction of the original defect, and the contract was deployed and verified on Celo
Sepolia in block `37511856` — four contracts, the canonical ERC-6551 registry reused rather than
deployed.

### 2.3 Chain-agnostic refactor — 1 October 2026, 00:00–01:40

The repository had Celo Sepolia literals in executable read paths. The refactor moved chain
configuration to one source of truth (`dashboard/chains.json` plus a multi-chain
`dashboard/deployment.json`) so every tracked file works against both chains.

| Time | Commit | What it was |
| --- | --- | --- |
| 00:09–00:27 | `58392bb`, `f65f7ba`, `d7faadc` | Pre-deployment claims the live deployment had made false removed; `FINDINGS.md` and the nullifier description corrected |
| 01:03–01:12 | `c4470c8`, `69f22a3`, `d834355` | One per-chain registry; diagram and dashboard render chain name and registry from config; check scripts take expected chain and proxy from configuration |
| 01:18–01:26 | `90e98ea`, `0c99fe3`, `e623b79`, `43a33f5`, `060e441`, `e49caa6`, `add1b1b` | `HardenMainnetAdmin` and a chain-aware fork rehearsal; RPC and explorer URLs belong to the layer that chose the chain; `.env.example` carries both chains; `DEPLOY.md` gains the Celo mainnet runbook |
| 01:33–01:36 | `074f1f7`, `a404bc6` | `RPC_URL` / `EXPLORER_URL` overrides and explorer links resolved from `chains.json` |

### 2.4 Celo mainnet broadcast — 1 October 2026, 06:37

Executed by Adam Jannoud from the deployer key, after a full simulation on the live chain. Re-read for
this refresh from the four receipts named in `broadcast/DeployAll.s.sol/42220/run-latest.json`:

| Item | Value |
| --- | --- |
| Transactions | 4 (account implementation, core implementation, proxy, `grantRole`) — no CREATE2, the canonical registry was reused |
| Block | `78935900`, block time 06:37:38 |
| Gas | 4,015,198 at 200.0011 gwei |
| Cost | **0.803044017 CELO** |
| Receipts | every one status `0x1` |

All four contracts report `is_verified: true` when read back from the explorer's v2 API on 3 October
2026, and the explorer flags each of the four as a partial match (`is_partially_verified: true`). The 2
October edition recorded the verification times (06:38:11Z to 06:44:13Z) and which source each contract
was matched from; those details sit in the explorer's history and were not re-derived here.

The `.env.mainnet.example` template was added at 07:20 with the 42220 network block taken from
`dashboard/chains.json`, plus a guard test that fails if the template and the registry disagree or if
a variable a deploy script requires is missing.

### 2.5 Custody: the Safe, the owner swap, and the role handover — 1 October 2026

This is the part of the architecture that matters most for a grant reviewer, because it is the
difference between a demo contract and one whose upgrade path is not a hot key.

**Why the Safe needed a swap first.** A Safe was supplied on 1 October with the deployer hot key as its
**sole owner**. Handing admin to it would have left the pen in the same hand, and the handover script's
own preflight refuses a `NEW_ADMIN` Safe the deployer can sign for — including through a nested Safe.
So the Safe's owner was moved first, in one Safe transaction, to a plain EOA the hot key does not
control.

| Step | Time | Result |
| --- | --- | --- |
| 7a — Safe owner swap (`script/SafeOwnerSwap.s.sol`) | 1 Oct 22:03:35, block `78991457` | tx `0x7a99f8092aa924018bab62ab4b0362c9d291376fc96065f614d44a3712288012`, 105,580 gas, 0.021116106 CELO, carrying `swapOwner(0x1, 0x1DB0084Db70bF8D0E06c1785D693Fc6a95317890, 0xD314e37FD8538fe66231EE670B74C9428d03feEa)` |
| 7b — role handover, mode B (`script/HardenMainnetAdmin.s.sol`) | 1 Oct 22:03:51–22:04:00, blocks `78991473`–`78991482` | 4 transactions, 172,420 gas, 0.034484189 CELO |

The times are the blocks' own timestamps, read for this refresh; the 2 October edition gave the
handover as "~21:40", which the chain does not bear out. Read back from the chain after both, and
re-read for this report: the Safe's owners are exactly
`[0xD314e37FD8538fe66231EE670B74C9428d03feEa]`, threshold `1`, `nonce` `1`, and the deployer key is no
longer an owner; `DEFAULT_ADMIN_ROLE` and `UPGRADER_ROLE` sit with the Safe; `VERIFIER_ROLE` stays with
the deployer. Five transactions in total, 278,000 gas, 0.055600295 CELO at 200.001 gwei.

**Mode B, stated plainly.** A dedicated server-side verifier key with no other privileges is the
better end state and is what the script prefers. It does not exist yet, so the approved choice was
that the hot key keeps minting (`VERIFIER_ROLE`, which also carries tree updates and
`reportMortality`) and gives up pause, upgrade and role administration. The Safe can grant
`VERIFIER_ROLE` to a dedicated key and revoke it from the deployer at any time without another
handover. That is the residual risk of this architecture, and it is a chosen one, not an oversight.

Both operations were rehearsed against a fork of live mainnet before anything was broadcast, and both
rehearsals are now steps of the acceptance gate, so they cannot go dead unnoticed again.

### 2.6 The first mainnet tree — 1 October 2026

| Item | Value |
| --- | --- |
| Function | `mintTree(address,bytes32,uint96,uint96)` from the verifier key |
| Transaction | `0x70476c02ef1af918a213eec63472e6cdbabcedd50193cdd6a7a89a09527797f7` |
| Block | `78992489` (22:20:47), gas 270,077, cost 0.054015697 CELO |
| Token | `1`, owner `0xD314e37FD8538fe66231EE670B74C9428d03feEa` |
| Stats | dbh `10`, biomass `20`, timestamp `1790893247`, alive `true` |
| Nullifier | `0xb7a55a6b1b7e4fe0fba76f303772cba7fdf3715d4030e3fcd91ed297c756d741`, the production H3 derivation, now active |
| Token-bound account | `0x453e89520DB8f374CFCeA95625B99DF5d4F1256A` |

The mint is the point at which the whole stack stops being a deployment and starts being a product:
the pilot tree's token-bound account was created through the canonical ERC-6551 registry, and its
nullifier exercises the documented H3 pipeline rather than the bare-salt shortcut the Sepolia demo
tree used. The nullifier is also recorded as active, so the same plot cannot be minted twice.

Three documents still claimed mainnet held no trees; all were corrected in the same commit that
recorded the mint.

### 2.7 Dashboard pointed at mainnet, and the hosted demo — 1 to 2 October 2026

| Time | Commit | What it was |
| --- | --- | --- |
| 1 Oct 22:44 | `c1eb9dd` | Celo mainnet became the default chain the dashboard and the architecture diagram render |
| 1 Oct 23:58 | `8e09d47` | A malformed `PRIVATE_KEY` no longer blanks the read-only page (real defect found while verifying the clean render) |
| 2 Oct 00:39 | `e87a340` | The dashboard UI check derives its simulation verdict from chain state instead of pinning a pre-mint page state |
| 2 Oct 00:48 | `2140ee3` | The dashboard's own test asserts against the live rule rather than a pre-mint world |

The hosted demo at `biorigdemo.streamlit.app` was re-opened anonymously in a real browser for this
refresh. It serves the 3 October Home page on Celo mainnet: the page title names the Celo mainnet demo,
and its live strip shows network `Celo · 42220`, one tree registered, the pilot registration's 0.054
CELO and the proxy `0x04Db…84E64`.

### 2.8 Gate integrity and the fork rehearsals — 2 October 2026, 00:39–02:01

The mainnet fork rehearsal harnesses had been dead since the swap and handover they assert against
actually happened, because they forked the tip while asserting the pre-operation world. Two commits
fixed the pin, and then a deeper fix removed the need for one.

| Time | Commit | What it was |
| --- | --- | --- |
| 2 Oct 01:07 | `5d04f71` | Sweep of pins to the pre-operation chain state; harnesses now fail on the real cause |
| 2 Oct 01:09 | `2cd34da` | An exported `FORK_URL` wins over the chain registry |
| 2 Oct 01:30 | `3b9585e` | **Tip-fork reconstruction**: both harnesses fork the current tip and rebuild the pre-operation state on the fork by inverting the executed transactions read out of the committed broadcast records, so no archive endpoint is needed |
| 2 Oct 01:56 | `598c017` | Both rehearsals became step 4b of `verify-demo.sh`; two scripts tracked non-executable were fixed |
| 2 Oct 02:01 | `9a4815f` | The undeclared `cv2` dependency of gate step 5b declared |

The significance is that a dead rehearsal now fails the acceptance gate rather than silently passing.
Before this work, nothing ran the rehearsals automatically, which is precisely how both went dead
unnoticed.

### 2.9 Audit and the 2 October report — 2 October 2026

The 2 October audit was run against `main` at `9a4815f`, tree clean, remote head equal to local head.
It found one documentation defect and one cosmetic residual. The defect — `README.md` naming a
`BUFFER_POOL` role the contract does not define — was fixed and pushed as `b98726d` (02:26), which was
the state that edition described. The fix still holds at `f6f2045`: `README.md` says the contract
defines no `BUFFER_POOL` role.

### 2.10 Since the 2 October report — 2 October 14:46 to 3 October 11:04

Thirty-seven commits landed on `main` between `b98726d` and the audited tip `f6f2045`, touching 166 files
(18,093 lines added, 346 removed). None of them touches the deployed contract or the chain: `src/` is
unchanged, the one Foundry addition is `test/PrivateKeyEnv.t.sol` for the deploy scripts' key loader
(`script/PrivateKeyEnv.sol`, from `2ad393d`), the contract still holds one tree, and every role reads back
as it did.
What they add is the registration path for the next trees, the reviewer-facing artifacts, and the gates
that keep both honest. They group into six threads.

**Brand and the planter flow — 2 October afternoon.**

| Time | Commit | What it was |
| --- | --- | --- |
| 2 Oct 14:46–14:53 | `2ffd6c4`, `95a391f` | Brand kit (brandmark, lockup, favicons from one geometry); the mark on the architecture diagram and the lockup on the proposal cover and running header |
| 2 Oct 15:01–15:41 | `0e0e3f7`, `0aaa293`, `0473ef8`, `32e45bf` | Allometric biomass (`dashboard/allometry.py`), one wording module, browser geolocation; the three-step planter flow becomes the default view, with the operator panel kept whole as a separate view |
| 2 Oct 15:59–16:30 | `8f2ab60`, `28c7339` | The mint finder confirms empty log answers from the public RPC; the fork rehearsals take their receipts from the committed records rather than a node's memory |

**The registration relay — 2 October evening, put behind a public edge on 3 October.** `relay/` is the
one process meant to hold `VERIFIER_ROLE`. A client sends a trunk measurement and a GPS fix, never a
nullifier, salt, cell or biomass; the relay derives the H3 cell, allocates the tree's ordinal under the
cell's write lock, derives the nullifier, recomputes biomass itself, queues the registration and signs
`mintTree`. Its HTTP contract is `docs/relay-api.md` (contract v1).

| Time | Commit | What it was |
| --- | --- | --- |
| 2 Oct 17:42–17:46 | `1426a12`, `7190055` | Config, SQLite store, plot index, state machine, broadcaster and service (phases 0–3 of the live-registration spec); the API contract and README; gate step 2 collects the relay suite |
| 3 Oct 07:14 | `2a20c3b` | Behind the platform edge: the relay reads the renamed `X-Sandbox-Forwarded-Authorization` header, decodes chunked bodies and closes a connection whose body it did not read — before this the deployed relay saw no credential (401) and an empty body (400) |
| 3 Oct 07:26 | `9ee6ff4` | Rate limits keyed on the device: the four per-caller limits count the app's `X-BioRig-Install-Id` (32 hex) when present and the caller's address otherwise, and a relay-wide ceiling of 30 new sessions an hour (`SESSIONS_GLOBAL_HOUR`) bounds what clearing the app's data for a fresh id can buy |
| 3 Oct 07:37 | `0c4c640` | The deployed relay's store, `relay/var-public/`, is git-ignored, so a live SQLite queue holding planter addresses cannot be committed by a blanket `git add` |

The relay is deployed at a public HTTPS address behind that edge, as the commit messages of `2a20c3b`
and `0c4c640` and the comment beside `relay/var-public/` in `.gitignore` record. **That address is not
recorded anywhere in the tree** and is not baked into the published APK, so this report cannot re-derive it and
does not name it; the reviewer should take it from the deployment record held outside the repository.
For the same reason it cannot be re-derived here whether the deployed instance runs in `DRY_RUN` or
against which chain. What can be re-derived is that it has minted nothing on mainnet: the contract still
holds exactly one tree. The relay's own README states the remaining steps — phase 4, moving the
dashboard's signing onto the relay, and phase 5, a live registration — as separate, reviewed steps.

**The Android MRV app and the reviewers' debug APK — 2 October night.** `mobile/android` is a Gradle/Kotlin
project in two modules. `:core` is plain Kotlin on JVM 17 — H3 indexing, the allometry, keccak and the
nullifier derivation, the relay client and the submission queue — and is tested against the repository's
own Python through generated golden vectors. `:app` is the Compose UI: a three-step wizard (the GPS fix,
refused worse than 30 m; the trunk photo and diameter; the hand-off to the relay), a Room queue that holds
captures until there is signal, and a read-back of the minted tree from Celo. The phone holds no key: it
carries the planter's public address and a relay session token, and the relay signs.

| Time | Commit | What it was |
| --- | --- | --- |
| 2 Oct 23:00–23:01 | `ab33f02`, `74735f7` | `:core` — H3, allometry, relay client and queue, tested against the repository's Python; the registration body checked with `relay/validate.py` and driven against the real relay over HTTP |
| 2 Oct 23:17–23:18 | `d0cf204`, `a5ec801` | `:app` — the three-step wizard, the Room queue and the chain read-back; the module README, and `:core:test` made to execute on every run |

The install-id header of `9ee6ff4` is the last change to `mobile/android`, and the published debug APK was
built from that tree: `docs/carriers.json` pins it to tree `421f7f03fe0db6ab473d8538e029b0b981357e16`,
which is the tree of `mobile/android` at `f6f2045` (Section 3.2). The app's instrumented tests compile but
were never run, and the module README records that nothing ran on a device.

**Clean-clone proof and the push path — 2 October evening to 3 October 00:35.**

| Time | Commit | What it was |
| --- | --- | --- |
| 2 Oct 19:07–20:24 | `37119c9`, `614764c`, `2ad393d`, `c3700d4`, `fbcd920` | A false branch claim in `DEPLOY_DASHBOARD.md` corrected; the fork rehearsals and the Foundry deploy scripts accept either form of the deployer key; the README quick start fixed so a clean clone can run the gate |
| 2 Oct 20:57 | `22dc88e` | `tools/clean_clone_proof.py`: a plain `git clone`, the README quick start run line by line, then the acceptance gate; and the gate's key-free mode (`VERIFY_ALLOW_NO_KEY=1`), whose banner can never read as a full pass |
| 2 Oct 21:11–21:39 | `6755d37`, `67d42c1`, `2fed0aa`, `10ac8bf` | A push to `main` gated on the proof (`scripts/git-hooks/pre-push`, `scripts/push-verified.sh`), a key-free CI job (`.github/workflows/clean-clone-proof.yml`), and the documentation sweep that became gate step 8 |
| 3 Oct 00:22–00:35 | `511e27d`, `ccc32fa` | Both push paths refuse a stale base in seconds, before the minutes-long proof rather than after it, through one shared check (`scripts/lib/fast_forward_check.sh`) |

The CI job ran on each recent push of `main`: GitHub's Actions API reports `success` for the
clean-clone-proof runs on `a5ec801`, `ccc32fa`, `2d635c0`, `550942c`, `0c4c640` and the audited tip
`f6f2045`. CI holds no key, so these are the gate's key-free runs, which skip the steps that need it.

**The carrier gate — 2 October 18:10 to 3 October 11:04.** The reviewer-facing copies held in the
workspace Files are not reachable from the repository, so on 2 October nothing noticed when the proposal
markdown had moved three commits past its published render. `tools/check_carriers.py` holds each
published copy to the source it was made from, against the publish record `docs/carriers.json`, and is
gate step 7.

| Time | Commit | What it was |
| --- | --- | --- |
| 2 Oct 18:10–18:13 | `4fd762b`, `d0f3500` | The gate and the publish record for the first four carriers (the proposal pdf, docx and md, and the architecture raster); gate step 7; the publish flow, `DEPLOY.md` section 9 |
| 2 Oct 23:15 | `16e9bf8` | The pdf's render bytes are attested only where the published copies are staged, since Chromium print-to-PDF bytes depend on the browser build and fonts |
| 3 Oct 01:02 | `2d635c0` | Strict publish mode, `--require-staged`: an absent or partial staging directory is drift, exit 1, so a publish whose staged copies went missing cannot read green |
| 3 Oct 11:04 | `f6f2045` | The slide-size architecture raster, the vector copy and the debug APK become carriers: seven in all, each checked by the strongest thing that holds for it |
| 3 Oct 12:44–12:51 | `575e4d9`, `33ac692` | The milestone report docx, the mainnet deployment plan and `FINDINGS.md` become carriers, and their doc names join the doc-path allowlist |
| 3 Oct 13:46 | `083e74a` | The two demo videos and the contract source doc become carriers: thirteen in all |
| 3 Oct 15:14 | `b3ec3f5` | Step 7 refuses a carrier record that is short or duplicate-padded, not only one missing a listed carrier, with the floor written down in `DEPLOY.md` section 9 |

**The dashboard redesign — 3 October early morning.**

| Time | Commit | What it was |
| --- | --- | --- |
| 3 Oct 02:13 | `c0d1c62`, `35757a5` | Home (`dashboard/home_view.py`) becomes the first screen for every visitor: the hero, two calls to action, a live strip (chain id, tree count, the pilot registration's cost from its receipt, the proxy), the Why-Celo cards and the three-step strip. The views become home / register / protocol, with `?view=planter` and `?view=operator` kept as aliases; the lime-and-emerald restyle with a deeper dark mode and tabular figures; the gate's UI check walks the new first screen (8 renders become 12) |
| 3 Oct 03:02 | `550942c` | A test fix so the Home view's URL assertion holds on Streamlit 1.65 and later |

**This refresh — 3 October 2026.** The audit in Section 3 was re-run against `f6f2045`, no tracked changes,
remote head equal to local head, and this report was carried forward in place. It is rendered to DOCX by
`tools/render_report_docx.py`, a committed renderer that reuses the proposal's
(`tools/render_proposal_docx.py`) so the two documents share one look. Section 6 records how the report
itself becomes a gated carrier.


## 3. Repository and artifact consistency audit

### 3.1 Scope and method

Every tracked file in `AdamJannoud/BioRig` was examined programmatically at `f6f2045`, and the results
were read file by file rather than accepted from the script's summary. The audit covers six groups:

1. **Inventory and structure** — what is tracked, in what proportion, and whether anything is present
   that should not be (key material, build output, scratch state).
2. **Authorship and attribution** — git identity across all commits, plus the attribution claims made
   inside the tracked content itself.
3. **Cross-carrier fact agreement** — whether one address, chain id, transaction hash or role appears
   with the same value in every file that carries it: contracts, deployment records, broadcast
   receipts, the dashboard configuration, the test suite and the documents.
4. **Documentation truth** — whether any tracked document still asserts something the live chain or
   the current tree makes false.
5. **Published carriers** — whether every copy published to reviewers outside the repository still
   matches the source it was made from, as recorded in `docs/carriers.json`.
6. **Executable verification** — the suites, the check scripts and the acceptance gate, run today with
   exit statuses captured in-band, plus a live read-back of the deployed state.

The audit is read-only: it writes nothing into the repository.

### 3.2 Inventory

296 tracked entries at `f6f2045`, up from 163 at `9a4815f`. The counts below are derived from
`git ls-files` and add up exactly:

| Type | Count | What it is |
| --- | --- | --- |
| .py | 81 | dashboard 22, tools 29, relay 19, scripts 3, evidence 3, the Android tooling 3, `script/` 1, and the root `streamlit_app.py` |
| .sol | 41 | 35 contracts, scripts and tests in `src` (3), `script` (9) and `test` (23); the historical `BioRigV3.sol` at the root; 5 preserved as evidence in `evidence/i6/` |
| .kt | 38 | the Android app's Kotlin sources and JVM tests under `mobile/android` |
| .json | 30 | chain and deployment configuration, broadcast receipts, ABIs, evidence captures, demo facts, the carrier record and the docs allowlist, the Android golden vectors |
| .txt | 15 | requirements files and evidence captures |
| .md | 12 | `README.md`, `DEPLOY.md`, `DEPLOY_DASHBOARD.md`, `DEMO.md`, `FINDINGS.md`, `dashboard/README.md`, `docs/prezenti-proposal.md`, `docs/relay-api.md`, `relay/README.md`, `mobile/android/README.md`, `assets/brand/README.md`, `evidence/i6/README.md` |
| .svg | 11 | the architecture diagram and the brand kit (mark, lockup, icons, favicon, two alternates, the dashboard's two marks) |
| .sh | 10 | the acceptance gate, the push and fork-rehearsal scripts, the evidence scripts and one sourced library |
| .png | 7 | the committed architecture raster, the brand lockup, marks and favicons |
| .log | 7 | operational evidence captures, explicitly labelled historical |
| .xml | 5 | Android manifest and resources |
| .kts | 4 | Gradle build scripts |
| .ttf, .toml | 3 each | display fonts the explainer renderer needs; Foundry, Streamlit and Gradle configuration |
| .sql, .properties, .gitignore, .example, .diff | 2 each | the relay's two migrations; Gradle properties; the root and Android ignore files; `.env.example` and `.env.mainnet.example`; captured upgrade diffs |
| single files | 13 | `.gitattributes`, `.gitmodules`, `foundry.lock`, `pytest.ini`, the architecture .sha256 file, `tools/print/proposal.css`, `script/data/ERC6551Registry.canonical.bin`, the pristine baseline `src/BioRigCoreV5.sol.orig`, the brand kit's `favicon.ico`, the Gradle wrapper jar and `gradlew.bat`, the CI workflow, and the dashboard's browser-geolocation component page |
| no extension | 6 | `assets/fonts/LICENSE-DejaVu`, `mobile/android/gradlew`, `scripts/git-hooks/pre-push`, and the three dependency submodules tracked as gitlinks |

No key material is tracked. Two `.env` templates are tracked (`.env.example`,
`.env.mainnet.example`) and both contain placeholders and comments only; the real `.env`,
`.env.mainnet` and `.deploy/` are ignored, the Android project's own ignore file refuses `*.jks` and
`*.keystore`, and the deployed relay's store `relay/var-public/` is ignored since `0c4c640`.

**Published carriers.** Seven files are published into the workspace Files for reviewers. They live
outside the repository, so they are named here by their record names in `docs/carriers.json`, not as
repo paths. The record at `f6f2045` reads:

| Carrier | Size (bytes) | Compared by | Made from |
| --- | --- | --- | --- |
| proposal pdf | 553,754 | sha256 `7c0e11d1…` | `docs/prezenti-proposal.md` through `tools/render_proposal_pdf.py`, with `tools/print/proposal.css` and the brand lockup |
| proposal docx | 87,852 | digest over its zip entries `1a4c43eb…` | the same markdown through `tools/render_proposal_docx.py`, with the lockup |
| proposal md | 34,435 | sha256 `8c6d8eb4…` | a byte copy of `docs/prezenti-proposal.md` |
| architecture png | 1,796,369 | sha256 `ae7044ce…` | a byte copy of `BioRig_Architecture_Pro.png`, itself a render of `assets/BioRig_Architecture_v5.svg` |
| architecture svg | 20,707 | sha256 `9e893e08…` | a byte copy of `assets/BioRig_Architecture_v5.svg` |
| architecture-slide png | 858,508 | the provenance its own bytes carry (the svg's sha256) and its 2400 x 2124 size | `tools/generate_architecture.py` over the same svg |
| android-debug apk | 16,079,038 | the git tree of `mobile/android` it was built from, `421f7f03…`; the bytes against the record where staged | `mobile/android` at that tree |

Run at `f6f2045`, `tools/check_carriers.py` finds every recorded source unchanged, a fresh docx render
matching the published entry digest, the md, png and svg matching their committed sources byte for byte,
and the app source equal to the tree the APK was built from. The published copies themselves are not
reachable from the repository, so they were not downloaded from Files for this refresh. Three local copies
of the reviewer artifacts held beside the workspace — the debug APK, the slide raster and the vector — were
staged and checked against the record instead, and all three match it byte for byte. The pdf's render
bytes are, by design, attested only where the published copies are staged; here the check notes that and
enforces the recorded source digests.

### 3.3 Authorship and attribution

**Git identity.** All 122 commits carry the same e-mail address for author and committer,
`jannoud-adam@hotmail.com`, and no bot account appears. The audit found the name spelled two ways —
121 commits read `AdamJannoud` and one, `550942c` on 3 October, read `Adam Jannoud`, same address. That
variant was normalized on 8 October 2026 by a repo-wide identity rewrite, so every commit in the
current history reads `AdamJannoud <jannoud-adam@hotmail.com>`, author and committer.

**Co-author trailers — a correction to the 2 October edition.** That edition stated there were "no
co-author trailers" in the history. That was wrong when it was written. 21 commits carry a
`Co-Authored-By:` trailer naming an AI coding assistant (Claude); 20 of them predate the 2 October audit,
including commits that edition itself quoted (`69a8caf`, `7ea558e`, `c4470c8`, `90e98ea`), and one,
`16e9bf8`, is from 2 October 23:15. The trailers record tooling used while writing those commits; they do
not change who authored, committed, owns or deployed anything, and every commit's author and committer
field is still Adam Jannoud. This report states the fact instead of repeating the earlier claim, and
leaves the decision about it to Adam (Section 3.9).

**Attribution inside the content.** A grep across every tracked file for agent, tool or platform
identities now returns one class of hit: the Foundry CLI's own name (the word `forge` inside `forge
script`, `forge test`, `forge verify-contract` commands, and the `lib/forge-std` module path) — the
build tool, not an authorship claim. The two classes the 2 October and 3 October editions recorded are
both closed against the head `b3ec3f5`: the working environment's scratch paths are gone from
`.gitignore` (the rules moved to the repository's own untracked `.git/info/exclude`, so the working
environment still ignores them and a reader of the tracked file sees no trace), and `docs/relay-api.md`
and `relay/tests/test_edge.py` describe the edge's behaviour without naming the hosting platform. The
one platform-derived string that survives is the header name `X-Sandbox-Forwarded-Authorization`
itself — the constant the edge sends and `relay/service.py` reads, which cannot be renamed without
breaking the deployed relay.

**Attribution statements in the documents.** `README.md`, `DEPLOY.md`, `DEMO.md` and
`dashboard/README.md` each state in their own words that Adam Jannoud is the project lead, the author
and the sole deployer, and that every recorded deployment was broadcast by him. Those statements are
consistent with the git author and committer fields and with the on-chain record.

### 3.4 Cross-carrier fact agreement

Each of these values was checked for agreement across every tracked file that carries it
(case-insensitive, submodules excluded). All agree:

| Fact | Value | Carriers |
| --- | --- | --- |
| Mainnet proxy | `0x04Db169dDF8AbB80943161C01B2a71DC40384E64` | 21 files — the documents, the architecture SVG, the deployment record, the broadcast receipts, the dashboard config and the tests |
| Implementation | `0xdb3a450b85D48E6e6552dB2b32aD75a7ac590c60` | 6 files |
| Safe (admin and upgrader) | `0x3B36b3446fCB0729B0046520156933E56352D551` | 10 files — the `.env.mainnet` template, `README.md`, `DEPLOY.md`, the `HardenMainnetAdmin` and `SafeOwnerSwap` broadcast receipts, and the two fork rehearsal harnesses |
| Deployer hot key | `0x1DB0084Db70bF8D0E06c1785D693Fc6a95317890` | 12 files |
| Safe owner EOA | `0xD314e37FD8538fe66231EE670B74C9428d03feEa` | 19 files |
| First-tree nullifier | `0xb7a55a6b…d741` | 6 files, among them the deployment record, the demo facts file and the proposal |
| Token-bound account | `0x453e89520DB8f374CFCeA95625B99DF5d4F1256A` | 6 files, among them `tools/demo_facts.json` and the proposal |

The live chain read-back in Section 3.8 confirms each of these as the value actually deployed, so the
agreement is not merely internal consistency between files that could all be wrong together.

Chain identifiers are carried deliberately by 26 files for `11142220` and 41 for `42220`. The Sepolia
carriers were classified one by one and are accounted for in Section 3.10; none of them is an executable
read path, because the runtime resolves the chain from `dashboard/chains.json` plus the `CHAIN_ID`
override.

### 3.5 Documentation truth

Every tracked markdown file was searched for the claim classes that go stale silently, and the hits were
read in context rather than counted:

- **Claims that an operation is still pending.** The hits are `DEMO.md` stating the 20% buffer-pool
  split is roadmap and not implemented (true), the proposal's sentence about a market "where it has not
  yet been applied at the smallholder tier" (a claim about the market, not this project), and the
  relay's documented `recovery_pending` and `tx_pending` states (protocol vocabulary). **No false
  hit.**
- **Claims that mainnet holds no trees, or is inert.** The one hit is `DEPLOY.md` *recording* that the
  deployment "is no longer inert". **No false claim remains.**
- **Claims about the work since 2 October.** `README.md`'s Layout and Docs sections name neither
  `relay/` nor `mobile/android`, nor their READMEs or the relay contract, so a reviewer who enters
  through the README will not find the relay or the app. And `mobile/android/README.md` records 43
  `:core` tests in its account of what was run when the app was built; the suite has 49 today, the six
  added since all arriving with the install id in `9ee6ff4`. The first is a gap, the second a dated statement;
  neither is false about the chain, and both are listed in Section 3.9.
- **Commit-hash pins.** 15 distinct backticked tokens of 7 to 40 hex digits appear across the tracked
  documents. Four resolve as commits. Seven are decimal numbers (the Sepolia chain id and block numbers),
  and the other four are legitimately not commit hashes — two fragments of ERC-1167 minimal-proxy
  bytecode, the demo plot's H3 cell `8c7a6e42ca207ff`, and the md5 digest of the contract source.
  **No stale commit pin.**
- **Paths, links, commands, ports and environment variables.** The seven gating documents are now swept
  mechanically by `tools/check_docs_paths.py` on every gate run (step 8, Section 3.7), against the
  allowlist in `docs/doc-path-allow.json`.

### 3.6 Secrets and repository hygiene

- **A 32-byte hex value paired with `PRIVATE_KEY` appears in exactly one tracked file**, and it is the
  well-known Anvil development key in `script/fork-dry-run.sh` (line 49), commented as local-fork only.
  It is a public test constant, not a secret.
- **Executable bits.** Nine of the ten tracked shell scripts are mode `100755`. The tenth,
  `scripts/lib/fast_forward_check.sh`, is `100644`: it carries a shebang but is a library that both push
  paths source, never execute, so the mode is correct for its use. `mobile/android/gradlew` and
  `scripts/git-hooks/pre-push` are `100755`. Five Python files carry a shebang at `100644` and are run
  through the interpreter.
- **Build output.** No `out/`, `cache/` or `.venv/` path, and no Gradle build or node_modules directory, is tracked; the
  Gradle wrapper jar is committed on purpose, as its ignore file says.
- **`.gitignore`** covers `.env`, `.env.*` (with the two committed templates re-included), `.deploy/`,
  key material, the relay's local and deployed stores, and the sandbox scratch paths.
- **Dependencies.** `tools/requirements.txt` declares the tooling's dependencies; the Android build
  resolves its own through `mobile/android/gradle/libs.versions.toml`.


### 3.7 Executable verification

| Suite | Command | Result |
| --- | --- | --- |
| Foundry | `forge test` | **181 passed, 0 failed**, 17 suites, 11.02 s |
| Python (every chain) | `pytest dashboard tools relay -q` | **440 passed**, 141.39 s — dashboard 150, tools 183, relay 107 |
| Python (mainnet) | `pytest dashboard tools relay -q --chain-id 42220` | **412 passed**, 130.69 s |
| Android `:core` | `./gradlew :core:test` in `mobile/android` | **49 passed**, `BUILD SUCCESSFUL`; run in a scratch clone of `f6f2045` so no build output lands in this checkout |
| Android cross-checks | `mobile/android/tools/gen_golden.py --check`, `check_registration_body.py`, `relay_e2e.py` | all three exit 0: the golden vectors match the repository's Python, the relay's validator accepts the app's body and refuses the four smuggled-field controls, and the queue drives the real relay end to end (`E2E PASS`) |

The Python suite is run twice because the chain selection is itself under test: the default run covers
every chain in `dashboard/chains.json` and the `42220` run narrows the dashboard's chain-parameterised
tests to mainnet, so the count differs by design — the 28 fewer tests are the dashboard's Sepolia cases
(150 collected by default, 122 with `--chain-id 42220`). The relay suite, 107 tests, joined both runs on
2 October and touches no network and no real key.

**The acceptance gate.** `scripts/verify-demo.sh` has ten steps at `f6f2045`. It is the one command that
ties the system together, so it is worth stating what each step actually proves rather than only that it
passed:

| Step | What it proves |
| --- | --- |
| 1. Contract sources untouched | `src/` and `test/` match `HEAD`, so nothing passed by editing the code under test |
| 2. Unit tests | The dashboard's pure logic, the tooling and video timing tables, and the relay: 440 passed in 127.67 s |
| 3. Live chain | `getTreeStats(1)` against mainnet; the token-bound account derived three ways (offline CREATE2, the registry's `account()` over `eth_call`, and the stored address), all equal; a `mintTree` `eth_call` simulation with a fresh salt, and the reuse of tree 1's nullifier refused `NullifierInUse()` — **no broadcast** |
| 4. Dashboard in a real browser | No `X-Frame-Options` or `frame-ancestors` header; twelve renders (Home, the register flow and the protocol view, dark and light, at 1440px and 390px): no missing element, zero console errors, no horizontal overflow, no key in the page; and the two old view links still open their screens |
| 4b. Mainnet rehearsals | Both executed operations replayed on a fork of live mainnet: the Safe owner swap (**54 checks**, `REHEARSAL PASSED`) and the role handover (**23 checks**, `REHEARSAL PASSED`), each with 0 failures |
| 5. Video | The 90-second explainer re-renders and probes at 1920 x 1080, 30 fps, 2,700 frames, 90.000000 s (3,543,402 bytes this run) |
| 5b. Roadmap label | The ROADMAP pill is absent before its cue and present in the rendered pixels of scene 4 and the closing card: 0 pill pixels at 71 s, 6,876 at 76 s and 226 on the closing card at 89 s |
| 6. Secrets | The live `.env` key appears in no tracked file: the gate scanned all 293 tracked regular files (the other three tracked entries are the dependency submodules) |
| 7. Proposal carriers | `tools/check_carriers.py`: every published carrier still matches the source it was made from (Section 3.2). With no copies staged it notes, rather than attests, the pdf's render bytes (its fresh render did match the recorded digest) and the slide raster's provenance |
| 8. Documentation | `tools/check_docs_paths.py`: every path, link, command, port and env var the seven gating documents name is real: the seven documents clean, with 18 findings allowlisted, each with a reason |

**What the gate printed.** The run quoted in the table started at 11:45:03 and ended at 11:50:48 UTC on
3 October: exit status 0, captured in-band, and the final line `ALL DEMO CHECKS PASSED`. It was the third
run of the day. The two before it failed, and both are recorded here rather than left out:

- **Run 1 (11:30–11:36) failed in step 4.** Two of the twelve renders — Home in light mode at 1440px, and
  the register flow in light mode at 390px — were missing elements that wait on a chain read, while the
  same views passed in every other mode and width. The run overlapped a burst of RPC reads made for this
  report, which drew a temporary rate limit from `forno.celo.org`, the dashboard's own endpoint. That is
  the likeliest cause, and run 3, made with nothing else reading the chain, passed all twelve renders; but
  it is an inference, and the check's sensitivity to a slow or limited RPC is worth knowing.
- **Run 2 (11:37–11:43) passed steps 1 to 7 and failed step 8** on 31 findings, every one a path under
  `.venv`. In the audit environment `.venv` was a symbolic link to a shared virtualenv rather than a
  directory; git refuses to evaluate a path beyond a symbolic link, so the `.venv/` rule in `.gitignore`
  could not cover `.venv/bin/python`. That is a property of the environment, not the repository: with
  `.venv` as a real directory, as the README's quick start creates it, step 8 reported the seven documents
  clean, and run 3 was made that way. The same symptom will appear on any checkout whose virtualenv is a
  symbolic link.

### 3.8 Live read-back

Read over RPC against Celo mainnet at block `79125988` (`forno.celo.org`) and again at block `79126079` on a
second public endpoint (`rpc.ankr.com`), gas price 202.5 gwei, and reconciled against the repository. The
two endpoints returned identical state. Every value the repository states for the deployment is the value
the chain returns:

| Check | Chain says | Matches |
| --- | --- | --- |
| `chain-id` | `42220` | yes |
| Proxy code | 163 bytes | yes — a real contract, not an EOA; the proposal records the same 163 |
| Implementation slot | `0xdb3a450b85D48E6e6552dB2b32aD75a7ac590c60` | yes — the deployment record and the broadcast receipts |
| `paused()` | `false` | yes — the contract is live |
| `bufferPool()` | deployer hot key | yes — `DEMO.md`, `DEPLOY.md`, `README.md` |
| Safe `getOwners()` | `[0xD314…feEa]` | yes |
| Safe `getThreshold()` / `nonce()` | `1` / `1` | yes — one swap executed, nothing since |
| Safe holds `DEFAULT_ADMIN_ROLE`, `UPGRADER_ROLE` | `true`, `true` | yes |
| Deployer holds `VERIFIER_ROLE` only | `true`, admin `false`, upgrader `false` | yes |
| Safe owner EOA holds any role | `false` for all three | yes |
| Tree `1` stats | dbh 10, biomass 20, ts 1790893247, account `0x453e…256A`, alive `true` | yes |
| Tree `1` owner, `ownerOf(1)` | `0xD314…feEa` | yes |
| Tree `2` | `getTreeStats(2)` reverts `InvalidTree` | yes — still exactly one tree |
| Tree `1` nullifier active | `true` | yes |
| Token-bound account | `0x453e89520DB8f374CFCeA95625B99DF5d4F1256A`, 173 bytes of code | yes |
| Account `supportsInterface(0x6faff5f1)` | `true` | yes — ERC-6551 |
| Account `token()` | `(42220, proxy, 1)` | yes — the binding, read from the account side |

Two notes of honesty rather than gaps.

**The trees are exactly one.** `getTreeStats(2)` reverts `InvalidTree`. That is the correct state for a
pilot that has minted one tree, and it is still the reason Phase A of the roadmap is the first thing to
do. The relay and the app added since 2 October have not changed it.

**The account's address is now confirmed three ways again.** The token-bound account's 173 bytes are
exactly what ERC-6551 prescribes: the 45-byte ERC-1167 minimal proxy pointing at the account
implementation `0x65D18C960170ca2B4936c62945bA0e827e5cCd2B`, followed by a 128-byte footer carrying the salt,
the chain id (`0xa4ec`, 42220), the token contract (the proxy) and the token id (1). And step 3 of the
acceptance gate derives the address offline through CREATE2, reads it from the canonical registry's
`account()` over `eth_call`, and reads the stored value from `getTreeStats` — all three equal. The 2
October edition said the registry's `account()` was not a `view` function and could not be compared
reliably; the vendored registry (`src/vendor/ERC6551Registry.sol`) declares it `external view`, and the
gate's call succeeds, so that note is withdrawn (Section 3.9).

### 3.9 Findings

**Corrections to the 2 October edition, found by this refresh.** Each was wrong when it was written; none
is a change in the project.

1. **"No co-author trailers."** 21 commits carry a `Co-Authored-By:` trailer naming an AI coding
   assistant; 20 of them predate that audit (Section 3.3). Author and committer are Adam Jannoud on every
   commit, which is what the ownership statements in this report rest on. Whether to keep the trailers is
   Adam's call: they cannot be removed without rewriting the published history again, which would change
   every hash this report and the other documents quote. This report makes no change.
2. **Code sizes.** The proxy holds 163 bytes of code, not 139, and the token-bound account 173, not 93
   (Section 3.8). Contract code cannot change in place, so the earlier figures were mis-measured rather
   than out of date; the proposal already carried the correct 163.
3. **The handover's time.** The role handover ran at 22:03:51–22:04:00 UTC on 1 October by its blocks'
   own timestamps, not "~21:40" (Section 2.5).
4. **The registry's `account()`.** It is a `view` function, and the three-way account check the 2 October
   edition withdrew is back in the gate (Section 3.8).
5. **The gate's steps.** That edition called the gate seven and eight steps in different places and
   described step 5b as "the lab's dependency set is complete"; step 5b asserts the roadmap label in the
   rendered pixels. The gate had eight steps then and has ten now (Section 3.7).

**Found by this refresh, open, for Adam to decide.**

6. **`README.md` does not lead to the relay or the app.** Its Layout table and Docs list name neither
   `relay/` nor `mobile/android`, nor `relay/README.md`, `docs/relay-api.md` or
   `mobile/android/README.md`. The work is documented where it lives, but a reviewer entering through
   the README will not find it. A two-line addition closes it.
7. **The relay's public address is recorded nowhere in the tree.** The deployed relay sits behind a public
   HTTPS edge, but neither the documents nor the published APK name its address, so nothing in the
   repository can check it, and this report cannot re-derive it (Section 2.10).
8. **`mobile/android/README.md` records 43 `:core` tests.** That was true when the app was built; the
   suite has 49 since `9ee6ff4`. It sits in a section that records what was run at build time, so it is
   dated rather than false, but the next touch of that file should update it.
9. ~~**One commit spells the author name differently.**~~ **Fixed 8 October 2026 by the repo-wide
   identity rewrite.** It read `Adam Jannoud` where the other 121 read `AdamJannoud`, both on the same
   address. Every commit in the current history reads `AdamJannoud <jannoud-adam@hotmail.com>`, author
   and committer.

**Carried from 2 October, cosmetic, still open.**

10. ~~**`.gitignore` names the working environment's own directory.**~~ **Fixed 3 October 2026.** The two
    ignore rules that named the working environment's own scratch directory and task file are gone from
    the tracked `.gitignore` and now live in the repository's untracked `.git/info/exclude`, so those
    paths stay ignored in the working environment and are invisible to a reader of the tracked file (the
    old lines are in the history, at `f6f2045` and earlier). The hosting platform's name went from
    `docs/relay-api.md` and `relay/tests/test_edge.py` in the same sweep (Section 3.3): both describe
    the edge's behaviour — the rename of the `Authorization` header — without naming the host. The
    header name `X-Sandbox-Forwarded-Authorization` is a protocol constant and stays.

**Fixed on 2 October and confirmed still fixed.** The `README.md` `BUFFER_POOL` wording (`b98726d`), the
two scripts tracked non-executable (`598c017`) and the undeclared `cv2` import (`9a4815f`) all hold at
`f6f2045`.

**Checked and found clean.** No key material tracked; both `.env` templates are placeholders; no build
output tracked; no false "pending" or "nothing deployed" prose in the twelve tracked documents; every
commit hash pinned in the documents resolves, and every other hex token is accounted for; the carrier
record agrees with every source it names; the seven gating documents pass the documentation sweep.

**Carried into the roadmap, not defects.** The token-bound account reward flows are design and not
implemented; the pilot tree carries placeholder measurements; the minting role is still on the deployer
hot key; the relay has not yet registered a tree on mainnet. Each is stated as open in Sections 1 and 4
rather than implied to be done.

### 3.10 Residual testnet references

The tree carries `11142220` in 26 files and `42220` in 41. Each Sepolia carrier was classified, and
none of them is an executable read path:

- **Legitimately dual-chain:** `dashboard/chains.json` and the multi-chain `dashboard/deployment.json` hold a
  record per chain, which is the point of the files.
- **Testnet deployment records and receipts:** the two Sepolia broadcast receipts, the four evidence logs
  and the demo facts file are historical evidence of a real deployment and should stay.
- **Documents:** where a document names Sepolia it is describing the testnet deployment or the demo,
  both of which genuinely happened there. The one new document hit, `relay/README.md`, shows
  `RELAY_CHAIN_ID=11142220` as an example override for a testnet run.
- **Tests and checks:** the dashboard suite is parameterised over both chains by design, which is why
  the `--chain-id 42220` run exists as a separate gate; the relay's config and plot-index tests and the
  fork harnesses name the testnet to prove it is refused or handled where it should be.

The rule that keeps this from being a defect is that no runtime path resolves a chain from a literal:
the dashboard reads `dashboard/chains.json` plus the `CHAIN_ID` override, the relay defaults to the
deployment record's default chain (42220) with `RELAY_CHAIN_ID` as its override, and the check scripts
take the expected chain and proxy from configuration.


## 4. Proposed roadmap and execution plan

The grant application frames three funded milestones. This section restates them as an ordered
execution plan with dependencies, and adds the workstreams that do not need funding but do need doing
before a larger ask is defensible. Each phase's status was re-checked against the tree and the chain at
`f6f2045` rather than carried from the 2 October text.

### 4.1 Sequencing at a glance

| Phase | What it delivers | Grant milestone | Depends on | Status at `f6f2045` | Can start |
| --- | --- | --- | --- | --- | --- |
| **A** Fleet-scale pilot minting | 25–50 real trees on mainnet, with a repeatable registration procedure and a cost model | Milestone 4 (pilot at field scale) | the relay in live service, a dedicated verifier key | **Open.** One tree on chain. The repeatable procedure now exists as the relay; it has not minted on mainnet | now |
| **B** Live biomass and DBH feed | Real measurements behind `dbh` and `biomass`, and `updateTree` writes as trees grow | Milestone 4 / feeds Milestone 3 | A | **Partly built.** The allometric model is in the tree and shared by the dashboard, the relay and the app; registrations carry a measured DBH. No update feed exists; tree 1 still carries 10 / 20 | now |
| **C** Dashboard as an operating console | Multi-tree view, per-tree history, mortality reporting, a gated verifier write path | Milestone 4 | A, B | **Partly built.** Home, the register flow and the protocol view are live on the hosted demo; there is one tree to list | after A |
| **D** Token-bound account reward flows | Automated 20% buffer-pool split and planter payout from each tree's account | Milestone 3 (second half) | C, and a security review | **Open.** `bufferPool` is a stored address; no routing exists | after C |
| **E** Native mobile client | Android and iOS builds capturing growth records offline | Milestone 2 | B's measurement schema | **Android debug build delivered**; iOS, on-device depth estimation, a release build and any on-device test run are open | now (iOS, depth) |
| **F** On-chain zk-ML verification | Growth verification moved from a trusted signer to a verifiable pipeline | Milestone 3 (first half) | E | **Open** | grant onset |
| **G** Independent security review | Third-party review of the deployed system, focused on the value-bearing paths and the internet-facing relay | Milestone 3 / budget line | D | **Open** | before D is enabled on mainnet |

**Done since the 2 October edition, and therefore no longer roadmap:** the registration relay through
phase 3 and behind a public edge; the Android MRV app and its published debug APK; the dashboard's Home
page and restyle; the clean-clone proof on every push to `main`; the carrier gate with its strict publish
mode, extended to all seven published carriers; and the documentation sweep as a gate step.

**What is open, in the order it should be done:**

1. **A minting key of the relay's own.** The Safe grants `VERIFIER_ROLE` to a key only the relay holds
   and revokes it from the deployer (Section 4.3). Nothing else on this list should reach mainnet first.
2. **Relay phase 4.** The dashboard's register flow posts to the relay and the dashboard's own signing
   path is deleted (Section 4.4).
3. **Relay phase 5.** One live registration on mainnet through the relay, read back from the chain
   (Section 4.2).
4. **Phase A at scale**, with the relay's key funded for the batch (Section 4.2).
5. **Phase B's re-measurement route**, then **Phase C's fleet views** (Sections 4.3 and 4.4).
6. **Phase E's remaining work** — iOS, depth estimation, a signed release build, a run on a device — in
   parallel from grant onset, then **F**, **G** and **D** in that order (Sections 4.5 and 4.6).

Alongside, two small documentation fixes from Section 3.9: point `README.md` at the relay and the app,
and record the relay's public address somewhere the repository can check it.

### 4.2 Phase A — Fleet-scale pilot minting

**Why it is first.** Two reasons, and the second is the one that matters for funding. It is the
fastest way to find the rough edges in the operating path (nullifier hygiene, cost per tree, what a
second and third tree do to the dashboard), and it produces the on-chain transaction volume that
Prezenti's own pool bands are keyed to. The current position — one tree on mainnet — supports the
smaller ask and not the larger one, which is exactly what the proposal says.

**Deliverable.** 25–50 trees on chain `42220`, registered through the relay, each with an H3-derived
nullifier that is recorded as active and a token-bound account created through the canonical registry.

**Evidence that it is done.** `getTreeStats(n)` returns a live tree for every `n` minted; a cost
report records gas and CELO per tree and in total; `dashboard/deployment.json` and the README are
refreshed to the new count; every mint traces to a relay job rather than a shell history.

**What changed since 2 October.** Two of the three known-work items are now built. The relay is the
committed, repeatable procedure the 2 October edition asked for in place of one `cast send` per tree, and
it closes the double-mint risk in storage: the ordinal is allocated under the cell's write lock and
`UNIQUE(cell, tree_ordinal)` and `UNIQUE(nullifier)` back it. What remains is putting it into service:
the relay's phase 4 (moving the dashboard's own signing path onto the relay) and phase 5 (a first live
registration), a dedicated verifier key (Section 4.3), and the trees themselves.

**Cost and funding.** The pilot mint cost 0.054 CELO at 200 gwei. Gate step 3's simulation of a second
mint estimated 277,017 gas, which at the 202.5 gwei read on 3 October is about 0.056 CELO a tree. The
deployer key held 2.98 CELO at block `79125988` — enough for roughly fifty mints and nothing else, so the
top of the 25–50 band needs the verifier key funded before it starts.

### 4.3 Phase B — Live biomass and DBH feed

**Why it matters.** This is where the pilot stops being a placeholder. The tree on mainnet carries
`dbh 10` and `biomass 20`, which are arbitrary values chosen to prove the mint path works. Until real
measurements flow, no claim about growth monitoring can be checked by anyone.

**Deliverable.** Registrations that carry a field measurement, with biomass derived by a documented
allometric model, and a verifier write path for `updateTree` (and `reportMortality` where a tree is lost)
as trees are re-measured. Each write is attributable to a transaction the dashboard can show.

**What changed since 2 October.** The model is done: `dashboard/allometry.py` implements the Chave et al.
2014 pantropical equation with its citation, the relay recomputes biomass from DBH itself and only
compares the client's estimate, and the Android `:core` module is a line-for-line port tested against the
Python through golden vectors. Relay contract v1 is the measurement schema for a *registration*: species,
DBH in centimetres, a GPS fix with its accuracy, and the trunk photo's SHA-256.

**Still open.** Contract v1 has no re-measurement route, so nothing yet writes `updateTree`; the photo is
hashed but never uploaded; and `updateTree` is gated by `VERIFIER_ROLE`, so until Milestone 3 this feed is
trusted rather than verified, and the documents must say so.

**Evidence that it is done.** At least one mainnet tree's `dbh` and `biomass` change over time, with
the update transaction recorded; the dashboard shows the change history per tree.

**Security prerequisite — and it is now on the critical path.** Before the relay registers real trees,
the minting role should move off the deployer hot key onto a dedicated key that only the relay holds. The
relay is built for exactly that and its boot check refuses to start unless its signer holds
`VERIFIER_ROLE`; but on mainnet today only the deployer holds the role, so a relay put into service now
would have to run with the deployer key on an internet-facing host. The Safe already holds
`DEFAULT_ADMIN_ROLE`, so it can grant `VERIFIER_ROLE` to the relay's key and revoke it from the deployer
without another handover. This closes the one residual risk mode B deliberately accepted, and it should
come before phase A's first relay registration rather than after.

### 4.4 Phase C — Dashboard as an operating console

**Deliverable.** The Streamlit app grows from "show one tree" to "operate a fleet": every tree listed
with its stats and nullifier state, a per-tree history, mortality reporting, and a verifier write path
behind an explicit flag that keeps the read-only mode as the default.

**What changed since 2 October.** The public face is done: Home is the first screen, with a live strip
read from the chain, and the register flow and protocol view sit behind it; the gate walks all three in
both modes at desktop and phone widths. The write path is already behind an explicit flag
(`ALLOW_MINT`), and the relay's phase 4 removes the dashboard's own signing entirely, which is the cleaner
end state.

**Evidence that it is done.** The hosted instance lists every minted tree; opening any tree shows its
history; registration from the hosted page goes through the relay, and the hosted demo holds no key.

**Constraint that must not be relaxed.** The hosted public demo holds no key and performs no writes of
its own. The gate proves no key reaches the rendered page; whether a key sits in the hosted platform's
secrets is held outside the repository and cannot be re-derived here, which is one more reason to finish
phase 4 and take the key out of the dashboard altogether.

### 4.5 Phase D — Token-bound account automated reward flows

**Why here and not earlier.** This is the only phase that moves value, so it comes after the system
has real trees, real data and a review. It is the second half of grant Milestone 3.

**Deliverable.** Value arriving at a tree's token-bound account is routed automatically: 20% to the
buffer pool address held in `bufferPool`, the remainder to the planter. `bufferPool` is already a
stored address with an admin-only setter, and the token-bound account machinery already exists — what
is missing is the routing policy and its implementation. Unchanged since 2 October.

**Evidence that it is done.** A funded fork test proves the split, including the buffer share reaching
`bufferPool()` and the planter share reaching the tree owner; an invariant test covers the accounting;
then a first real transaction on mainnet with the split read back from the chain.

**Prerequisite.** Phase G. Adding value-bearing logic to a deployed contract without an independent
review is the one place in this roadmap where the downside is not merely a bad dashboard.

### 4.6 Phases E and F — the funded engineering milestones

**Phase E (Milestone 2, 45% of the recommended budget).** The proposal's deliverable is an Android and
iOS client implementing offline monocular depth estimation with verifier-signed sync, so a growth record
can be captured with no connectivity and submitted later. Part of it now exists. The Android app captures
a registration offline, queues it in Room and sends it when there is signal, and the verifier — the relay
— signs; it was built against relay contract v1 rather than defining a second schema, as this roadmap
asked. What is not built: iOS; the depth estimation (the planter enters the diameter and the photo is
hashed, not measured); a signed release build (the published APK is a debug build); and any run on a
device — the instrumented tests compile but have not executed. The remaining work is the larger share of
the milestone, and the proposal should present the Android build as a working foundation, not as the
milestone delivered.

**Phase F (Milestone 3, 30%).** Move growth verification from a trusted signer to an on-chain
verifiable pipeline. Deliverable: proofs verified on chain, which is what allows the documents to stop
describing the trust boundary as `onlyRole(VERIFIER_ROLE)`. Unchanged since 2 October.

### 4.7 Risks, and what to do about each

| Risk | Why it matters | Mitigation |
| --- | --- | --- |
| The minting role is still the deployer hot key | A compromised key can mint fraudulent trees; it cannot upgrade or grant roles. Putting the relay into service with that key would move it onto an internet-facing host | Dedicated verifier key for the relay, granted by the Safe, deployer revoked, before the first relay registration; no handover needed |
| The relay is internet-facing | It holds the minting key and accepts anonymous sessions | Per-device limits keyed on the install id, a relay-wide ceiling of 30 sessions an hour, fail-closed boot checks, an admin pause; include the relay in Phase G's scope |
| The device limit trusts a client-chosen id | A caller can mint fresh install ids to get fresh per-device budgets | The relay-wide session ceiling bounds it by design; watch it once real traffic arrives |
| Cost at scale | About 0.056 CELO per mint at 200 gwei means 1,000 trees is roughly 56 CELO; the minting key holds 2.98 | Phase A measures the real cost; fund the verifier key for the batch before committing to a mint count |
| The measurement feed is trusted | `updateTree` takes no proof, so a wrong or dishonest measurement is recorded | Say so in the documents; Phase F replaces it with verification; keep an audit trail per write |
| Reward routing moves value | A defect in the split is a fund-handling defect | Fork-proof first, invariant test, independent review (Phase G) before mainnet enablement |
| The hosted demo is public | A write path there could expose a key | Keep the hosted instance read-only; finish the relay's phase 4 so the dashboard holds no key at all |
| Published copies drifting from the source | On 2 October the published proposal was three commits behind its markdown and nothing noticed | The carrier gate (gate step 7) now holds all seven published carriers to their sources; this report becomes the eighth once the reviewer records it (Section 6) |
| Documents drifting from the chain again | The 2 October edition itself carried statements that were wrong when written (Section 3.9) | The gate re-reads the chain and runs the fork rehearsals; the documentation sweep covers the seven gating documents; every figure in this report is tied to a reproducible command (Section 5) |


## 5. Verification appendix

Every command below was run on 3 October 2026 against a checkout of `f6f2045` with no tracked changes.
Exit statuses were captured in-band from the command's own process, never through a pipe. Each figure in
this report is also listed with the exact command that produced it in a facts file delivered alongside
the report (Section 6).

### 5.1 Repository state

```bash
git rev-parse HEAD                                   # f6f2045b9bb5519ae1eff81af2444cd9f3aa5293
git ls-remote origin refs/heads/main                 # same hash — remote head equals local head
git status --porcelain --untracked-files=no          # empty — no tracked changes
git rev-list --count HEAD                            # 122
git ls-files | wc -l                                 # 296, of which 3 are submodule gitlinks
git log --format='%an <%ae>' | sort | uniq -c        # 121 AdamJannoud, 1 Adam Jannoud, one address
git log --format=%h -i --grep='co-authored-by' | wc -l   # 21
git rev-parse HEAD:mobile/android                    # 421f7f03fe0db6ab473d8538e029b0b981357e16
```

### 5.2 Suites

```bash
git submodule update --init --recursive              # a fresh clone leaves lib/ empty
forge test                                           # 181 passed, 0 failed, 17 suites, 11.02 s
.venv/bin/python -m pytest -q dashboard tools relay  # 440 passed in 141.39 s
.venv/bin/python -m pytest -q dashboard tools relay --chain-id 42220   # 412 passed in 130.69 s
.venv/bin/python mobile/android/tools/gen_golden.py --check            # exit 0
.venv/bin/python mobile/android/tools/check_registration_body.py       # exit 0, four controls refused
.venv/bin/python mobile/android/tools/relay_e2e.py                     # E2E PASS
cd mobile/android && ./gradlew :core:test --console=plain             # 49 PASSED, BUILD SUCCESSFUL
```

The Gradle run writes build output under `mobile/android`, so for this refresh it was run in a scratch
clone of the same commit rather than in the audited checkout.

### 5.3 Live chain read-back

```bash
export RPC_URL=https://forno.celo.org
cast chain-id --rpc-url $RPC_URL                     # 42220
cast block-number --rpc-url $RPC_URL                 # 79125988 at read time
cast codesize 0x04Db169dDF8AbB80943161C01B2a71DC40384E64 --rpc-url $RPC_URL   # 163
cast storage 0x04Db169dDF8AbB80943161C01B2a71DC40384E64 0x360894a13ba1a3210667c828492db98dca3e2076cc3735a920a3ca505d382bbc --rpc-url $RPC_URL
cast call 0x04Db169dDF8AbB80943161C01B2a71DC40384E64 'hasRole(bytes32,address)(bool)' $(cast keccak VERIFIER_ROLE) 0x1DB0084Db70bF8D0E06c1785D693Fc6a95317890 --rpc-url $RPC_URL
cast call 0x04Db169dDF8AbB80943161C01B2a71DC40384E64 'getTreeStats(uint256)((uint96,uint96,uint64,address,bool,bytes32))' 1 --rpc-url $RPC_URL
cast call 0x04Db169dDF8AbB80943161C01B2a71DC40384E64 'isNullifierActive(bytes32)(bool)' 0xb7a55a6b1b7e4fe0fba76f303772cba7fdf3715d4030e3fcd91ed297c756d741 --rpc-url $RPC_URL
cast call 0x3B36b3446fCB0729B0046520156933E56352D551 'getOwners()(address[])' --rpc-url $RPC_URL
cast call 0x453e89520DB8f374CFCeA95625B99DF5d4F1256A 'token()(uint256,address,uint256)' --rpc-url $RPC_URL
cast codesize 0x453e89520DB8f374CFCeA95625B99DF5d4F1256A --rpc-url $RPC_URL   # 173
cast receipt 0x70476c02ef1af918a213eec63472e6cdbabcedd50193cdd6a7a89a09527797f7 --rpc-url $RPC_URL
```

The same `hasRole` call runs for each of the three holders and each of the three roles
(`DEFAULT_ADMIN_ROLE` is the zero hash, the other two are `cast keccak` of their names), and the Safe is
read for `getThreshold()` and `nonce()` as well as `getOwners()`. Every read was repeated on a second
public endpoint with identical results. The historical figures in Sections 2.4 to 2.6 come from the
receipts of the transactions named in the three committed mainnet broadcast records and the mint. Results
are in Sections 1.2 to 1.4 and 3.8.

### 5.4 Acceptance gate

```bash
mkdir -p out
bash scripts/verify-demo.sh > out/verify-demo.log 2>&1; echo "GATE_EXIT=$?"
```

The gate's ten steps are listed in Section 3.7 with what each one proves and what it printed. It reads the
deployer key from `.env` itself; nothing in this report or its facts file prints it.

### 5.5 Consistency sweep

The sweep described in Section 3.1 was run as a read-only script over the tracked tree. It checks the
inventory, all git identities and trailers, identity leakage, secret-shaped strings, executable bits on
shebang'd scripts, every backticked hex token in the documents against the git object database, and the
per-address carrier counts in Section 3.4. It writes nothing into the repository. The carrier check of
Section 3.2 is the repository's own:

```bash
.venv/bin/python tools/check_carriers.py             # exit 0; the pdf render bytes noted, not attested, without staged copies
.venv/bin/python tools/check_docs_paths.py           # the seven gating documents: clean
```

### 5.6 The wiki

The workspace wiki pages that held BioRig project state on 2 October were not re-read for this refresh,
so nothing is claimed about them here.

---

## 6. Provenance and status of this report

- **Compiled:** 3 October 2026, from the repository at `main` = `f6f2045`, with live chain reads taken the
  same day. It refreshes the 2 October 2026 edition in place; that edition's audited basis was `9a4815f`,
  with its one fix pushed as `b98726d`.
- **Rendered:** `tools/render_report_docx.py` turns this markdown into the DOCX through the proposal's own
  renderer, as `.venv/bin/python tools/render_report_docx.py --src docs/milestone-roadmap-report.md --out out/milestone-report.docx`.
  It exits non-zero if a heading is missing from the rendered text, an internal link resolves to nothing,
  a markdown table did not become a real table, or the package's authorship metadata names anyone but
  Adam Jannoud.
- **Becoming a gated carrier.** The rendered DOCX is delivered outside the repository, beside the other
  published carriers, so it is not named here as a repo path. Recording it — adding it to
  `docs/carriers.json` with this markdown and the two renderers as its sources, and adding this document
  to the documentation sweep — is the reviewer's step, done through the publish flow in `DEPLOY.md`
  section 9. Until then, nothing gates this report against its source.
- **Ownership:** this report describes work in `AdamJannoud/BioRig`, which is owned, authored and
  deployed by Adam Jannoud. Every commit in the repository is authored and committed by that identity;
  21 commit messages also carry a co-author trailer naming an AI coding assistant (Section 3.3).
- **What it does not claim:** that the external audit has happened (it has not; it is a grant
  milestone), that the pilot tree carries real field measurements (it does not), that the reward flows
  are implemented (they are design), that the relay has registered a tree on mainnet (it has not), or
  that the Android app has run on a device (its own README says it has not). Each of those is stated as
  open rather than implied.
- **What it could not re-derive:** the deployed relay's public address and its running mode, which the
  tree does not record; the explorer's 1 October verification times and match sources; the bytes held in
  the workspace Files, which are not reachable from the repository (three local copies were checked
  instead); whether the hosted demo's platform secrets hold a key; and the workspace wiki. Each is said
  where it arises rather than repeated from the 2 October text.
- **Reproducibility:** the commands in Section 5 reproduce every figure in this report. Where a figure
  could not be re-derived today, it is not stated as fact.
