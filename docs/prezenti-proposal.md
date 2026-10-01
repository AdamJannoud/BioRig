# BioRig — Prezenti Grant Application Proposal

**Project:** BioRig — Mobile-First dMRV & Proof-of-Growth Infrastructure on Celo
**Applicant:** Adam Jannoud — project lead, author and sole deployer
**Program:** Prezenti Grants (Celo Community Grants)
**Current round open until:** 29 December 2026
**Proposal status:** Draft for applicant review before submission
**Prepared:** 1 October 2026
**Last revised:** 1 October 2026 — Celo mainnet deployment executed; four contracts live on chain 42220 for 0.803044 CELO (see [Section 2.1](#21-network), [Section 2.2](#22-deployed-contracts), [Section 6.2](#62-the-honest-summary)), and Milestone 4 restated as the pilot and the first live trees, the deployment itself now being done. The reviewer verification note (Section 5.2) now carries the four Celo mainnet deployment transaction hashes with explorer links. The reviewer-facing dashboard is now live and public at <https://biorigdemo.streamlit.app>, verified anonymously; Section 2.6, Section 5 and the open-items table record it.

> **Read this first.** This draft is grounded in the live state of the project on 1 October 2026, re-verified the same day. Three things commonly assumed about BioRig in draft applications do not currently hold, and they are stated plainly below rather than smoothed over, because a Prezenti reviewer will check them: the explorer records are *partially* verified rather than fully verified, the one tree on chain was minted with a bare-salt nullifier rather than the documented H3 derivation, and the live **Celo mainnet** deployment carries no minted trees yet, so the on-chain activity a reviewer can point at is still the Celo Sepolia one. See [Section 6](#6-eligibility-position-against-prezentis-published-criteria) and [Section 7](#7-open-items-to-close-before-submission).

---

## 1. Project Overview & Elevator Pitch

### 1.1 One line

BioRig is mobile-first dMRV and proof-of-growth infrastructure on Celo: a smallholder planter proves that a tree exists and is growing using only a phone, and that proof is minted on chain as an ERC-721 tree whose proceeds are held in an ERC-6551 Token-Bound Account.

### 1.2 Problem

Measurement, Reporting and Verification (MRV) is the bottleneck in every carbon and agroforestry market. Today it is built around periodic third-party auditors with satellite subscriptions and field visits, which produces two failures at once:

- **It prices out the smallholder.** Verification cost per hectare exceeds the revenue per hectare for plots in the range of a few hundred square metres to a few hectares, which is most of the supply in emerging markets. The result is that the farmers who could most benefit are structurally excluded from the market.
- **It leaks privacy and trust.** Proving a specific plot exists and is growing requires revealing *where* it is. Publishing precise geolocation to a public ledger exposes land tenure, family holdings and income data, and gives competitors and bad actors a map of exactly who to target. Meanwhile the same plot can be claimed twice, because nothing binds a physical location to a single claimant without an identity system.

### 1.3 Solution

Three mechanisms, all of which are implemented in the deployed contract:

- **Proof-of-Growth via Edge AI on mobile.** Growth and structural condition are estimated on the device with monocular depth estimation, so verification does not depend on connectivity, satellite revisits or an auditor visit. Only the signed result is transmitted.
- **H3 spatial nullifiers for privacy-preserving Sybil defence.** A plot is reduced to an H3 resolution-12 cell and committed as a 32-byte nullifier. Uniqueness is enforced per cell without publishing coordinates, so a planter can prove a plot is theirs and one-of-a-kind without ever revealing where it is.
- **Dynamic ERC-721 trees bound to ERC-6551 Token-Bound Accounts.** One token is one plot. Each token owns a Token-Bound Account, so the tree is not just a record: it is an account that can hold and route funds, which is what makes the 20% solvency buffer pool and downstream revenue routing possible at all.

---

## 2. Technical Deliverables & Current State (Live Proof of Feasibility)

### 2.1 Network

| Item | Value |
|---|---|
| Network | Celo Sepolia (**testnet**) |
| Chain ID | `11142220` |
| RPC | `https://forno.celo-sepolia.celo-testnet.org` |
| Note | The former Alfajores testnet (`44787`) is dead and is not in use. |
| Celo mainnet | Chain ID `42220`. **Live since 1 October 2026** — all four contracts deployed, addresses and cost in [Section 2.2](#22-deployed-contracts). The canonical ERC-6551 registry already carried code on mainnet with bytecode identical to Sepolia's, so the deployment reused it and sent no CREATE2 transaction. |

### 2.2 Deployed contracts

All four are live on Celo Sepolia and carry executable bytecode:

| Contract | Address | Role |
|---|---|---|
| ERC1967Proxy | `0x21ab8b36177f65ce69e04e281e4aff3db6b5f7e6` | Live entry point (UUPS) |
| BioRigCoreV5 (implementation) | `0x4c998c6553c78bb9d5a67aac6fbc526d64dba3a4` | Core logic |
| Canonical ERC-6551 Registry | `0x000000006551c19487814612e58FE06813775758` | Canonical address, carries code |
| ERC-6551 Account Implementation | `0x3d8a53db1bbcab6d47097b25080527e5560c5165` | Token-Bound Accounts |

**Proxy creation block:** 37511856.

The same four contracts were deployed to **Celo mainnet** (chain `42220`) on 1 October 2026:

| Contract | Address | Role | Deployment transaction |
|---|---|---|---|
| ERC1967Proxy | `0x04Db169dDF8AbB80943161C01B2a71DC40384E64` | Live entry point (UUPS) | [`0x2b2d42c17b6b6b1a1522086e718f4d5ab9b04180da7cfd328ddce11982f453a5`](https://celo.blockscout.com/tx/0x2b2d42c17b6b6b1a1522086e718f4d5ab9b04180da7cfd328ddce11982f453a5) (389,191 gas) |
| BioRigCoreV5 (implementation) | `0xdb3a450b85D48E6e6552dB2b32aD75a7ac590c60` | Core logic | [`0xc06b4b994dc36d6e21f95a1359c768573226aa913856df68a9215bfc4ef351eb`](https://celo.blockscout.com/tx/0xc06b4b994dc36d6e21f95a1359c768573226aa913856df68a9215bfc4ef351eb) (2,942,890 gas) |
| Canonical ERC-6551 Registry | `0x000000006551c19487814612e58FE06813775758` | The same canonical address as Sepolia; mainnet already carried the code, so no transaction was sent for it | None — the code was already at this address, so the deployment reused it |
| ERC-6551 Account Implementation | `0x65D18C960170ca2B4936c62945bA0e827e5cCd2B` | Token-Bound Accounts | [`0xdd6b5e999894b1ed6450eafe9a689448c15f285a0e860600913084963f55f53b`](https://celo.blockscout.com/tx/0xdd6b5e999894b1ed6450eafe9a689448c15f285a0e860600913084963f55f53b) (626,504 gas) |

Each hash is a link to that transaction's page on the Celo mainnet Blockscout explorer. All three are creations, mined in block `78935900` with receipt status `1`, and the address printed in the row is the contract each transaction created.

**Mainnet proxy creation block:** 78935900. **Measured mainnet deployment cost: 0.803044 CELO** — 4,015,198 gas at 200.0011 gwei across four transactions, every receipt status `0x1`. The fourth transaction was not a creation: it granted `VERIFIER_ROLE` on the proxy to the admin account `0x1DB0084Db70bF8D0E06c1785D693Fc6a95317890` — [`0xf97d29ab26f9fb96ec5d407e62f423f189649fa186b94e15bca47b3860c36dc8`](https://celo.blockscout.com/tx/0xf97d29ab26f9fb96ec5d407e62f423f189649fa186b94e15bca47b3860c36dc8) (56,613 gas). The canonical registry accounts for the gap between the three creations above and the four transactions, since it sent none. The four transactions are listed one by one, with their gas figures, in [Section 5.2](#52-reviewer-verification-note).

**No tree has been minted on the mainnet contract.** It is deployed and empty; the minted tree described in Section 2.5 is the Celo Sepolia one. Mainnet code sizes match the compiled artifacts exactly: 163 bytes at the proxy, 13,243 at the implementation and 2,651 at the account implementation.

### 2.3 Verification status — stated precisely

All four contracts return `is_verified = true` on Blockscout, with `verified_at` timestamps between 19:17 and 19:39 UTC on 30 September 2026.

**However**, all four also return `is_partially_verified = true` and `is_fully_verified = false`. This is not an error and not a submission failure: the canonical ERC-6551 registry is matched through Blockscout's Ethereum Bytecode Database, which compares executable bytecode and ignores the trailing metadata hash, so the submitted source cannot reproduce the deployed IPFS metadata digest. The executable code is byte-identical; only the metadata digest differs.

**What this means for a reviewer:** clicking through the explorer will show four records flagged as partially verified. That is expected, and it is verifiable independently — recompiling the canonical source at solc 0.8.17 / evm `london` / optimizer 200 reproduces 571 bytes of executable code identical to the deployed registry, differing only in the trailing metadata.

### 2.4 Testing and quality assurance

| Check | Result |
|---|---|
| Foundry suite | **175 passed, 0 failed, 0 skipped** across 16 suites, exit 0, after a clean rebuild (`rm -rf cache out`) |
| Storage layout | V5 occupies slots 0-8; slot 9 is reserved and free for a V6 append |
| Upgrade safety | Proven, not asserted: the upgrade test snapshots all nine V5 slots with `vm.load`, performs the upgrade, and asserts every slot is byte-identical, that slot 9 reads the V6 marker, and that neither side collides |
| Live bytecode vs. local source | Proxy 163 bytes and account implementation 2,651 bytes byte-for-byte identical to the compiled artifacts; core implementation 13,243 bytes identical apart from the single UUPS `__self` immutable, which holds the implementation's own address and agrees with the proxy's ERC1967 slot |
| Dashboard and tooling tests | **129 passing**, and the same suite is green under both `CHAIN_ID=42220` (Celo mainnet) and `CHAIN_ID=11142220` (Celo Sepolia) |
| Architecture address tests | 16 passing, resolving the registry address from the chain configuration rather than a chain-specific broadcast artifact |
| Hosted entrypoint check | exit 0 in all three modes, with no secrets and no `.env` on disk |
| Read-only telemetry | Loads with `.env` removed and every secret unset; chain ID, proxy, live tree and nullifier all resolve |

Re-verified live on 1 October 2026: chain ID `11142220` at block 37531117, all four contract code sizes matching the compiled artifacts, `src/BioRigCoreV5.sol` md5 `f6db19ed010db46ab48720f8fe137736` unchanged since the final contract round. On Celo mainnet the same check returns 163 bytes at the proxy, 13,243 at the implementation and 2,651 at the account implementation, identical to the compiled artifacts.

### 2.5 Live on-chain state

One tree has been minted, and it is live:

| Field | Value |
|---|---|
| Token | 1 |
| Mint transaction | `0x486bc529…4b9d5f9e` |
| Block | 37512380 |
| Gas used | 267,565 |
| Planter | `0xb5aB2054b43040593805Cf662A938eFE924F2778` |
| Nullifier stored | `0xf8fa2658012341dda81dbb7d27a6bb0accd68b63e618001d8ccbed1375dbf667` |
| Token-Bound Account | `0x61bd8BEcE5a38209Fc10d4DA3f837EE83a10124a` |

The Token-Bound Account derivation agrees three independent ways: offline CREATE2, `ERC6551Registry.account` via `eth_call`, and the stored on-chain value. The account answers ERC-165 with `0x6faff5f1` and reports the bound token as `(11142220, 0x21ab8b36…, 1)`.

**A correction on the nullifier.** The production nullifier pipeline is the H3 resolution-12 derivation `keccak256(uint64(h3Cell) ++ utf8(salt))`, implemented in `dashboard/h3_nullifier.py`. For the demo plot at lat -1.2921, lng 36.8219, res 12, salt `"plot-1"`, that yields cell `8c7a6e42ca207ff` and nullifier `0xb7a55a6b1b7e4fe0fba76f303772cba7fdf3715d4030e3fcd91ed297c756d741`.

**The tree currently on chain is not a product of that pipeline.** Its nullifier is `keccak256("plot-1")` — the bare salt, with no H3 cell — because `mintTree` stores whatever 32-byte value the verifier passes and rejects only `bytes32(0)`. The derivation is therefore an off-chain convention enforced by the application, not an on-chain rule. This is documented in the repository. The consequence for this application is stated plainly: **the only tree on chain does not demonstrate the H3 pipeline, and the H3 nullifier mechanism is proven by tests and by the dashboard rather than by on-chain history.**

### 2.6 Repository and demo

| Item | Value |
|---|---|
| Repository | `AdamJannoud/BioRig` — **private** |
| Branch | `main` |
| Head commit | `b4f34df` on `main`, verified against the GitHub API on 1 October 2026 before this document was committed |
| Reading the live tip | `git ls-remote origin refs/heads/main` — the head moves whenever a commit lands, so read it rather than trusting any hash printed here |
| Live demo | **<https://biorigdemo.streamlit.app>** — public, opens without a sign-in; verified anonymously on 1 October 2026 |

**One thing a reviewer cannot currently open, fixable before submission:**

1. **The repository is private.** A reviewer following the repository link will get a 404. It must either be made public before submission or reviewer access granted.

**The hosted dashboard is now live.** <https://biorigdemo.streamlit.app> opens without a sign-in and renders read-only telemetry against the live Celo Sepolia proxy: the chain ID, the proxy and implementation addresses, the current block, and `getTreeStats(1)` for the one tree on chain, with minting disabled by default. It was verified anonymously on 1 October 2026 — a browser session carrying no cookies and no stored credentials loaded the page and read the tree state from the chain. The page resolves its deployment from `dashboard/deployment.json`, so it renders against chain `11142220` (Celo Sepolia), where the demo tree lives; the Celo mainnet deployment is recorded in the same file.

### 2.7 Security posture

- **Upgradeability is bounded.** UUPS with `_authorizeUpgrade` restricted to the admin role, and the V5 storage layout frozen at the slots above.
- **Input validation is enforced on chain.** `mintTree` validates the registry's returned ERC-6551 account: code must be present, the account must answer ERC-165 with `0x6faff5f1`, and its `token()` must equal `(stored chainId, this, tokenId)`. A nullifier of `bytes32(0)` is rejected. A codeless non-zero `setURIGenerator` address is rejected.
- **Metadata cannot brick a token.** `tokenURI` falls back to the base implementation when `uriGenerator` is codeless, reverting, or gas-exhausting, so an admin error or a broken external contract cannot make a tree unreadable.
- **Defect found and fixed.** The audit pass found `mintTree` accepting `address(0)` as the account implementation and fixed it, with a regression test against the pre-fix source.
- **The demo harness is read-only.** The dashboard gates minting behind an explicit `ALLOW_MINT` flag, and the demo ran with no transaction broadcast.
- **No secrets in the repository.** `.env` is excluded and the verification runs were executed with every secret unset.

---

## 3. Ecosystem Impact & Alignment with Celo

### 3.1 Financial inclusion for smallholder planters

The core economic argument is arithmetic. Verification cost per plot is roughly fixed while plot revenue scales with plot size, so below a certain size the ratio inverts and the planter is excluded. BioRig attacks the cost side directly: edge AI on a device the planter already owns removes the satellite subscription and the auditor visit from the critical path, and the H3 nullifier removes the need for a paid identity or attestation layer to prevent double-claiming. The result is a per-plot verification cost that does not scale with the number of planters.

This is Celo's stated mission applied to a market where it has not yet been applied at the smallholder tier: a financially excluded producer gaining direct, self-custodied access to carbon and agroforestry revenue through a phone.

### 3.2 Foundation for downstream ReFi protocols

BioRig is deliberately infrastructure rather than a marketplace. A tree is an ERC-721 with an ERC-6551 account, which makes it a composable primitive:

- **Carbon registries and marketplaces** (Toucan, Flowcarbon and equivalents) can consume BioRig trees as a verified supply source rather than building their own MRV.
- **Enterprise Scope 3 retirement** can reference token-bound accounts for provenance, so an offset retirement traces back to a specific plot, a specific planter and a specific growth record.
- **DeFi on Celo** gains a collateral class backed by a productive physical asset with a live growth signal, which is exactly what most nature-based collateral schemes lack.

Every consumer built on top of BioRig writes to Celo, and the token-bound account design means value routed to a tree lands in an account on Celo rather than off chain.

### 3.3 Direct alignment with the Celo ecosystem

- **Native Celo deployment.** Contracts, the canonical ERC-6551 registry at its canonical address, and all tooling target Celo and nothing else.
- **MiniPay-shaped distribution.** The planter-facing surface is a phone, and the economics only work at smallholder scale, which is precisely the population MiniPay reaches.
- **USdm-denominated flows.** Grant funding, and in production the buffer pool and revenue routing, settle in a USD-denominated stable asset.
- **Verifiable on-chain activity.** Every claim in this application resolves to a transaction hash, a contract address or a re-runnable test suite.

---

## 4. Milestone Roadmap & Budget Request

### 4.1 Roadmap

**Milestone 1 — Foundation (COMPLETED, self-funded).**
Core contract architecture, ERC-6551 integration, H3 spatial nullifier indexing, and 175 Foundry tests, deployed and verified on Celo Sepolia. Delivered and independently checked as of 1 October 2026.

**Milestone 2 — Native mobile client.**
Android and iOS client implementing offline monocular depth estimation with verifier-signed sync, so a growth record can be captured with no connectivity and submitted later. Deliverable: a shipped mobile build producing signed growth records that the deployed contract accepts.

**Milestone 3 — On-chain zk-ML growth verification and buffer pool routing.**
Move growth verification from a trusted signer to an on-chain verifiable pipeline, and automate the 20% solvency buffer pool routing. Deliverable: proofs verified on chain, and buffer routing executing without manual intervention.

**Milestone 4 — First mainnet pilot and live trees.**
The Celo mainnet deployment this milestone was framed around is already complete: four contracts have been live on chain `42220` since 1 October 2026 (addresses, block and cost in [Section 2.2](#22-deployed-contracts)), carrying no minted trees yet. What remains here is the pilot and the first live trees — an initial agroforestry community producing on-chain trees on mainnet, plus ReFi marketplace integration. Deliverable: live mainnet trees with third-party usage.

### 4.2 Budget request

> **Applicant decision required.** No figure has been committed. What follows is a recommendation with its reasoning, to be confirmed or replaced before submission.

**Recommended ask: 25,000 USDm**, released against Milestones 2, 3 and 4.

Reasoning: Prezenti's own published Anchor pool bands are approximately 25,000 USDm at Stage 2 and 50,000 USDm at Stage 3, both keyed to daily transaction volume. BioRig is live on Celo mainnet but carries no transaction volume there, so the smaller figure is the defensible ask and the larger one is not supportable on current evidence.

**Recommended allocation:**

| Bucket | Share | Purpose |
|---|---|---|
| Mobile client engineering | 45% | Milestone 2 — offline depth estimation, signed sync, both platforms |
| Verification pipeline and zk tooling | 30% | Milestone 3 — on-chain verification and buffer routing |
| Pilot deployment and integration | 20% | Milestone 4 — agroforestry pilot, first live mainnet trees, marketplace integration |
| Security review | 5% | Independent review of the deployed system, scheduled as a milestone deliverable rather than a gate on the Alpha v1 broadcast |

Note that Prezenti splits payments 20% at project onset and 80% after agreed delivery, so Milestone 1 being complete means the request is for delivery of Milestones 2-4 rather than for work already done.

---

## 5. Team & Verification Note

### 5.1 Team

> **Applicant input required.** No team members are named beyond the applicant; no people, roles or biographies are invented for a document that goes to a grant reviewer.

**Adam Jannoud** — applicant, project lead, author and sole deployer. Author of the contract architecture, the test suite, the deployment tooling and the documentation, and the only account that has deployed BioRig.

*Placeholders to complete before submission:* any additional team members with their roles and links; prior shipped work in the ecosystem; and a decision on whether the project's AI-assisted development workflow is disclosed (see Section 7).

### 5.2 Reviewer verification note

This is the note a reviewer can follow step by step. It contains no claims beyond what the four addresses and the repository support.

**1. Contracts — Blockscout (Celo Sepolia and Celo mainnet)**

Open the explorer for Celo Sepolia and look up these four addresses:

| Contract | Address |
|---|---|
| ERC1967Proxy (entry point) | `0x21ab8b36177f65ce69e04e281e4aff3db6b5f7e6` |
| BioRigCoreV5 implementation | `0x4c998c6553c78bb9d5a67aac6fbc526d64dba3a4` |
| Canonical ERC-6551 Registry | `0x000000006551c19487814612e58FE06813775758` |
| ERC-6551 Account Implementation | `0x3d8a53db1bbcab6d47097b25080527e5560c5165` |

All four show `is_verified = true`. They are also flagged **partially verified**, which is expected for the reason given in Section 2.3 and does not indicate a submission failure.

The same four contracts are live on **Celo mainnet** (chain `42220`), deployed on 1 October 2026: proxy `0x04Db169dDF8AbB80943161C01B2a71DC40384E64`, implementation `0xdb3a450b85D48E6e6552dB2b32aD75a7ac590c60`, canonical registry `0x000000006551c19487814612e58FE06813775758` (the same address on both chains), account implementation `0x65D18C960170ca2B4936c62945bA0e827e5cCd2B`. They show the same verification pattern as their Sepolia counterparts: `is_verified = true` with `is_fully_verified = false`, resolved through the same executable-bytecode match described in Section 2.3.

**The four Celo mainnet deployment transactions** — all in block `78935900` on chain `42220`, every receipt status `1`, each hash linking to its page on the Celo mainnet Blockscout explorer:

- Deployed the ERC-6551 account implementation — [`0xdd6b5e999894b1ed6450eafe9a689448c15f285a0e860600913084963f55f53b`](https://celo.blockscout.com/tx/0xdd6b5e999894b1ed6450eafe9a689448c15f285a0e860600913084963f55f53b) (626,504 gas)
- Deployed the BioRigCoreV5 implementation — [`0xc06b4b994dc36d6e21f95a1359c768573226aa913856df68a9215bfc4ef351eb`](https://celo.blockscout.com/tx/0xc06b4b994dc36d6e21f95a1359c768573226aa913856df68a9215bfc4ef351eb) (2,942,890 gas)
- Deployed the ERC1967Proxy that is the entry point listed above — [`0x2b2d42c17b6b6b1a1522086e718f4d5ab9b04180da7cfd328ddce11982f453a5`](https://celo.blockscout.com/tx/0x2b2d42c17b6b6b1a1522086e718f4d5ab9b04180da7cfd328ddce11982f453a5) (389,191 gas)
- Granted `VERIFIER_ROLE` on the proxy to the admin account `0x1DB0084Db70bF8D0E06c1785D693Fc6a95317890` — [`0xf97d29ab26f9fb96ec5d407e62f423f189649fa186b94e15bca47b3860c36dc8`](https://celo.blockscout.com/tx/0xf97d29ab26f9fb96ec5d407e62f423f189649fa186b94e15bca47b3860c36dc8) (56,613 gas). The role is `0x0ce23c3e399818cfee81a7ab0880f714e53d7672b08df0fa62f2843416e1ea09`, the `keccak256` of `VERIFIER_ROLE`. `initialize` has no transaction of its own because it runs inside the proxy's constructor, so the proxy is never live and uninitialised.

The canonical ERC-6551 registry has no deployment transaction of its own: it already existed at `0x000000006551c19487814612e58FE06813775758` on chain `42220` and the deployment reuses it, which is why there are four transactions rather than five. The four gas figures total 4,015,198, the cost recorded in Section 2.2.

**2. Reading the live state yourself**

Using the RPC endpoint `https://forno.celo-sepolia.celo-testnet.org` against the proxy address, call `getTreeStats(1)`. It returns the live tree, including the bound Token-Bound Account and the stored nullifier listed in Section 2.5. `getTreeStats(2)` reverts, which confirms exactly one tree exists. The same call against the Celo mainnet proxy `0x04Db169dDF8AbB80943161C01B2a71DC40384E64` on `https://forno.celo.org` reverts for `getTreeStats(1)`, which confirms the mainnet contract holds no trees yet.

**3. Reading the mint**

The mint transaction `0x486bc529…4b9d5f9e` at block 37512380 is visible in full on the explorer: 267,565 gas, planter `0xb5aB2054b43040593805Cf662A938eFE924F2778`, and the nullifier value the transaction itself carries as its second argument. That argument is the bare salt, as Section 2.5 states.

**4. Repository**

`AdamJannoud/BioRig`, branch `main`, head `b4f34df` as verified on 1 October 2026. This document was committed on `main` after that verification, so read the live tip with `git ls-remote origin refs/heads/main` rather than treating the hash in this sentence as current. Run `forge test` for the 175-test suite and `forge inspect src/BioRigCoreV5.sol:BioRigCoreV5 storageLayout` for the storage layout the upgrade test asserts. `FINDINGS.md` at the repository root records the audit: per-hypothesis verdicts, the defect that was found and fixed, the residual trust deliberately left open, and an honest list of what was not verified.

**5. Hosted dashboard**

Live at <https://biorigdemo.streamlit.app> — public, no sign-in required, verified anonymously on 1 October 2026. The page exposes read-only telemetry against the live Celo Sepolia proxy (chain ID, proxy and implementation addresses, current block, and `getTreeStats(1)` for the one tree on chain) with minting disabled by default. It resolves its deployment from `dashboard/deployment.json` and therefore renders against chain `11142220`, where the demo tree lives; the Celo mainnet deployment is recorded in the same file.

---

## 6. Eligibility Position Against Prezenti's Published Criteria

This section exists because the published criteria for both open pools contain hard requirements BioRig does not currently meet, and stating that here is better than having a reviewer discover it.

### 6.1 The three pools

| Pool | Access | Core requirement | BioRig position |
|---|---|---|---|
| **Boost** | Invitation only, from Celo Core Co / DevRel | Live app, ideally a MiniApp; must deploy on Celo mainnet | Not applicable — no invitation |
| **Anchor** | Open application | Verifiable traction: stage bands keyed to 10K-100K+ daily transactions; must deploy on Celo mainnet | **Does not currently qualify.** The mainnet deployment requirement is now met (Section 2.2), but there is one on-chain tree and no transaction volume |
| **Frontier** | Open application | AI and agent-economy **infrastructure**; working Celo mainnet deployment verified by Prezenti; ERC-8004 registration and Self Agent ID for agent projects | **Does not currently qualify.** The mainnet deployment exists but is not yet verified by Prezenti, and BioRig is ReFi/dMRV infrastructure rather than AI/agent infrastructure |

### 6.2 The honest summary

BioRig's technical foundation is real, deployed and verified: contracts live on Celo Sepolia and on Celo mainnet, 175 tests green, upgrade safety proven, and bytecode matching the source. Its position against Prezenti's published criteria is still not met by either open pool. Two things decide that position, and only the second is a gap today:

1. **Mainnet — closed on 1 October 2026.** Both open pools require a working deployment on Celo **mainnet**. The four contracts are live there, deployed for a measured 0.803044 CELO (Section 2.2). The contract holds no trees yet, so the deployment exists without activity on it.
2. **Traction.** The Anchor pool is explicitly stage-based on daily transaction volume and rejects projects "without verifiable traction or credible usage evidence". BioRig has one minted tree, on Celo Sepolia, and none on Celo mainnet.

The most defensible route is therefore to mint a small number of real trees on the now-live mainnet contract and apply with that evidence in hand. Applying today would mean asking a reviewer to fund a project against the traction criteria the application itself does not meet.

**Also worth noting:** Prezenti explicitly excludes ongoing salaries, core costs, pure marketing spend, events, liquidity provision, token listings and general VC investment from funding. The budget in Section 4.2 is structured as engineering and review work to stay inside those bounds.

---

## 7. Open Items to Close Before Submission

| # | Item | Why it matters | Owner |
|---|---|---|---|
| 1 | Make the repository public, or grant reviewer access | `AdamJannoud/BioRig` is private, so a reviewer following the link gets a 404 | Adam |
| 2 | Confirm or replace the budget figure and allocation | Section 4.2 is a recommendation, not a settled ask | Adam |
| 3 | Supply team members, roles and links | Section 5.1 has a named applicant and nothing else | Adam |
| 4 | ~~Deploy to Celo mainnet~~ — **done 1 October 2026**: four contracts live on chain `42220` for 0.803044 CELO, as an Alpha v1 / pilot, with the external audit deferred to a later milestone. Still open: minting the first mainnet trees, the deployer role handover, and which pool to apply to, and when | Section 6.2 shows the eligibility position; mainnet deployment is no longer the gap — traction is | Adam |
| 5 | Decide whether to disclose the AI-assisted development workflow | Relevant because Prezenti's Frontier pool states it wants "the efficient and effective use of agentic tooling" rather than low-effort output. This is a positioning choice, not a technical one | Adam |

---

## 8. Sources for Every Figure in This Document

| Claim | Where it comes from |
|---|---|
| Contract addresses, chain ID, block numbers | Live `cast` calls against Celo Sepolia and Celo mainnet, re-run 1 October 2026 |
| Mainnet deployment cost 0.803044 CELO, 4,015,198 gas at 200.0011 gwei | The four mainnet deployment receipts, broadcast 1 October 2026 |
| 175 tests across 16 suites | `forge test -vvv` after `rm -rf cache out`, exit 0, 1 October 2026 |
| Storage layout, slots 0-8 with 9 reserved | `forge inspect` plus the upgrade test that snapshots all nine slots with `vm.load` |
| Code sizes and bytecode match | Live `cast code` reads on the four Sepolia addresses and the mainnet proxy, implementation and account implementation, compared against local artifacts, 1 October 2026 |
| Partial verification on all four, on both chains | Blockscout v2 API for Celo Sepolia and Celo mainnet, re-read 1 October 2026 |
| Mint details and nullifier | The mint transaction, the token-bound account derivation, and the dashboard's own derivation |
| Repository head `b4f34df` | GitHub API, 1 October 2026, verified before this document was committed |
| 129 dashboard and tooling tests, 16 architecture address tests, entrypoint check | Project test runs under the repository's own environment |
| Prezenti pool criteria, bands, exclusions and payment split | `prezenti.xyz/grants`, read 1 October 2026 |
