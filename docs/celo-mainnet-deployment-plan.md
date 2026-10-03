# BioRig — Celo Mainnet Deployment Plan

**Prepared 1 October 2026, refreshed 3 October 2026** · target **Celo mainnet, chain id 42220** · deployed, handed over and minted on 1 October 2026
Every figure below was re-derived on 3 October 2026, from the committed broadcast records, the repository at `61bb478` (its head while the audit ran; five commits have landed since, `c30898a` through `079c725` and this edition's own branding-sweep commit on top, all in the carrier record and its gate, and none of them changes a figure below) and read-only calls against the live chain, not carried from the 1 October text. The source table at the end names the command behind each one.

**Recommendation in one line:** the on-chain cost turned out as trivial as forecast (0.803044 CELO for the deployment and 1.016 CELO for everything the deployer key has sent, about 10 US cents at today's price), so cost was never what gated this, and the deployment, the Safe owner swap, the role handover and the first tree have all run. Of the three things that had to be right before mainnet, two are settled: the test suite is chain-agnostic (the refactor landed on 1 October 2026 in commits `c4470c8` to `a404bc6`, and the 1 October text's `35874ce` no longer resolves after that day's history rewrite), and a Safe, not the hot key, now holds `DEFAULT_ADMIN_ROLE` and `UPGRADER_ROLE`. The third, an external audit of `BioRigCoreV5` and the vendored ERC-6551 account implementation, did **not** happen first; it was recorded as a later grant milestone rather than a gate on the pilot, so the contract is live unaudited. What is genuinely still open is smaller and mostly a Safe transaction away: move `VERIFIER_ROLE` off the deployer hot key onto a dedicated key, move `bufferPool` off it too, set a base URI, and have the audit done before anything that moves value is switched on.

## 1. Where things stand

| | Celo Sepolia (live) | Celo mainnet (live) |
|---|---|---|
| chain id | 11142220 | 42220 |
| BioRig contracts | deployed 30 September 2026: proxy `0x21ab8B36177F65ce69e04E281E4aFf3Db6b5f7E6`, block 37511856 | **deployed 1 October 2026**: proxy `0x04Db169dDF8AbB80943161C01B2a71DC40384E64`, block 78935900, implementation `0xdb3a450b85D48E6e6552dB2b32aD75a7ac590c60`, account implementation `0x65D18C960170ca2B4936c62945bA0e827e5cCd2B` |
| canonical ERC-6551 registry | deployed by us through Nick's factory | already on chain, reused: the broadcast holds no CREATE2 |
| `DEFAULT_ADMIN_ROLE`, `UPGRADER_ROLE` | still the deployer, `0xb5aB2054b43040593805Cf662A938eFE924F2778` | the Safe `0x3B36b3446fCB0729B0046520156933E56352D551` |
| `VERIFIER_ROLE` (minting) | the deployer | the deployer hot key `0x1DB0084Db70bF8D0E06c1785D693Fc6a95317890` |
| trees | one (token 1, bare-salt nullifier) | one (token 1, H3-derived nullifier); `getTreeStats(2)` reverts `InvalidTree` |
| gas price at read time | not re-read | 202.5 gwei (base fee 200, priority fee 2.5) |

Mainnet reads, 3 October 2026: chain id 42220, block 79,127,834 (11:56:32 UTC), base fee 200 gwei, gas price 202.5 gwei, max priority fee 2.5 gwei. CELO at $0.098586. The proxy holds 163 bytes of code, its ERC-1967 implementation slot resolves to `0xdb3a450b85D48E6e6552dB2b32aD75a7ac590c60`, and `paused()` is `false`.

Who holds what on mainnet, read with `hasRole` on the proxy for each holder and each role:

| Holder | `DEFAULT_ADMIN_ROLE` | `UPGRADER_ROLE` | `VERIFIER_ROLE` |
|---|---|---|---|
| Safe `0x3B36b3446fCB0729B0046520156933E56352D551` | **true** | **true** | false |
| deployer hot key `0x1DB0084Db70bF8D0E06c1785D693Fc6a95317890` | false | false | **true** |
| Safe owner `0xD314e37FD8538fe66231EE670B74C9428d03feEa` | false | false | false |

The Safe is 1-of-1: `getOwners()` returns `[0xD314e37FD8538fe66231EE670B74C9428d03feEa]`, `getThreshold()` 1, `nonce()` 1, and the deployer key is not an owner. `bufferPool()` still returns the deployer hot key.

What has happened, each against its record:

| Date (UTC) | What | Record |
|---|---|---|
| 1 Oct 05:47:27, block 78,932,889 | deployer key funded with **4 CELO** | on chain only: the deployer's first incoming transaction, `0x98a7fdf5…f8bc346`; no repo record |
| 1 Oct 06:37:38, block 78,935,900 | `DeployAll`: account implementation, `BioRigCoreV5`, proxy, `grantRole(VERIFIER_ROLE)` — four transactions, every receipt `0x1`, 4,015,198 gas, 0.803044 CELO at 200.0011 gwei | `broadcast/DeployAll.s.sol/42220/run-latest.json`, recorded in commit `0089f90` |
| 1 Oct 06:38–06:44 | all four contracts verified on Blockscout (partial match) | `/api/v2/smart-contracts/{address}` on <https://celo.blockscout.com>, read today |
| 1 Oct 19:30 and 21:02, blocks 78,982,289 and 78,987,805 | the deployer key created two Safes through `SafeProxyFactory` `0x14F2982D601c9458F93bd70B218933A6f8165e7b`: `0x3B36b3446fCB0729B0046520156933E56352D551` and `0xe7042bC31A13E4FD2D5C4176ec52D28907E1311E`, each with the deployer as sole owner | on chain only: deployer nonces 4 and 5; no broadcast record is committed |
| 1 Oct 22:03:35, block 78,991,457 | Safe owner swap: `swapOwner(0x1, deployer, 0xD314e37FD8538fe66231EE670B74C9428d03feEa)` through `execTransaction`, 105,580 gas, 0.021116106 CELO | `broadcast/SafeOwnerSwap.s.sol/42220/run-latest.json`, commit `bf44a17` |
| 1 Oct 22:03:51–22:04:00, blocks 78,991,473 to 78,991,482 | role handover, mode B: Safe granted `UPGRADER_ROLE` then `DEFAULT_ADMIN_ROLE`, deployer renounced `UPGRADER_ROLE` then `DEFAULT_ADMIN_ROLE` — four transactions, 172,420 gas, 0.034484189 CELO | `broadcast/HardenMainnetAdmin.s.sol/42220/run-latest.json`, commit `bf44a17` |
| 1 Oct 22:20:47, block 78,992,489 | first mainnet tree minted from the verifier key: token 1, 270,077 gas, 0.054015697 CELO, tx `0x70476c02ef1af918a213eec63472e6cdbabcedd50193cdd6a7a89a09527797f7` | the receipt on chain; recorded in `DEPLOY.md` section 8 by commit `0dda1c5` |
| 1 Oct 22:44 | the dashboard and diagram default to Celo mainnet | commit `c1eb9dd`; `default_chain_id` 42220 in `dashboard/deployment.json` |

The deployer key's nonce is 12 today: those twelve transactions, and nothing else, are everything it has sent. Its balance is 2.983615 CELO.

The registry check that made the deployment a four-transaction job still holds: `0x000000006551c19487814612e58FE06813775758` holds 571 bytes of code on mainnet with keccak `0xda1d5b06e579f9e42e59b00fbc22939896ecb38dc8830d40de0a2508fecd6735`, the codehash `dashboard/chains.json` records for both chains, and the tree's token-bound account `0x453e89520DB8f374CFCeA95625B99DF5d4F1256A` answers `token()` with `(42220, 0x04Db169dDF8AbB80943161C01B2a71DC40384E64, 1)`.

## 2. What has to change

Most of what this section listed on 1 October has now changed, by running. Each subsection says what happened to its item and what, if anything, is left.

### 2.1 Nothing in the contracts, and nothing in the deploy scripts — confirmed by the run

`script/DeployAll.s.sol` ran on mainnet unchanged, as forecast. The registry step was the no-op it was expected to be: `_deployCanonicalRegistry` returns early when the canonical address already has code, and only then checks that Nick's factory exists (`script/DeployCommon.sol:114-129`). The committed broadcast shows the consequence: four transactions (`CREATE ERC6551Account`, `CREATE BioRigCoreV5`, `CREATE ERC1967Proxy`, `CALL ERC1967Proxy`) and no CREATE2. The proxy ran `initialize` in its constructor, the `VERIFIER_ROLE` grant followed, and every receipt has status `0x1`.

`foundry.toml` still pins no `evm_version`, so solc 0.8.28 targets Cancun by default. The 1 October text left mainnet acceptance of that bytecode to be confirmed; the deployment confirmed it, and the code sizes now on chain match what the proposal records for the compiled artifacts (163 bytes at the proxy).

Nothing in `src/` has changed since. The contract on chain is the contract in the tree.

### 2.2 `.env` — the values the runs used

The mainnet template is now committed as `.env.mainnet.example`, and `tools/test_env_template.py` fails if its network block disagrees with `dashboard/chains.json` or a variable a deploy script requires is missing. Each value below is the one the chain shows was used, not a recollection of the file:

| Key | Celo Sepolia, 30 September | Celo mainnet, 1 October |
|---|---|---|
| `RPC_URL` | `https://forno.celo-sepolia.celo-testnet.org` | `https://forno.celo.org` |
| `CHAIN_ID` | `11142220` | `42220`; the proxy's `chainId()` returns 42220 |
| `VERIFIER` | `blockscout` | `blockscout` (no API key needed) |
| `VERIFIER_URL` | `https://celo-sepolia.blockscout.com/api/` | `https://celo.blockscout.com/api/` |
| `EXPLORER_URL` | `https://celo-sepolia.blockscout.com` | `https://celo.blockscout.com` |
| `PRIVATE_KEY` | testnet deployer | **a newly generated key**, address `0x1DB0084Db70bF8D0E06c1785D693Fc6a95317890`, funded with 4 CELO (the plan asked for about 5) |
| `ADMIN` | the deployer EOA | the deployer EOA, as `_preflightBase` requires; the `initialize` calldata in the broadcast carries `0x1DB0084Db70bF8D0E06c1785D693Fc6a95317890` |
| `ERC6551_REGISTRY` | `0x000000006551c19487814612e58FE06813775758` | same address, reused |
| `ERC6551_IMPLEMENTATION` | `0x3d8a53db1bbcab6d47097b25080527e5560c5165` | not read by `DeployAll`; the run deployed `0x65D18C960170ca2B4936c62945bA0e827e5cCd2B` and passed it to `initialize` |
| `BUFFER_POOL` | `0xb5aB2054b43040593805Cf662A938eFE924F2778` | the deployer `0x1DB0084Db70bF8D0E06c1785D693Fc6a95317890` — **not** the treasury or Safe the plan asked for; still the live value |
| `URI_GENERATOR` | `0x0000000000000000000000000000000000000000` | `0x0`; `uriGenerator()` returns zero, and `setBaseURI` has not been called |
| `SAFE_ADDRESS`, `NEW_OWNER` | — | `0x3B36b3446fCB0729B0046520156933E56352D551` and `0xD314e37FD8538fe66231EE670B74C9428d03feEa`, for the owner swap |
| `NEW_ADMIN` | — | the Safe `0x3B36b3446fCB0729B0046520156933E56352D551`, the address both `grantRole` calls in the handover broadcast name |
| `VERIFIER_ADDRESS` | — | the deployer itself (mode B): no `VERIFIER_ROLE` grant or renounce is in the handover broadcast, and the deployer still holds the role |
| `PROXY_ADDRESS` | `0x21ab8B36177F65ce69e04E281E4aFf3Db6b5f7E6` | `0x04Db169dDF8AbB80943161C01B2a71DC40384E64` |

`ERC6551_REGISTRY` and `ERC6551_IMPLEMENTATION` are still read by `DeployBioRig` only. `DeployAll` took both from its own deployments.

### 2.3 The `initialize()` arguments, and which of them are final

Decoded from the proxy's constructor arguments in `broadcast/DeployAll.s.sol/42220/run-latest.json`, and checked against the live getters:

- **`_defaultAdmin`** — the deployer `0x1DB0084Db70bF8D0E06c1785D693Fc6a95317890`, which received `DEFAULT_ADMIN_ROLE` and `UPGRADER_ROLE`. Both have since moved to the Safe (2.5). The upgrade key for this UUPS contract is now the Safe, and through it the one EOA that owns it.
- **`_implementation`** (the ERC-6551 account implementation) — `0x65D18C960170ca2B4936c62945bA0e827e5cCd2B`, **fixed, no setter.** It is the vendored EIP reference example account, unaudited. The first mint proved it works: the tree's account reports ERC-165 `0x6faff5f1` support and the right `token()`. Changing it now takes a contract upgrade.
- **`_registry`** — the canonical `0x000000006551c19487814612e58FE06813775758`, **fixed, no setter.** Known-good.
- **`_bufferPool`** — the deployer hot key. Has an admin setter, `setBufferPool`, which only the Safe can call now. Open: see section 4, step 9.
- **`_uriGenerator`** — zero, which falls back to the base URI. The base URI is unset, so `tokenURI(1)` returns an empty string today. `setBaseURI` and `setURIGenerator` are admin-only, so this too is a Safe transaction now. Open: step 10.
- **`_chainId`** — 42220, the `0xa4ec` word in the calldata. The tree's account footer carries the same chain id, so mainnet TBAs are bound to mainnet, as intended.

### 2.4 One script edit: the admin cannot be a multisig as written — Option A was taken

The require in `script/DeployCommon.sol:64-73` still insists on `ADMIN == deployer`, and it was not relaxed. The run took **Option A**: deploy with the fresh deployer EOA as `ADMIN`, then hand admin to the Safe. Option B (a Safe as admin from block one) was not built.

The window was not the "few minutes" this section expected. The deployer held `DEFAULT_ADMIN_ROLE` from block 78,935,900 (06:37:38 UTC) until it renounced it in block 78,991,482 (22:04:00 UTC): **15 hours 26 minutes** on a live contract. Two things filled it. The first Safe supplied was owned by the deployer key itself, so handing admin to it would have changed nothing, and the owner swap of 2.5 had to be written and rehearsed first. Nothing went wrong in that window, and the read-back shows the deployer holds neither admin nor upgrade today.

Do not confuse the two "A or B" choices. This section's Option A and B are about who is admin at deployment. `script/HardenMainnetAdmin.s.sol` has its own **mode A and mode B**, about where minting ends up: mode A grants `VERIFIER_ROLE` to a dedicated key and strips it from the deployer, mode B leaves it on the deployer. The handover ran in **mode B**.

### 2.5 The admin handover — written, run, and preceded by a script the plan did not foresee

`script/HardenMainnetAdmin.s.sol` now exists and has run. A second script turned out to be needed first: `script/SafeOwnerSwap.s.sol`, because the Safe supplied for mainnet had the deployer hot key as its sole owner, and the handover's own preflight refuses a `NEW_ADMIN` Safe the deployer can sign for (the ownership walk is `script/SafeOwnershipGuard.sol`, shared by both scripts). `DEPLOY.md` records that both were rehearsed on a fork of mainnet before the broadcast, by `script/safe-owner-swap-fork-check.sh` and `script/handover-fork-check.sh`; no log of those pre-broadcast rehearsals is committed, but both harnesses are now step 4b of `scripts/verify-demo.sh` and replay the two operations on every gate run.

What ran, in order, every receipt status `0x1`:

| # | Call | Block | Gas | Record |
|---|---|---|---|---|
| 7a | Safe `execTransaction` carrying `swapOwner(0x1, 0x1DB0084Db70bF8D0E06c1785D693Fc6a95317890, 0xD314e37FD8538fe66231EE670B74C9428d03feEa)` | 78,991,457 | 105,580 | `broadcast/SafeOwnerSwap.s.sol/42220/run-latest.json` |
| 7b.1 | `grantRole(UPGRADER_ROLE, Safe)` | 78,991,473 | 56,613 | `broadcast/HardenMainnetAdmin.s.sol/42220/run-latest.json` |
| 7b.2 | `grantRole(DEFAULT_ADMIN_ROLE, Safe)` | 78,991,476 | 56,229 | same |
| 7b.3 | `renounceRole(UPGRADER_ROLE, deployer)` | 78,991,478 | 29,981 | same |
| 7b.4 | `renounceRole(DEFAULT_ADMIN_ROLE, deployer)` | 78,991,482 | 29,597 | same |

Against the six steps this section listed: steps 1, 2, 5 and 6 ran in that order; steps 3 and 4 (grant `VERIFIER_ROLE` to a verifier key, renounce it from the deployer) did **not** run, because mode B leaves minting on the deployer. Both grants landed before either renounce, so the proxy was never without a `DEFAULT_ADMIN_ROLE` holder. Steps 3 and 4 are still to do, now as Safe transactions rather than deployer ones (section 4, step 8).

### 2.6 Twenty-two tracked files still name Sepolia, all deliberately

The chain-agnostic refactor moved chain selection into `dashboard/chains.json` plus the multi-chain `dashboard/deployment.json`, with `CHAIN_ID` as the override, so no runtime path resolves a chain from a literal any more. The same search as on 1 October (the Sepolia chain id, the Sepolia proxy, the Sepolia explorer host, the Sepolia deploy block) now matches 29 tracked files. Seven are logs and broadcast artifacts under `evidence/` and `broadcast/`. The other twenty-two are below; each names Sepolia because it records, selects or tests the testnet deployment, not because it is pinned to it:

| File | Matches | Why it names Sepolia |
|---|---|---|
| `DEPLOY.md` | 13 | the dual-chain network table and the executed Sepolia deployment (section 6) |
| `dashboard/test_config.py` | 13 | tests parameterised over both chains |
| `docs/prezenti-proposal.md` | 9 | the Sepolia deployment recorded beside the mainnet one |
| `.env.example` | 5 | the template deliberately ships Celo Sepolia's network block, so a copied `.env` never aims at mainnet |
| `README.md` | 5 | both live deployments |
| `tools/demo_facts.json` | 5 | the Sepolia demo tree the explainer renders |
| `DEMO.md` | 3 | the explainer was rendered against Sepolia |
| `DEPLOY_DASHBOARD.md` | 3 | how to select Sepolia with `CHAIN_ID` |
| `dashboard/chains.json` | 3 | Sepolia's registry entry |
| `dashboard/deployment.json` | 3 | Sepolia's record beside mainnet's |
| `dashboard/test_chain_format.py` | 2 | TBA derivation tested per chain |
| `mobile/android/core/src/test/resources/golden/vectors.json` | 2 | a golden checksum vector for the Sepolia proxy address |
| `relay/tests/test_config.py` | 2 | the relay's chain override, tested |
| `tools/test_architecture.py` | 2 | asserts the diagram does **not** render Sepolia |
| `FINDINGS.md` | 1 | the Sepolia deployment record |
| `dashboard/README.md` | 1 | how to point the dashboard at Sepolia |
| `mobile/android/tools/gen_golden.py` | 1 | the source of that golden vector |
| `relay/README.md` | 1 | `RELAY_CHAIN_ID=11142220` as a testnet example |
| `relay/tests/test_plot_index.py` | 1 | a testnet relay rig |
| `script/handover-fork-check.sh` | 1 | a wrong-`CHAIN_ID` guard that must refuse |
| `script/safe-owner-swap-fork-check.sh` | 1 | the same guard |
| `scripts/check_dashboard_ui.py` | 1 | the known tree-1 TBA, kept per chain |

The repository side of the old 2.6 is therefore done. On the same search, `42220` appears in 50 tracked files.

### 2.7 The test suite — parameterised, and green against the mainnet record

Done before the deployment, as this section asked. The suites now read the expected chain, proxy and block from configuration and cover the real mainnet entry. Re-run in this checkout on 3 October 2026:

- `forge test` — **181 passed, 0 failed**, 17 suites
- `pytest dashboard tools relay` — **440 passed**, covering every chain in `dashboard/chains.json`
- `pytest dashboard tools relay --chain-id 42220` — **412 passed**, with the dashboard's chain-parameterised tests narrowed to mainnet

Nothing was loosened to get there: the dashboard tests check that a chain is recorded exactly when its broadcast is committed, with that broadcast's proxy and block.

## 3. Cost

### 3.1 Gas, measured

On 1 October this table was the Sepolia receipts, on the argument that the same bytecode costs the same gas. Now it can be the mainnet receipts themselves, and the argument held to within 12 gas:

| Step | Gas on Celo Sepolia | Gas on Celo mainnet |
|---|---|---|
| canonical registry via Nick's factory | 177,170 | — **skipped**, code already there |
| ERC-6551 account implementation | 626,504 | 626,504 |
| `BioRigCoreV5` implementation | 2,942,890 | 2,942,890 |
| ERC1967Proxy, including `initialize` in its constructor | 389,203 | 389,191 |
| `grantRole(VERIFIER_ROLE)` | 56,613 | 56,613 |
| **deployment total** | — | **4,015,198** (forecast 4,015,210) |
| Safe owner swap | — | 105,580 |
| role handover, mode B, four transactions | — | 172,420 |
| one `mintTree` | 267,565 | 270,077 (the first mainnet tree) |

The proxy's 12 gas difference is in the constructor calldata, which is priced per byte: 4 gas for a zero byte, 16 for a non-zero one. The likeliest cause is the chain id argument, where Sepolia's `0xaa044c` has one more non-zero byte than mainnet's `0xa4ec`.

### 3.2 What it cost, and what the next trees cost

Every mainnet transaction above ran at 200.001 to 200.0011 gwei effective. The spend, from the receipts:

- **Deployment: 0.803044 CELO** (forecast 0.8131 at 202.5 gwei; it ran at the 200 gwei base fee with almost no tip)
- **Safe owner swap: 0.021116 CELO**
- **Role handover: 0.034484 CELO** (`DEPLOY.md` section 8 prints 0.034483190; the four receipts sum to 0.034484189)
- **First tree: 0.054016 CELO**
- **Total in the committed records: 0.912660 CELO** for ten transactions
- **Two Safe creations** the deployer key also sent, readable on chain but not in any committed record: 259,305 and 259,317 gas, 0.103725 CELO together
- **Everything the deployer key has sent: 1.016385 CELO ≈ $0.10** at CELO $0.098586

Forward, at today's 202.5 gwei: `eth_estimateGas` for a `mintTree` from the verifier key to a planter that holds no tree yet, with a fresh nullifier, returns **279,544 gas**, so

- **One tree: 0.0566 CELO ≈ $0.0056**
- **One hundred trees: 5.66 CELO ≈ $0.56**

The deployer key was funded with 4 CELO, not the 5 this section recommended, and it was enough: nothing ran short mid-sequence. It holds **2.983615 CELO** today, about 52 mints at that estimate. In mode B it is still the key that mints, so that balance is the minting budget until a dedicated verifier key exists.

### 3.3 The L1 data fee, which Celo is not charging — now measured on mainnet

The 1 October text could only point at Sepolia receipts and an inconclusive mainnet oracle probe. Mainnet receipts settle it: `l1Fee` is **zero** on all ten mainnet transactions in the committed records and the mint (the four deployment receipts, the swap, the four handover receipts and the mint), with `l1GasUsed` non-zero, from 1,600 to 117,392. The mainnet GasPriceOracle reports `l1BaseFee` of 61,287,715 wei today. Budget execution gas only.

### 3.4 The cost that actually matters

Still an external audit of `BioRigCoreV5` and the vendored ERC-6551 account implementation, and still unpriced: it needs quotes. What changed is its place in the sequence. The runbook approved on 1 October (`DEPLOY.md` section 8) records the deployment as "Alpha v1 / pilot" with the external audit as a later grant milestone, not a gate, so the audit now gates the value-bearing work (reward routing out of the token-bound accounts) rather than the deployment. Everything else is still free at this scale: Blockscout verification needed no key, `forno.celo.org` is a free public RPC, and the dashboard is hosted for nothing. A paid RPC endpoint remains optional.

## 4. Steps

Steps 0 to 7 are the 1 October sequence, each with what actually happened. Steps 8 onward are what is genuinely still open.

**Step 0 — preflight. Done, with one gap in the record.** A fresh deployer key was used (`0x1DB0084Db70bF8D0E06c1785D693Fc6a95317890`, nonce 0 at the deployment) and funded with 4 CELO at block 78,932,889, fifty minutes before the broadcast. The committed runbook (`DEPLOY.md` section 8, step 0 and step 4) has the fork rehearsal and the no-broadcast simulation as its first steps and says they ran, but neither run's log is committed (`cache/` and `broadcast/**/dry-run/` are git-ignored), so this plan cannot show the simulation output.

**Step 1 — deploy. Done.** `DeployAll` broadcast four transactions in block 78,935,900, every receipt `0x1`. The proxy is `0x04Db169dDF8AbB80943161C01B2a71DC40384E64`. The script's read-back assertions run inside the same command, and the live getters agree with them today: the implementation slot holds `0xdb3a450b85D48E6e6552dB2b32aD75a7ac590c60`, `erc6551Registry()` and `erc6551Implementation()` return the canonical registry and `0x65D18C960170ca2B4936c62945bA0e827e5cCd2B`, `chainId()` 42220, `bufferPool()` the deployer, `uriGenerator()` zero, `paused()` false.

**Step 2 — verification. Done.** Read from the explorer's own API, not the submission exit code: all four contracts report `is_verified: true` and `is_partially_verified: true`, `is_fully_verified: false`, verified between 06:38:11Z and 06:44:13Z on 1 October. The partial match Sepolia recorded is what mainnet recorded too, as expected. A full match would still need Sourcify or a reproduction of the metadata hash, and nothing depends on it.

**Step 3 — hand the contract over. Done, in mode B, after an owner swap.** See 2.5 for the five transactions. The Safe holds admin and upgrade, the deployer holds only `VERIFIER_ROLE`, the Safe's owner holds nothing on the proxy. The `VERIFIER_ROLE` move that this step originally included is step 8 below.

**Step 4 — record it in the repo. Done.** The broadcast records and `dashboard/deployment.json` were committed in `0089f90` and `bf44a17`, the mint in `0dda1c5`, and the switch of the default chain to mainnet in `c1eb9dd`. The suites are green against that record (2.7).

**Step 5 — mint the first real tree. Done.** From the verifier key, not the dashboard. `getTreeStats(1)` returns dbh 10, biomass 20, timestamp 1790893247, account `0x453e89520DB8f374CFCeA95625B99DF5d4F1256A`, alive, and the nullifier `0xb7a55a6b1b7e4fe0fba76f303772cba7fdf3715d4030e3fcd91ed297c756d741`, which is the H3 derivation from `dashboard/h3_nullifier.py` for the demo plot, not a bare salt. `isNullifierActive` returns `true` for it, and an `eth_call` of `mintTree` reusing it reverts with selector `0xc24c608f`, `NullifierInUse()`. dbh 10 and biomass 20 are placeholder values, not field measurements.

**Step 6 — re-point the dashboard. Done in the repo; the hosted instance was not re-checked in this run.** `dashboard/deployment.json` has `default_chain_id` 42220, so a dashboard started with no `CHAIN_ID` renders mainnet. One correction to the 1 October text: `ALLOW_MINT` does **not** stay off by default. `dashboard/config.py` reads it with `_flag(env.get("ALLOW_MINT"), True)`, so an unset flag means minting is on; only an unrecognised value fails closed. A public deployment must set `ALLOW_MINT = false` explicitly, as `DEPLOY_DASHBOARD.md` says. Whether the hosted instance's secrets do so, and whether they hold a key at all, cannot be read from the repository.

**Step 7 — the grant application. Done for the deployment gate; the traction gate is open.** `docs/prezenti-proposal.md` carries the mainnet addresses, the four transaction hashes with explorer links and the first mainnet tree. One tree is not traction.

**Step 8 — move minting to a dedicated key. Open, and first.** The Safe sends `grantRole(VERIFIER_ROLE, new key)` and then `revokeRole(VERIFIER_ROLE, 0x1DB0084Db70bF8D0E06c1785D693Fc6a95317890)`, through the Safe app, signed by the Safe's owner. No new handover script is needed: the Safe already holds `DEFAULT_ADMIN_ROLE`. The relay (`relay/README.md`) is built to be that key's only holder and refuses to start unless its signer holds the role, so this has to come before the relay mints anything on mainnet; otherwise the relay would run on the deployer key on an internet-facing host. Fund the new key for the batch (3.2). Done when `hasRole` reads `false` for the deployer and `true` for the new key, and the new key holds nothing else.

**Step 9 — move `bufferPool` off the deployer. Open.** The Safe calls `setBufferPool` with the treasury or Safe address the plan intended. Nothing routes value to `bufferPool` yet, so this is hygiene before the reward flows, not an emergency.

**Step 10 — set the base URI. Open.** `tokenURI(1)` is empty today. The Safe calls `setBaseURI` (or `setURIGenerator` with a contract that has code). Wallets and explorers show the tree with no metadata until then.

**Step 11 — put the relay into service. Open.** `relay/README.md` names the two remaining steps: phase 4 moves the dashboard's own signing onto the relay and deletes the dashboard's key path, phase 5 is one live registration on mainnet read back from the chain. After step 8.

**Step 12 — the audit, before anything moves value. Open.** As 3.4: the reward flows out of the token-bound accounts are not implemented, and they should not be switched on unaudited.

Check the end state of steps 8 to 10 from the chain, read-only:

```bash
cast call 0x04Db169dDF8AbB80943161C01B2a71DC40384E64 'hasRole(bytes32,address)(bool)' "$(cast keccak VERIFIER_ROLE)" 0x1DB0084Db70bF8D0E06c1785D693Fc6a95317890 --rpc-url https://forno.celo.org   # false once step 8 is done
cast call 0x04Db169dDF8AbB80943161C01B2a71DC40384E64 'bufferPool()(address)' --rpc-url https://forno.celo.org          # no longer 0x1DB0... once step 9 is done
cast call 0x04Db169dDF8AbB80943161C01B2a71DC40384E64 'tokenURI(uint256)(string)' 1 --rpc-url https://forno.celo.org   # non-empty once step 10 is done
```

## 5. Risks

- **Mainnet is irreversible and the contract is unaudited — and now live.** This risk was accepted rather than mitigated: the deployment went ahead as a pilot with the audit deferred ([3.4](#34-the-cost-that-actually-matters)). What still bounds it: the contract is pausable and UUPS-upgradeable, and both powers now sit with the Safe rather than a hot key; it holds one tree and routes no value. Keep it that way until the audit (step 12).
- **A hot key held admin during the deployment window — closed.** The window was 15 hours 26 minutes, not a few minutes ([2.4](#24-one-script-edit-the-admin-cannot-be-a-multisig-as-written--option-a-was-taken)), and it ended at block 78,991,482. The deployer holds neither `DEFAULT_ADMIN_ROLE` nor `UPGRADER_ROLE` today.
- **The hot key still mints.** Mode B left `VERIFIER_ROLE` on the deployer key, and it is still the `bufferPool` address. A compromised key can mint, update and kill trees (`mintTree`, `updateTreeGrowth`, `reportMortality`); it cannot upgrade, pause or grant roles. Mitigation: step 8, then step 9. This is the one residual risk mode B chose deliberately.
- **Custody is one EOA.** The Safe is 1-of-1, threshold 1, and its sole owner is the EOA `0xD314e37FD8538fe66231EE670B74C9428d03feEa`. Whoever holds that key can upgrade the contract. That is a large improvement on a hot key that also signs every deployment transaction, but it is not multi-party control. Mitigation: add owners and raise the threshold in the Safe app before the contract holds anything of value.
- **`VERIFIER_ROLE` is an off-chain convention.** Unchanged. `mintTree` rejects `bytes32(0)` and enforces uniqueness through `_activeNullifiers` (a reused nullifier reverts `NullifierInUse`, read today against the live tree), but nothing on chain requires the H3 res-12 derivation. The relay now derives the nullifier itself rather than accepting one from the client, which narrows this in practice once it is the only signer. Mitigations: keep the verifier key off the public dashboard, watch `TreeMinted` events, consider enforcing the derivation in a later upgrade.
- **The vendored ERC-6551 account implementation is unaudited and final.** It is now `0x65D18C960170ca2B4936c62945bA0e827e5cCd2B`, fixed at `initialize` with no setter. Accepted residual from the audit, still in `FINDINGS.md`: the contract trusts whatever implementation reports ERC-165 support and a `token()`. Mitigation: include it in the audit; replacing it takes an upgrade.
- **Other accepted residuals** carried in `FINDINGS.md` ("Residual trust after hardening"): malformed `uriGenerator` returndata reverts the call, and a return bomb is copied into memory. Neither is a fund-loss path. With `uriGenerator` at zero on mainnet, neither is reachable until step 10 installs a generator.
- **Verification recorded a partial match — as expected.** All four contracts read `is_verified: true`, `is_fully_verified: false`. Nothing depends on a full match.
- **Under-funded deployer mid-sequence — did not happen.** 4 CELO covered twelve transactions with 2.98 CELO left. The same risk now applies to the minting key: fund the dedicated verifier key for the batch before a run of mints.
- **Public RPC for production.** Unchanged: `forno.celo.org` has no SLA. Mitigation: a paid endpoint for the dashboard.
- **A public dashboard that can mint.** Sharper than the 1 October text said: `ALLOW_MINT` defaults to on when unset (step 6). Mitigation: set `ALLOW_MINT = false` explicitly on any public instance, and finish relay phase 4 so the dashboard holds no key at all.
- **Artefacts still show testnet addresses — decided.** The explainer video stays as rendered against Celo Sepolia and is not re-rendered (`DEPLOY.md` section 8, "Explainer"); `DEMO.md` states in its opening paragraph that the video was rendered against Celo Sepolia.
- **Prezenti eligibility is two gates, not one.** Unchanged in substance. The mainnet deployment satisfies the working-mainnet-deployment requirement. It does **not** satisfy the Anchor pool's traction criterion, whose stage bands are keyed to 10K–100K+ daily transactions and which rejects projects "without verifiable traction or credible usage evidence", as `docs/prezenti-proposal.md` section 6 quotes it; one tree is not traction. Be straight about that in the application.

## 6. What I could not establish

Three of the four items the 1 October text left open are now answered: mainnet charges no L1 data fee on these transactions ([3.3](#33-the-l1-data-fee-which-celo-is-not-charging--now-measured-on-mainnet)), Blockscout recorded the same partial match as Sepolia (step 2), and mainnet accepted the Cancun-default bytecode (2.1). What remains, or is new:

- What an audit costs, and what traction Prezenti will actually accept. Both still need a human answer.
- Whether the step-0 fork rehearsal and the no-broadcast simulation produced clean output. `DEPLOY.md` says every runbook step ran; neither log is committed.
- The two Safe creations at deployer nonces 4 and 5 are on chain but in no committed broadcast record, so the scripts or tools that sent them cannot be named from the repository.
- Where the 4 CELO came from is readable on chain (the funding transaction above) but not who controls the sending address; the repository does not record it.
- How the Safe owner key `0xD314e37FD8538fe66231EE670B74C9428d03feEa` is held (hardware wallet or not). `DEPLOY.md` says it is an address Adam Jannoud controls and the hot key does not; the chain can only show that it is an EOA with no code.
- The hosted dashboard's live state: whether it renders mainnet today, whether its secrets set `ALLOW_MINT = false`, and whether they hold a key. None of that is in the repository, and the page was not opened for this refresh.
- The CELO price is a third-party read (CoinGecko), not a chain fact; the dollar figures move with it.

## 7. Where each number came from

Chain reads used `https://forno.celo.org`, the mainnet RPC registered in `dashboard/chains.json`, on 3 October 2026; every one is a read-only `eth_call`, `eth_getStorageAt`, `eth_estimateGas` or receipt lookup, and nothing was signed or sent. Explorer reads used <https://celo.blockscout.com>. Commands are shown with the RPC flag omitted where it is the only argument left out.

| Figure | Source |
|---|---|
| chain id 42220, block 79,127,834, block time | `cast chain-id`, `cast block-number`, `cast block 79127834 --field timestamp` |
| 200 gwei base fee, 202.5 gwei gas price, 2.5 gwei priority fee | `cast base-fee`, `cast gas-price`, `cast rpc eth_maxPriorityFeePerGas` |
| proxy code 163 bytes, implementation `0xdb3a450b…0c60` | `cast codesize 0x04Db169dDF8AbB80943161C01B2a71DC40384E64`; `cast storage` on the proxy at the ERC-1967 slot `0x360894a13ba1a3210667c828492db98dca3e2076cc3735a920a3ca505d382bbc` |
| the role table in section 1 | `cast call 0x04Db169dDF8AbB80943161C01B2a71DC40384E64 'hasRole(bytes32,address)(bool)'` for each of the three holders and each role (`DEFAULT_ADMIN_ROLE` is the zero hash, the other two `cast keccak UPGRADER_ROLE` and `cast keccak VERIFIER_ROLE`) |
| Safe owners, threshold 1, nonce 1 | `cast call 0x3B36b3446fCB0729B0046520156933E56352D551` with `'getOwners()(address[])'`, `'getThreshold()(uint256)'`, `'nonce()(uint256)'` |
| `paused()`, `bufferPool()`, `uriGenerator()`, `chainId()`, `erc6551Registry()`, `erc6551Implementation()`, empty `tokenURI(1)` | `cast call` on the proxy for each getter |
| tree 1 stats and owner; no tree 2; nullifier active | `cast call` with `'getTreeStats(uint256)((uint96,uint96,uint64,address,bool,bytes32))' 1`, `'ownerOf(uint256)(address)' 1`, `getTreeStats` of 2 (reverts `0xf0352c1b`, `cast sig 'InvalidTree()'`), `'isNullifierActive(bytes32)(bool)'` |
| reusing the nullifier reverts `NullifierInUse()` | `cast call` of `mintTree` with tree 1's nullifier and `--from 0x1DB0084Db70bF8D0E06c1785D693Fc6a95317890`: reverts `0xc24c608f`, `cast sig 'NullifierInUse()'` |
| TBA `token()` = `(42220, proxy, 1)` | `cast call 0x453e89520DB8f374CFCeA95625B99DF5d4F1256A 'token()(uint256,address,uint256)'` |
| registry 571 bytes, keccak `0xda1d5b06…d6735` | `cast codesize` and `cast keccak` of `cast code 0x000000006551c19487814612e58FE06813775758` |
| deployment, swap and handover: transactions, blocks, gas, prices, CELO | the `receipts` of `broadcast/DeployAll.s.sol/42220/run-latest.json`, `broadcast/SafeOwnerSwap.s.sol/42220/run-latest.json` and `broadcast/HardenMainnetAdmin.s.sol/42220/run-latest.json` (`gasUsed` times `effectiveGasPrice`, summed) |
| `initialize` arguments | the proxy transaction's `arguments` in `broadcast/DeployAll.s.sol/42220/run-latest.json` |
| block times | `cast block` with `--field timestamp` for 78935900, 78991457 and 78992489 |
| first mint: 270,077 gas, 0.054015697 CELO | `cast receipt 0x70476c02ef1af918a213eec63472e6cdbabcedd50193cdd6a7a89a09527797f7 --json` |
| `l1Fee` zero, `l1GasUsed` 1,600 – 117,392 | `cast receipt --json` on the nine broadcast transactions and the mint |
| `l1BaseFee` 61,287,715 wei | `cast call 0x420000000000000000000000000000000000000F 'l1BaseFee()(uint256)'` |
| next mint 279,544 gas | `cast estimate` of `mintTree(address,bytes32,uint96,uint96)` on the proxy, planter `0x1111111111111111111111111111111111111111` (no code, no tree), nullifier `cast keccak plan-refresh-probe-2026-10-03`, stats 10 and 20, `--from` the deployer |
| deployer nonce 12, balance 2.983615 CELO, funded with 4 CELO | `cast nonce` and `cast balance --ether` on the deployer; `cast balance --ether --block 78935899` reads 4.0 |
| the deployer's twelve transactions, the funding and the two Safe creations | <https://celo.blockscout.com/api/v2/addresses/0x1DB0084Db70bF8D0E06c1785D693Fc6a95317890/transactions>, and `cast receipt` on the two `createProxyWithNonce` transactions for the Safe each created |
| verification status and times | <https://celo.blockscout.com/api/v2/smart-contracts/0x04Db169dDF8AbB80943161C01B2a71DC40384E64>, and the same for the other three addresses |
| CELO $0.098586 | <https://api.coingecko.com/api/v3/simple/price?ids=celo&vs_currencies=usd>, 3 October 2026 |
| 29 files naming Sepolia, 22 outside `evidence/` and `broadcast/`, per-file counts; 50 naming `42220` | `git grep -liE` and `git grep -ciE` for `11142220`, the Sepolia proxy address, `celo-sepolia.blockscout.com` and `37511856`, excluding `lib`; `git grep -l 42220` |
| record commits | `git log -- broadcast/DeployAll.s.sol/42220`, the same for the other two broadcast directories, and `git log -S` for the mint hash |
| `src/` unchanged since the deployment | `git log --since='2026-10-01 06:00' -- src` prints nothing |
| suite results | `forge test`; `python -m pytest -q dashboard tools relay`; the same with `--chain-id 42220` |
| `ADMIN == deployer` requirement, registry no-op | `script/DeployCommon.sol:64-73` and `:114-129` |
| `ALLOW_MINT` defaults on | `dashboard/config.py`, `_flag` and its `allow_mint` call |

The Python commands assume the virtualenv the README's quick start creates is active.

## 8. Decisions I need from you

Four decisions were asked for on 1 October. All four were taken, and each is recorded:

1. **Option A or B** in 2.4 — **Option A**: the script was not changed, the deployer was admin for the window, then the Safe took over (2.4, 2.5).
2. **Audit before mainnet, or deploy and audit in parallel?** — **Deploy first**: the runbook records the audit as a later grant milestone, not a gate (`DEPLOY.md` section 8).
3. **Re-render the explainer and screenshots, or label them as testnet?** — **Keep the Sepolia render**, not re-rendered (`DEPLOY.md` section 8).
4. **Who holds the verifier key?** — **The deployer key, for now** (handover mode B), with the Safe able to move it at any time.

What is open now:

1. **The dedicated verifier key** (step 8): which key, held where (the relay's secret store is what `relay/README.md` assumes), funded with how much, and on what date the Safe moves the role and revokes the deployer.
2. **Where `bufferPool` should point** (step 9): a treasury address or the Safe itself.
3. **The base URI** (step 10): what metadata a tree should show, and whether that is a static base path or a generator contract.
4. **The Safe's owners and threshold**: stay 1-of-1, or add owners before the contract holds value.
5. **Audit timing**: before relay phase 5 opens mainnet registration to the public, or only before reward routing is built. [Section 4](#4-steps) assumes the latter as the minimum.
