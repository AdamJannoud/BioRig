# Deploying BioRigCoreV5

`script/DeployBioRig.s.sol` deploys the `BioRigCoreV5` implementation, then an OpenZeppelin `ERC1967Proxy` whose
constructor runs `initialize(...)`. The proxy is therefore never live without being initialised. `BioRigCoreV5` is
UUPS: upgrades are gated by `UPGRADER_ROLE` inside the implementation. That means no `TransparentUpgradeableProxy`
and no `ProxyAdmin`.

**Author and sole deployer: Adam Jannoud.** BioRig is his project — the contract, the scripts, the tests and this
runbook — and he is the only account that has ever broadcast a BioRig deployment. Both executed deployments below, Celo
Sepolia (section 6) and Celo mainnet (section 8), were sent by him from a deployer key he controls.

**Networks.** Every chain BioRig targets has one entry in `dashboard/chains.json`: name, RPC, Blockscout explorer and
verifier API, and the canonical ERC-6551 registry with its codehash. The dashboard, the diagram generator, the check
scripts and the shell scripts all read it (`python3 -m dashboard.config chains` lists it), and the deploy scripts
take their explorer links from it. Two chains are registered:

| | Celo Sepolia | Celo mainnet |
| --- | --- | --- |
| chain id | `11142220` | `42220` |
| RPC | `https://forno.celo-sepolia.celo-testnet.org` | `https://forno.celo.org` |
| explorer / verifier | <https://celo-sepolia.blockscout.com>, `/api/` | <https://celo.blockscout.com>, `/api/` |
| BioRig | **live** since 30 September 2026 (section 6) | **live** since 1 October 2026 (section 8) |

Currency is CELO on both. `CHAIN_ID` picks the chain; unset, the tooling uses `default_chain_id` in
`dashboard/deployment.json`, which is Celo Sepolia and where both live chains are recorded. Every deployment input comes
from the environment, so the same
commands work on either chain once `.env` is switched; `python3 -m dashboard.config env --chain-id <id>` prints the
network block for it. Celo Alfajores (`44787`) was shut down and replaced by Celo Sepolia. Its RPC no longer
resolves, so nothing here targets it.

Testnet faucets: <https://faucet.celo.org/celo-sepolia> and the Google Cloud Web3 faucet (Celo Sepolia). The Celo faucet's
browser flow is gated on reCAPTCHA v3 and its unauthenticated API path rejects requests without a captcha token, so
headless callers need either a real browser or a self-serve API key from <https://faucet.celo.org/keys>.

## One command, when the chain has neither prerequisite

On a chain with no ERC-6551 registry and no account implementation — the state Celo Sepolia was in before 30 September
2026, where both now have code (section 6) — `script/DeployAll.s.sol` deploys **all three** in a single broadcast, in
dependency order:

```bash
cp .env.example .env          # PRIVATE_KEY, ADMIN, BUFFER_POOL (the network block ships as Celo Sepolia's)
set -a; source .env; set +a

# dry run: simulates against live chain state, sends nothing
forge script script/DeployAll.s.sol:DeployAll --rpc-url "$RPC_URL"

# broadcast, waiting for each receipt
forge script script/DeployAll.s.sol:DeployAll --rpc-url "$RPC_URL" --broadcast --slow
```

It (1) puts the canonical registry at `0x000000006551c19487814612e58FE06813775758` through Nick's factory, or reuses
it if already present; (2) deploys the reference account implementation and checks it reports ERC-165 `0x6faff5f1`;
(3) deploys the `BioRigCoreV5` implementation and an `ERC1967Proxy` that runs `initialize(...)` in its own constructor;
(4) grants `VERIFIER_ROLE` to `ADMIN`, which `initialize` does not do, and without which `mintTree` reverts. Both
deployed addresses are fed into `initialize` from the deployments themselves, so no environment value can point the
contract at a different registry than the one that run created.

`DeployAll` needs no `ERC6551_REGISTRY` or `ERC6551_IMPLEMENTATION` in `.env`. `DeployBioRig.s.sol` remains the
contract-only path for chains where both already exist.

**`ADMIN` must be the deployer address** for either script: only the holder of `DEFAULT_ADMIN_ROLE` can grant
`VERIFIER_ROLE`, and the scripts refuse to run when `ADMIN` is a different account rather than deploying something
nobody can mint with.

## Deployment is not proof of a working system

`mintTree` calls `erc6551Registry.createAccount(...)`, then validates the returned account. The account must have
code, report ERC-165 support for `0x6faff5f1`, and return a matching `token()`. If the registry or the account
implementation is wrong or has no code, **every mint reverts**, even though the deployment itself succeeds and every
read-back looks fine. On Celo Sepolia before the 30 September 2026 deployment:

| Contract | Address | Celo Sepolia | Celo mainnet |
| --- | --- | --- | --- |
| Canonical ERC-6551 registry | `0x000000006551c19487814612e58FE06813775758` | **no code** | code present |
| Nick's CREATE2 factory | `0x4e59b44847b379578588920cA78FbF26c0B4956C` | code present | code present |
| Tokenbound AccountV3 / AccountV3Upgradable | `0x41C8…44eC` / `0x5526…6E7F` | **no code** | not checked |

Both **no code** cells closed on 30 September 2026: `DeployAll` deployed the canonical registry and the ERC-6551 account
implementation in the same broadcast as BioRig (section 6). The Tokenbound implementations in the third row were never
used; that run deployed the EIP's reference example account instead.

On Celo mainnet the registry's runtime code (571 bytes) has keccak
`0xda1d5b06e579f9e42e59b00fbc22939896ecb38dc8830d40de0a2508fecd6735`, identical to Celo Sepolia's (checked 1 October
2026; `dashboard/chains.json` records it, and `script/fork-dry-run.sh` re-checks it on every run). `DeployAll` therefore
reuses it, and **a mainnet broadcast contains no CREATE2 transaction**: four transactions, not Celo Sepolia's five.

`DeployBioRig` therefore refuses to run unless `ERC6551_REGISTRY` and `ERC6551_IMPLEMENTATION` both have code on
the target chain. It also refuses if a non-zero `URI_GENERATOR` has no code, and if `CHAIN_ID` differs from the RPC's
`eth_chainId`. On Celo Sepolia they are already deployed; on a chain where they are not, deploy the optional
prerequisites below first.

## 0. Setup

```bash
cp .env.example .env          # then edit .env: PRIVATE_KEY, ADMIN, BUFFER_POOL, ERC6551_IMPLEMENTATION, ...
set -a; source .env; set +a   # export every variable into this shell
cast chain-id --rpc-url "$RPC_URL"                       # must print $CHAIN_ID
cast balance "$(cast wallet address --private-key "$PRIVATE_KEY")" --rpc-url "$RPC_URL" --ether
```

`.env` is gitignored. Use a dedicated deployer key that is used for nothing else: a low-value testnet key on Celo
Sepolia, a fresh key on Celo mainnet (section 8). On a fork of Celo Sepolia, the full `DeployBioRig` run was estimated
at about 4.33M gas (~0.33 CELO at the fork's 76.7 gwei max fee). The registry was estimated at about 259k gas. The real
Celo Sepolia `DeployAll` used 4,192,380 gas (section 6); the real Celo mainnet `DeployAll` used 4,015,198 gas and
0.803044 CELO at 200.0011 gwei, with the canonical registry reused rather than deployed (section 8).

## 1. Optional prerequisites: an ERC-6551 registry and account implementation

Skip this on chains where both already exist, such as Celo mainnet for the registry. Check first:

```bash
cast code "$ERC6551_REGISTRY" --rpc-url "$RPC_URL"   # "0x" means absent
```

### 1a. Registry: `script/DeployERC6551Registry.s.sol`

The vendored source is `src/vendor/ERC6551Registry.sol`, taken verbatim from `erc6551/reference` (MIT). In the default
`ERC6551_REGISTRY_MODE=canonical`, the script sends the EIP-6551 canonical creation code through Nick's factory with
the canonical salt. The registry therefore lands at the **canonical address**
`0x000000006551c19487814612e58FE06813775758`, the same as on every other chain, so `ERC6551_REGISTRY` in `.env` does
not change. The script is a no-op if that address already has code. After deploying, it checks that
`account(...)` agrees with an independent CREATE2 derivation. That canonical creation code is byte-identical to the
vendored source compiled with solc 0.8.17 and optimizer 200, apart from the trailing CBOR metadata hash; this was
checked while building this tooling. `ERC6551_REGISTRY_MODE=source` instead deploys the vendored source, as compiled
by this repo, at a fresh address. Use it only where Nick's factory is absent, then set `ERC6551_REGISTRY` to the
printed address.

```bash
# dry run (simulation only)
forge script script/DeployERC6551Registry.s.sol:DeployERC6551Registry --rpc-url "$RPC_URL"
# broadcast
forge script script/DeployERC6551Registry.s.sol:DeployERC6551Registry --rpc-url "$RPC_URL" --broadcast
```

### 1b. Account implementation: `script/DeployERC6551Account.s.sol`

This deploys `src/vendor/ERC6551Account.sol`, the EIP's reference **example** account, taken verbatim from
`erc6551/reference` (MIT). It is unaudited and supports call-only `execute`. Prefer an audited implementation wherever
one is deployed. Set `ERC6551_IMPLEMENTATION` to the printed address.

```bash
forge script script/DeployERC6551Account.s.sol:DeployERC6551Account --rpc-url "$RPC_URL"                 # dry run
forge script script/DeployERC6551Account.s.sol:DeployERC6551Account --rpc-url "$RPC_URL" --broadcast \
  --verify --verifier blockscout --verifier-url "$VERIFIER_URL"                                          # broadcast
```

## 2. Deploy BioRigCoreV5 behind an ERC1967Proxy

```bash
# dry run: simulates against live chain state, sends nothing, prints the read-back summary
forge script script/DeployBioRig.s.sol:DeployBioRig --rpc-url "$RPC_URL"

# broadcast + verify on Blockscout (no API key needed)
forge script script/DeployBioRig.s.sol:DeployBioRig --rpc-url "$RPC_URL" --broadcast \
  --verify --verifier blockscout --verifier-url "$VERIFIER_URL"
```

After deploying, the script reads state back **through the proxy** and `require`s each value. It prints the chain id,
implementation address, proxy address, the ERC1967 implementation slot, `name()`, `symbol()`, every deployment-param
getter, and the admin's `DEFAULT_ADMIN_ROLE` and `UPGRADER_ROLE` membership. **Use the proxy address**; the
implementation is never called directly.

The deployed addresses are also recorded in `broadcast/DeployBioRig.s.sol/$CHAIN_ID/run-latest.json`:

```bash
jq -r '.transactions[] | "\(.contractName) \(.contractAddress)"' broadcast/DeployBioRig.s.sol/$CHAIN_ID/run-latest.json
```

## 3. Verification on Blockscout

The explorer is **Blockscout, not CeloScan or Etherscan**, on both chains. Use `--verifier blockscout` with
`--verifier-url "$VERIFIER_URL"`: `https://celo-sepolia.blockscout.com/api/` on Celo Sepolia,
`https://celo.blockscout.com/api/` on Celo mainnet (`python3 -m dashboard.config get verifier_url` prints the selected
chain's). No API key is needed. `script/verify-retry.sh status` reads `is_verified` for all four contracts of the
selected chain's `DeployAll` broadcast, and `script/verify-retry.sh proxy|core|account|registry` makes one submission
for one of them, with the proxy's constructor arguments taken from the broadcast itself.

What was actually observed (`evidence/blockscout-verify-probe.log`): with no API key set, `forge verify-contract
--verifier blockscout --verifier-url https://celo-sepolia.blockscout.com/api/` against Celo Sepolia was accepted,
returned a GUID, and polled to a final status. This was a deliberate negative control, submitting a source that does
not match the target, and it reported `Fail - Unable to verify` as expected. **No positive verification was observed
at that point, because nothing had been deployed yet.** That changed with the real deployment, and all four contracts
are verified now (sections 6 and 7). Unauthenticated status polling can hit Blockscout's rate limit (`Too many requests`).
If it does, the submission is not lost: re-check it later with `forge verify-check`, shown below.

If `--verify` during the broadcast fails or is rate-limited, verify each contract manually:

```bash
IMPL=0x...    # implementation address from the script output
PROXY=0x...   # proxy address from the script output

# implementation
forge verify-contract "$IMPL" src/BioRigCoreV5.sol:BioRigCoreV5 \
  --chain-id "$CHAIN_ID" --verifier blockscout --verifier-url "$VERIFIER_URL" --watch

# proxy: constructor args are (implementation, initialize calldata) and must match the deployment exactly
INIT_DATA=$(cast calldata "initialize(address,address,address,uint256,address,address)" \
  "$ADMIN" "$ERC6551_REGISTRY" "$ERC6551_IMPLEMENTATION" "$CHAIN_ID" "$BUFFER_POOL" "$URI_GENERATOR")
forge verify-contract "$PROXY" lib/openzeppelin-contracts/contracts/proxy/ERC1967/ERC1967Proxy.sol:ERC1967Proxy \
  --chain-id "$CHAIN_ID" --verifier blockscout --verifier-url "$VERIFIER_URL" \
  --constructor-args "$(cast abi-encode "constructor(address,bytes)" "$IMPL" "$INIT_DATA")" --watch

# re-check a submission later using the GUID it printed
forge verify-check <GUID> --chain-id "$CHAIN_ID" --verifier blockscout --verifier-url "$VERIFIER_URL"
```

**The proxy may need its own handling.** Blockscout's own index shows many `ERC1967Proxy` instances on Celo Sepolia as
verified, such as `0x1a21a117A9Ffb2a043C6Bcf704A2A5A120a2F4a8`. That suggests identical proxy bytecode often matches
already. This deployment's proxy did need its own submission, which the explorer accepted and then completed
asynchronously (section 7); it is verified now. If a proxy page does not show "Read/Write as Proxy"
pointing at the implementation, verify the proxy as above, then use the proxy-detection button on its Blockscout page.

## 4. After deploying: make it usable, then prove it

`initialize` grants no `VERIFIER_ROLE`; the deploy scripts grant it to `ADMIN` (the deployer) in the same broadcast,
which is how the Celo Sepolia deployment minted. On Celo mainnet, `script/HardenMainnetAdmin.s.sol` then moves it to
the dedicated verifier key and strips the deployer (section 8). To grant it to another account by hand:

```bash
cast send "$PROXY" "grantRole(bytes32,address)" "$(cast keccak VERIFIER_ROLE)" <verifier-address> \
  --private-key <ADMIN key> --rpc-url "$RPC_URL"
```

Then mint one tree as the verifier. That is the real end-to-end check of the registry and account implementation:

```bash
cast send "$PROXY" "mintTree(address,bytes32,uint96,uint96)" <planter> "$(cast keccak plot-1)" 10 20 \
  --private-key <VERIFIER key> --rpc-url "$RPC_URL"
cast call "$PROXY" "getTreeStats(uint256)((uint96,uint96,uint64,address,bool,bytes32))" 1 --rpc-url "$RPC_URL"
```

The nullifier in that command is the **bare salt**, `$(cast keccak plot-1)` =
`0xf8fa2658012341dda81dbb7d27a6bb0accd68b63e618001d8ccbed1375dbf667`, and the live tree stored exactly that
value (block `37512380`). It is a deliberate demo mint, not the production derivation. Production derives the
nullifier from the plot's H3 cell at resolution 12 - `keccak256(uint64(h3Cell) ++ utf8(salt))`, implemented in
`dashboard/h3_nullifier.py`; for that same plot and salt it gives
`0xb7a55a6b1b7e4fe0fba76f303772cba7fdf3715d4030e3fcd91ed297c756d741`, which is the value the dashboard
computes, displays and checks for reuse (`tools/demo_facts.json` records both digests side by side: the chain's
under `spatial_nullifier`, the derivation's under `demo_h3`). Neither value is enforced on chain: `mintTree`
stores the 32-byte argument it is given and rejects only `bytes32(0)`, so any deployment relying on the H3
guarantee has to derive it off-chain. Swap the literal for the computed digest to mint a production-style tree.

`mintTree` uses `_safeMint`. A planter with code must implement `onERC721Received`. That includes EOAs with an
EIP-7702 delegation, whose code begins `0xef0100...`. On Celo Sepolia, anvil's well-known test accounts carry exactly
such a delegation, and minting to them reverts.

## 5. Local fork dry run (evidence)

`script/fork-dry-run.sh` starts anvil forked from the selected chain, rehearses the whole deployment and the role
handover against real chain state, and stops anvil on exit. It sends nothing to the real chain, and it files forge's
broadcast logs under `cache/fork-dry-run/`, never under `broadcast/`. `CHAIN_ID` selects the chain and its RPC comes
from `dashboard/chains.json`; a `FORK_URL` argument instead reads the chain id from that RPC, and given both they must
agree. With neither it forks the repo's default chain.

```bash
script/fork-dry-run.sh                        # default chain (Celo Sepolia)
CHAIN_ID=42220 script/fork-dry-run.sh         # Celo mainnet
script/fork-dry-run.sh https://forno.celo.org # the same, chain id read from the RPC
```

`evidence/deploy-fork-dry-run.log` is the Celo Sepolia run from before the 30 September 2026 deployment, kept as the
record of that day; it shows the earlier, shorter script.

> **Every `PRIVATE_KEY` in that script is one of anvil's public dev keys.** They exist only for this local fork dry
> run. Never use one for a broadcast to any real network. Funds sent to them are taken immediately.

The script runs these steps, and checks each step's output as well as its exit status, so a step that passes for the
wrong reason still fails the run:

1. **Registry, either way round.** Where the canonical registry has no code, `DeployBioRig` must be refused by the
   registry guard (`ERC6551_REGISTRY has no code on this chain`). Where it has code (Celo mainnet, and Celo Sepolia
   since 30 September 2026), its codehash must equal the one in `dashboard/chains.json` and the guard must pass.
   `FORK_WIPE_REGISTRY=1` clears the code on the fork first, to rehearse the refusing branch.
2. **Chain-id guard:** `CHAIN_ID=44787` against the fork's RPC must be refused with `CHAIN_ID mismatch`.
3. `DeployERC6551Registry` dry run, which reuses an existing registry instead of redeploying it.
4. Local setup, on the anvil fork only: the registry (if absent) and the example account are broadcast to the fork.
5. `DeployBioRig` dry run: the proxy is deployed and every read-back passes.
6. Fork smoke test: `DeployBioRig` is broadcast to the fork and one tree is minted.
7. **`DeployAll`, the command a real deployment runs**, simulated and broadcast to the fork. The broadcast must
   contain no CREATE2 when the registry already had code, and exactly one when it did not.
   `scripts/record_deployment.py` must accept the artifact (into `cache/`, not `dashboard/deployment.json`).
8. A 1-of-1 Safe (v1.4.1, through the canonical `SafeProxyFactory`) is created on the fork to stand in for the admin
   Safe.
9. **Handover guards:** `HardenMainnetAdmin` must refuse a wrong `CHAIN_ID`, a `VERIFIER_ADDRESS` equal to
   `NEW_ADMIN`, a `NEW_ADMIN` with no code, a contract that is not a Safe, a Safe the deployer owns, and a
   `PROXY_ADDRESS` that is not a BioRig proxy.
10. **Handover:** `HardenMainnetAdmin` is simulated and broadcast to the fork, then every role is read back from the
    fork with `cast`: the deployer holds nothing, the Safe holds admin and upgrader only, the verifier holds
    `VERIFIER_ROLE` only.
11. **After the handover:** the deployer can no longer mint or pause, the verifier key mints a tree whose TBA is bound
    to the fork's chain id, and the Safe pauses the proxy through `execTransaction`.
12. A second `HardenMainnetAdmin` run must be refused: the deployer has nothing left to hand over.

## 6. Executed deployment: Celo Sepolia, 30 September 2026

Run by Adam Jannoud, the project's author and sole deployer, with `DeployAll` exactly as in "One command" above,
plus `--verify --verifier blockscout --verifier-url "$VERIFIER_URL"`. One broadcast, 5 transactions, 4,192,380 gas, 0.2096 CELO at a ~50 gwei base fee. Deployer and
admin were the throwaway account `0xb5aB2054b43040593805Cf662A938eFE924F2778`, with `BUFFER_POOL` the same address and
`URI_GENERATOR` zero.

| Contract | Address | Tx | Gas | Blockscout |
| --- | --- | --- | --- | --- |
| ERC-6551 registry (canonical) | `0x000000006551c19487814612e58FE06813775758` | `0xb8f54434…451320` | 177,170 | verified (partial match) |
| ERC-6551 account implementation | `0x3d8a53dB1bBcab6D47097B25080527e5560C5165` | `0x5abd3074…8c6e99` | 626,504 | verified |
| BioRigCoreV5 implementation | `0x4c998C6553C78bb9d5A67Aac6fBC526d64DBa3a4` | `0x32c7fdff…33199d` | 2,942,890 | verified |
| ERC1967Proxy (the address to use) | `0x21ab8B36177F65ce69e04E281E4aFf3Db6b5f7E6` | `0xdcf0dd8b…39184e` | 389,203 | verified |
| `grantRole(VERIFIER_ROLE, admin)` | `0x21ab8B36…f7E6` | `0x9a004384…6e0203` | 56,613 | — |

A deployment that only reads back correctly is still not proof the system works, so one tree was minted: `mintTree`,
tx `0x486bc529…4b9d5f9e`, 267,565 gas.

```bash
cast call "$PROXY" "ownerOf(uint256)(address)" 1     # 0xb5aB2054b43040593805Cf662A938eFE924F2778
cast call "$PROXY" "totalSupply()(uint256)"          # 1
cast call "$PROXY" "getTreeStats(uint256)((uint96,uint96,uint64,address,bool,bytes32))" 1
```

Tree 1's token-bound account is `0x61bd8BEcE5a38209Fc10d4DA3f837EE83a10124a`. Its code is an ERC-1167 minimal proxy
to the account implementation, it reports ERC-165 `0x6faff5f1`, and its `token()` returns `(11142220,
0x21ab8B36177F65ce69e04E281E4aFf3Db6b5f7E6, 1)`, so the registry and account path genuinely works on this chain.

Both contracts that were still unverified when the broadcast ended are now verified:

- **The proxy.** Its submission during the broadcast hit the rate limit (`status=0, Too many requests`), but Blockscout
  verifies asynchronously and the accepted submission completed anyway. The command used for it, reusable for any
  future proxy, is:
  ```bash
  ARGS=$(cast abi-encode "f(address,bytes)" 0x4c998C6553C78bb9d5A67Aac6fBC526d64DBa3a4 "$(cast calldata \
    'initialize(address,address,address,uint256,address,address)' 0xb5aB2054b43040593805Cf662A938eFE924F2778 \
    0x000000006551c19487814612e58FE06813775758 0x3d8a53dB1bBcab6D47097B25080527e5560C5165 11142220 \
    0xb5aB2054b43040593805Cf662A938eFE924F2778 0x0000000000000000000000000000000000000000)")
  forge verify-contract 0x21ab8B36177F65ce69e04E281E4aFf3Db6b5f7E6 \
    lib/openzeppelin-contracts/contracts/proxy/ERC1967/ERC1967Proxy.sol:ERC1967Proxy \
    --verifier blockscout --verifier-url "$VERIFIER_URL" --chain 11142220 --constructor-args "$ARGS"
  ```
- **The canonical registry** is verified as a **partial match** (2026-09-30 19:39:04 UTC), resolved by Blockscout's
  Ethereum Bytecode Database, which matches an unverified contract on the executable part of its bytecode and ignores
  metadata. A full match is still out of reach from here: on chain it is the EIP-6551 canonical creation code compiled
  with solc 0.8.17, this repo compiles the vendored source with solc 0.8.28, and the original file that would reproduce
  the metadata hash is not available. Its behaviour is proven independently anyway: `DeployAll` checks `account()`
  against a CREATE2 derivation before broadcasting, and a real tree was minted through it.

## 7. Verification outcome

Final state, read from the explorer's own API (`/api/v2/addresses/{address}`) rather than from the
verification call's exit status:

| Contract | `is_verified` |
| --- | --- |
| canonical ERC-6551 registry | true (partial match) |
| ERC1967Proxy | true |
| BioRigCoreV5 implementation | true |
| ERC-6551 account implementation | true |

The proxy's first submission returned `Too many requests` and looked like a failure, but Blockscout
verifies asynchronously: the submission was accepted and completed after the client had stopped
polling. Read `is_verified`, not the submission's exit code.

Blockscout's unauthenticated v1 API allows **10 requests per window**, with the window length in the
`x-ratelimit-reset` header in milliseconds (about 30 minutes). The first version of
`script/verify-retry.sh` looped six attempts, each of which forge retries three times internally, so
one burst spent the whole window and every attempt after it got a 429. The rewrite does a single
attempt per run and reads status through the v2 API, which is not quota-limited.

The registry's own obstacle was the metadata hash, which no amount of quota would have fixed. Compiling
the vendored source with the settings the canonical deployment used, recovered from Blockscout's record
of the same contract on Ethereum mainnet (`ERC6551Registry`, solc 0.8.17, optimizer on, runs 200, evm
london):

- **Executable runtime code is identical** (518 bytes), so the deployed behaviour is exactly what the
  canonical source produces. `script/registry-byte-match.py` reproduces this locally, and re-running
  it costs no Blockscout quota.
- **The 53-byte metadata blob differs**, and only in its 32-byte content hash, which is keccak256 of
  the metadata JSON covering the original source text and its path.

That second point is exactly what Blockscout's **Ethereum Bytecode Database** exists to ignore. It
stores verified sources keyed by bytecode rather than by chain and address, and matches an unverified
contract on the **Main** (functionally significant) part of the bytecode, metadata excluded. The
registry was resolved through it and is recorded as **partially verified** at 2026-09-30 19:39:04 UTC:
`is_verified` and `is_partially_verified` true, `is_fully_verified` false,
`is_verified_via_eth_bytecode_db` true, with the canonical name, path (`src/ERC6551Registry.sol`) and
settings. The explorer's contract page states the route in words: "Contract source code verified
(partial match) — This contract has been partially verified using Blockscout Bytecode Database".

The source text that match attached is the database's own copy, not this repo's and not the
mainnet-verified one: it misspells `keccak256(bytecode)` as `keccak256(bytedcode)` in one comment, which
is why its text differs from this repo's vendored file. Comments never reach executable bytecode, so the
behaviour the explorer displays is correct; the difference only explains partial rather than full match.

A full match would need the original file byte for byte, which is not available here, and for
third-party canonical code deployed through a keyless factory the partial match is the expected
outcome: the same address carries byte-identical executable code on every chain.

An explicit manual submission was also attempted, to confirm the "similar match" route. It was
**accepted** by the explorer ("Smart-contract verification started", HTTP 200) with the canonical
source at solc 0.8.17 / optimizer 200 / evm london via the UI's `flattened-code` method, but changed
nothing: the contract keeps the bytecode-database partial match (`verified_at` unchanged), because an
exact or full match would require the submitted source to reproduce the deployed metadata hash, which
no available copy of the file does. Note also that the UI/`v2` verify route is not rate-limited the way
the `v1` `module=contract` API is (180 requests per window here), so the 429s earlier were specific to
the `v1`-based `forge verify-contract` path, not to verification on this explorer generally.


## 8. Celo mainnet (chain 42220): Alpha v1 / pilot broadcast runbook

**Executed by Adam Jannoud, the project's author and sole deployer, on 1 October 2026: steps 0-6 and 8 of the runbook
below ran; step 7, the role handover, has not.** Read back
from the chain, `DEFAULT_ADMIN_ROLE`, `UPGRADER_ROLE`, `VERIFIER_ROLE` and `bufferPool` all still sit with the deployer
hot key `0x1DB0084Db70bF8D0E06c1785D693Fc6a95317890`, and no tree is minted: `ownerOf(1)` reverts
`ERC721NonexistentToken(1)`.

One broadcast, four transactions, 4,015,198 gas, **0.803044 CELO** at 200.0011 gwei, all in block `78935900`, every
receipt status `0x1`. The canonical registry was reused rather than deployed, so `DeployAll` sent four transactions and
no CREATE2. The deployer's remaining balance is `3.1969559832822` CELO.

| Contract | Address | Tx | Gas | Blockscout |
| --- | --- | --- | --- | --- |
| ERC-6551 registry (canonical, reused) | `0x000000006551c19487814612e58FE06813775758` | none, already on chain | — | verified |
| ERC-6551 account implementation | `0x65D18C960170ca2B4936c62945bA0e827e5cCd2B` | `0xdd6b5e99…55f53b` | 626,504 | verified |
| BioRigCoreV5 implementation | `0xdb3a450b85D48E6e6552dB2b32aD75a7ac590c60` | `0xc06b4b99…f351eb` | 2,942,890 | verified |
| ERC1967Proxy (the address to use) | `0x04Db169dDF8AbB80943161C01B2a71DC40384E64` | `0x2b2d42c1…f453a5` | 389,191 | verified |
| `grantRole(VERIFIER_ROLE, admin)` | `0x04Db169d…4E64` | `0xf97d29ab…c36dc8` | 56,613 | — |

All four report `is_verified: true`, read on 1 October 2026 from `/api/v2/smart-contracts/{address}` on
<https://celo.blockscout.com> (verified between 06:38:11Z and 06:44:13Z) rather than from the submission exit codes. The
explorer resolved the registry, the account implementation and the proxy through its Ethereum Bytecode Database, the
same partial match Celo Sepolia reached, and `BioRigCoreV5` from this repository's own source.

The rest of this section is the ordered runbook as approved, with each step's status marked:

- **Alpha v1 / pilot.** The external audit is a later grant milestone, not a gate on this deployment.
- **Admin.** Deploy from a fresh deployer hot key with `ADMIN` equal to it, which is what `_preflightBase` requires,
  then hand admin to a Celo Safe with `script/HardenMainnetAdmin.s.sol`. That is a separate run, step 7, and it has
  **not run**: the deployer still holds admin.
- **Verifier.** `VERIFIER_ROLE` goes to a dedicated server-side key, never the admin. The handover refuses a
  `VERIFIER_ADDRESS` equal to the deployer or the Safe. **Pending**, step 7: the deployer holds it today.
- **Explainer.** The video stays as rendered against Celo Sepolia (`DEMO.md`); it is not re-rendered.

What the code expects of mainnet: the canonical ERC-6551 registry is already there with the canonical bytecode
(section "Deployment is not proof"), so `DeployAll` sends **four** transactions (account implementation, BioRig
implementation, proxy, `grantRole`) and **no CREATE2**. That was estimated at about 0.81 CELO at the 202.5 gwei of
1 October 2026; the run above actually spent 0.803044 CELO at 200.0011 gwei. The handover adds six small transactions.

Before starting, have three things ready: the Celo Safe that becomes admin (deployed through app.safe.global, with
its owners and threshold decided, and the new deployer key not among them), the verifier server's address (its key
stays on that server), and the address `BUFFER_POOL` should hold (it must be non-zero; on Celo Sepolia it was the
deployer, and `DEFAULT_ADMIN_ROLE` can change it later with `setBufferPool`). Work from a fresh shell at the reviewed
commit, so nothing exported from the Celo Sepolia `.env` lingers.

**0. Rehearse on a fork of mainnet.** Sends nothing; every step in section 5 has to report `AS EXPECTED`.

```bash
forge test && .venv/bin/python -m pytest dashboard tools -q
CHAIN_ID=42220 script/fork-dry-run.sh > cache/fork-mainnet.log 2>&1; echo "exit $?"   # must print exit 0
grep -E '^>>> UNEXPECTED|SUMMARY' -A1 cache/fork-mainnet.log
```

**1. Generate the deployer key.** It sends the deployment and the handover, and holds nothing afterwards.

```bash
mkdir -p .deploy && chmod 700 .deploy                         # .deploy/ is gitignored
cast wallet new --json > .deploy/mainnet-deployer.json && chmod 600 .deploy/mainnet-deployer.json
DEPLOYER=$(jq -r '(.data // .)[0].address' .deploy/mainnet-deployer.json); echo "$DEPLOYER"
```

**2. Fund it with about 5 CELO** from a wallet the team controls. That is several times the estimate, as headroom
for a gas spike; what is left is swept back in step 7.

```bash
cast balance "$DEPLOYER" --rpc-url https://forno.celo.org --ether            # expect >= 5
```

**3. Set the environment.** Copy the committed template and fill in its empty values. The network block in the
template is the one `dashboard/chains.json` holds for chain 42220, and `tools/test_env_template.py` fails if the two
disagree or if a variable a deploy script requires is missing — so do not hand-edit that block.

```bash
cp .env.mainnet.example .env.mainnet && chmod 600 .env.mainnet                 # .env.mainnet is gitignored by .env.*
# PRIVATE_KEY through this sed rather than retyping it; ADMIN, BUFFER_POOL, NEW_ADMIN, VERIFIER_ADDRESS by hand
sed -i "s|^PRIVATE_KEY=.*|PRIVATE_KEY=$(jq -r '(.data // .)[0].private_key' .deploy/mainnet-deployer.json)|" .env.mainnet
sed -i "s|^ADMIN=.*|ADMIN=$DEPLOYER|" .env.mainnet
unset PROXY_ADDRESS PROXY_DEPLOY_BLOCK
set -a; source .env.mainnet; set +a
cast chain-id --rpc-url "$RPC_URL"                                            # 42220
cast wallet address --private-key "$PRIVATE_KEY"                              # must equal $ADMIN
cast call "$NEW_ADMIN" "getThreshold()(uint256)" --rpc-url "$RPC_URL"         # the Safe's threshold
cast call "$NEW_ADMIN" "getOwners()(address[])" --rpc-url "$RPC_URL"          # must not contain $ADMIN
```

**4. Simulate against live mainnet state.** No `--broadcast`, so nothing is sent. The log must say `Canonical ERC-6551
registry already deployed on this chain; reusing it.`, and the simulated transactions must be exactly these four:

```bash
forge script script/DeployAll.s.sol:DeployAll --rpc-url "$RPC_URL"
jq -r '.transactions[] | .transactionType + " " + (.contractName // "-")' \
  broadcast/DeployAll.s.sol/42220/dry-run/run-latest.json
# CREATE ERC6551Account / CREATE BioRigCoreV5 / CREATE ERC1967Proxy / CALL ERC1967Proxy
```

**5. Broadcast**, verifying on <https://celo.blockscout.com> in the same run. If the run is cut off, repeat the same
command with `--resume` rather than starting over.

```bash
forge script script/DeployAll.s.sol:DeployAll --rpc-url "$RPC_URL" --broadcast --slow \
  --verify --verifier blockscout --verifier-url "$VERIFIER_URL"
export PROXY_ADDRESS=$(jq -r '[.transactions[] | select(.transactionType == "CREATE" and .contractName ==
  "ERC1967Proxy")] | last | .contractAddress' broadcast/DeployAll.s.sol/42220/run-latest.json)
echo "$PROXY_ADDRESS"                                     # the summary's PROXY_ADDRESS= line prints the same
```

**6. Verify on Blockscout.** Read the explorer's own status, not `--verify`'s exit code (section 7). For any
contract still `false`, submit it once; each attempt can cost four of the ten requests per window, so space them out.

```bash
script/verify-retry.sh status                 # CHAIN_ID=42220 is exported, so this reads mainnet
script/verify-retry.sh core                   # only for a contract still unverified
script/verify-retry.sh account
script/verify-retry.sh proxy
```

The canonical registry is third-party code that predates this deployment. `script/verify-retry.sh status` on 1 October
2026 showed it unverified (`is_verified: false`), and Blockscout then resolved it through its Ethereum Bytecode Database
at 06:44:13 UTC, the same partial match Celo Sepolia reached, so no submission from here was needed. Its behaviour is
pinned by its codehash.

**7. Hand the roles over.** Simulate first; the broadcast reads every transition back and reverts on the first
surprise. Then read the roles from the chain itself, and sweep what is left of the deployer's CELO.

```bash
forge script script/HardenMainnetAdmin.s.sol:HardenMainnetAdmin --rpc-url "$RPC_URL"
forge script script/HardenMainnetAdmin.s.sol:HardenMainnetAdmin --rpc-url "$RPC_URL" --broadcast --slow

ADMIN_ROLE=0x0000000000000000000000000000000000000000000000000000000000000000   # DEFAULT_ADMIN_ROLE
for who in "$ADMIN" "$NEW_ADMIN" "$VERIFIER_ADDRESS"; do   # deployer, Safe, verifier
  printf '%s admin=%s upgrader=%s verifier=%s\n' "$who" \
    "$(cast call "$PROXY_ADDRESS" 'hasRole(bytes32,address)(bool)' "$ADMIN_ROLE" "$who" --rpc-url "$RPC_URL")" \
    "$(cast call "$PROXY_ADDRESS" 'hasRole(bytes32,address)(bool)' "$(cast keccak UPGRADER_ROLE)" "$who" --rpc-url "$RPC_URL")" \
    "$(cast call "$PROXY_ADDRESS" 'hasRole(bytes32,address)(bool)' "$(cast keccak VERIFIER_ROLE)" "$who" --rpc-url "$RPC_URL")"
done
# deployer: false false false     Safe: true true false     verifier: false false true

RETURN_TO=0x...                               # the address the CELO came from
LEFT=$(cast balance "$ADMIN" --rpc-url "$RPC_URL"); FEE=$((21000 * $(cast gas-price --rpc-url "$RPC_URL") * 2))
cast send "$RETURN_TO" --value $((LEFT - FEE)) --private-key "$PRIVATE_KEY" --rpc-url "$RPC_URL"
```

Once the explorer shows the handover and the sweep, the deployer key has no further use: delete
`.deploy/mainnet-deployer.json` and the `PRIVATE_KEY` line of `.env.mainnet`.

**8. Record the deployment** in `dashboard/deployment.json`, from the broadcast artifact. The tool refuses an artifact
for another chain, a transaction without a successful receipt, a proxy without code, and an RPC that answers for a
different chain, and it adds mainnet beside Celo Sepolia without touching it. Run for mainnet on 1 October 2026, which recorded it at block
`78935900` and left the default alone. Celo Sepolia stays the default chain;
pass `--make-default` only when the dashboard and the diagram are meant to switch to mainnet, and regenerate the
diagram then (`.venv/bin/python tools/generate_architecture.py`; check its "all four contracts verified" line is true
by then).

```bash
.venv/bin/python scripts/record_deployment.py --chain-id 42220
git add dashboard/deployment.json broadcast/DeployAll.s.sol/42220 broadcast/HardenMainnetAdmin.s.sol/42220
git commit -m "Record the Celo mainnet deployment"
```

`broadcast/**/dry-run/` is gitignored, so only the real broadcasts are added.

**9. Re-run the suites against the mainnet record.** The dashboard tests check that a chain is recorded exactly when
its broadcast is committed, and with that broadcast's proxy and block, so they now cover the real mainnet entry.

```bash
forge test
.venv/bin/python -m pytest dashboard -q
.venv/bin/python -m pytest dashboard -q --chain-id 42220
.venv/bin/python -m pytest tools -q
CHAIN_ID=42220 .venv/bin/python scripts/check-hosted-entrypoint.py
```

Run on 1 October 2026 against the recorded mainnet entry: `forge test` **175 passed, 0 failed** (16 suites); `pytest
dashboard` **89 passed** on the default chain and **61 passed** with `--chain-id 42220`; `pytest tools` **40 passed**;
and `check-hosted-entrypoint.py` green on the default chain and again with `CHAIN_ID=42220`.

`dashboard.smoke` and `scripts/check_dashboard_ui.py` read token #1 and simulate a mint from the configured
`PRIVATE_KEY`, so on mainnet they belong after the first pilot mint, run with `CHAIN_ID=42220` and the verifier
server's key: `CHAIN_ID=42220 .venv/bin/python -m dashboard.smoke`, and `check_dashboard_ui.py` against a dashboard
started with the same `CHAIN_ID`.

The same steps serve Celo Sepolia: `--chain-id 11142220` in steps 3 and 8, a faucet instead of step 2, and a
`DeployAll` that sends five transactions where the registry is absent. The Celo Sepolia deployment of section 6
predates `HardenMainnetAdmin` and still has its deployer as admin.
