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
`dashboard/deployment.json`, which is Celo mainnet and where both live chains are recorded. Every deployment input comes
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
`DEFAULT_ADMIN_ROLE` and `UPGRADER_ROLE` to a Safe and leaves `VERIFIER_ROLE` wherever
`VERIFIER_ADDRESS` points: a dedicated server-side key, or the deployer itself when there is no separate
signing key yet (section 8). In the second case the deployer keeps minting and loses only pause, upgrade and
role administration. To grant it to another account by hand:

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
script/fork-dry-run.sh                        # default chain (Celo mainnet)
CHAIN_ID=11142220 script/fork-dry-run.sh      # Celo Sepolia
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
   `NEW_ADMIN`, a `NEW_ADMIN` with no code, a contract that is not a Safe, a Safe the deployer owns, a
   `PROXY_ADDRESS` that is not a BioRig proxy, and - when `VERIFIER_ADDRESS` is the deployer - a deployer that
   does not already hold `VERIFIER_ROLE` (which would leave nobody able to mint). "A Safe the deployer owns" means
   anywhere in the ownership tree, to `MAX_OWNERSHIP_DEPTH` contract hops: a Safe whose owner is another
   deployer-owned Safe is refused too, and the rehearsal covers that nested case, a chain that exceeds the bound,
   and an owner that is a contract whose Safe views cannot be read (refused unless `ALLOW_UNINSPECTED_OWNER=true`
   is set deliberately - an owner address may legitimately carry code, e.g. an EIP-7702 delegation).
10. **Handover:** `HardenMainnetAdmin` is simulated and broadcast to the fork, then every role is read back from the
    fork with `cast`: the deployer holds no admin and no upgrade, the Safe holds admin and upgrader only, and
    `VERIFIER_ROLE` sits with the verifier - the dedicated key, or the deployer itself when that is what
    `VERIFIER_ADDRESS` names.
11. **After the handover:** the deployer can no longer pause, the verifier mints a tree whose TBA is bound to the
    fork's chain id, and the Safe pauses the proxy through `execTransaction`. With a dedicated verifier key, the
    deployer cannot mint either.
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

**Executed by Adam Jannoud, the project's author and sole deployer, on 1 October 2026: every step of the runbook
below has run, step 7 the role handover included, in mode B.** Read back from the chain afterwards,
`DEFAULT_ADMIN_ROLE` and `UPGRADER_ROLE` sit with the Safe `0x3B36b3446fCB0729B0046520156933E56352D551`, whose sole
owner is the plain EOA `0xD314e37FD8538fe66231EE670B74C9428d03feEa` - an address the deployer hot key
`0x1DB0084Db70bF8D0E06c1785D693Fc6a95317890` cannot sign for - while the deployer key keeps `VERIFIER_ROLE`
(minting) and still holds `bufferPool`. It has since minted the first mainnet tree, recorded below.

**The first mainnet tree.** This deployment is no longer inert: one tree was minted on it on 1 October 2026,
from the verifier key the handover above left in place.

```bash
cast send "$PROXY" "mintTree(address,bytes32,uint96,uint96)" 0xD314e37FD8538fe66231EE670B74C9428d03feEa 0xb7a55a6b1b7e4fe0fba76f303772cba7fdf3715d4030e3fcd91ed297c756d741 10 20 --private-key <VERIFIER key> --rpc-url "$RPC_URL"
```

Tx `0x70476c02ef1af918a213eec63472e6cdbabcedd50193cdd6a7a89a09527797f7`, block `78992489`, status `0x1`,
270,077 gas, 0.054015697 CELO at 200.0011 gwei. The verifier's balance moved by exactly that figure and nothing
else, which is the non-payable claim holding on chain. The nullifier is the **production H3 derivation** for the
demo plot (`plot-1` at -1.2921, 36.8219, resolution 12) - not the bare salt the Sepolia tree in section 4 used.

```bash
cast call "$PROXY" "ownerOf(uint256)(address)" 1
#   0xD314e37FD8538fe66231EE670B74C9428d03feEa
cast call "$PROXY" "getTreeStats(uint256)((uint96,uint96,uint64,address,bool,bytes32))" 1
#   (10, 20, 1790893247, 0x453e89520DB8f374CFCeA95625B99DF5d4F1256A, true,
#    0xb7a55a6b1b7e4fe0fba76f303772cba7fdf3715d4030e3fcd91ed297c756d741)
cast call "$PROXY" "getTreeStats(uint256)((uint96,uint96,uint64,address,bool,bytes32))" 2
#   reverts InvalidTree - exactly one tree exists
cast call "$PROXY" "isNullifierActive(bytes32)(bool)" 0xb7a55a6b1b7e4fe0fba76f303772cba7fdf3715d4030e3fcd91ed297c756d741
#   true
```

The tree's token-bound account `0x453e89520DB8f374CFCeA95625B99DF5d4F1256A` is the one the canonical registry
derives from `salt = keccak256(abi.encodePacked(uint256(1), planter, nullifier))`, so the registry and account
path is proven on mainnet as it is on Sepolia: it reports ERC-165 `0x6faff5f1`, and its `token()` returns
`(42220, 0x04Db169dDF8AbB80943161C01B2a71DC40384E64, 1)`.
Mode B was the choice recorded on 1 October 2026. `script/handover-fork-check.sh` and
`script/safe-owner-swap-fork-check.sh` rehearsed exactly that against a fork of mainnet, and both were green before
anything was broadcast. Both operations have since run on the real chain, so the tip no longer holds the state they
assert: the Safe is owned by the plain EOA, and the deployer holds neither `DEFAULT_ADMIN_ROLE` nor `UPGRADER_ROLE`.
By default each harness forks the tip and rebuilds that state on the fork with `tools/fork_reconstruct.py`, which
inverts the executed transactions read out of the committed broadcast records, so no archive endpoint is needed.
`FORK_MODE=pin` forks block `78991456` instead — archival-exact, but a past-block fork makes anvil read chain state
there and the public Celo RPCs serve historical state only intermittently, so it needs an archive `FORK_URL` and
otherwise stops before asserting anything, prints one `FATAL:` line and exits 2. `FORK_MODE=raw` forks the
unreconstructed tip, where their facts and guards fail by design. Both harnesses run as step 4b of
`scripts/verify-demo.sh`.

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

**Step 7 executed later the same day, mode B**: five transactions, 278,000 gas, **0.055600295 CELO** at 200.001 gwei,
every receipt status `0x1`. Addresses and hashes are below, step by step.

The rest of this section is the ordered runbook as approved, with each step's status marked:

- **Alpha v1 / pilot.** The external audit is a later grant milestone, not a gate on this deployment.
- **Admin.** Deploy from a fresh deployer hot key with `ADMIN` equal to it, which is what `_preflightBase` requires,
  then hand admin to a Celo Safe with `script/HardenMainnetAdmin.s.sol`. That separate run, step 7, **has run**: the
  Safe holds `DEFAULT_ADMIN_ROLE` and `UPGRADER_ROLE`, and the deployer key holds neither.
- **Verifier.** `VERIFIER_ROLE` goes to whatever address `VERIFIER_ADDRESS` names. A dedicated server-side key
  is the better end state and is what the script prefers, but the approved choice here is that there is no such
  key yet, so the deployer keeps the role and keeps mint/update/reportMortality; it loses pause, upgrade and
  role administration. The Safe holds `DEFAULT_ADMIN_ROLE` after the handover, so it can grant `VERIFIER_ROLE`
  to a dedicated key and revoke it from the deployer at any time, without another handover. The handover
  refuses a `VERIFIER_ADDRESS` equal to the Safe, and a Safe whose owners include the deployer. **Done**: the
  deployer holds it, and the Safe that holds admin can grant it to a dedicated key at any time.
- **Explainer.** The video stays as rendered against Celo Sepolia (`DEMO.md`); it is not re-rendered.

What the code expects of mainnet: the canonical ERC-6551 registry is already there with the canonical bytecode
(section "Deployment is not proof"), so `DeployAll` sends **four** transactions (account implementation, BioRig
implementation, proxy, `grantRole`) and **no CREATE2**. That was estimated at about 0.81 CELO at the 202.5 gwei of
1 October 2026; the run above actually spent 0.803044 CELO at 200.0011 gwei. The handover added five small
transactions, 0.055600295 CELO.

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

**1. Generate the deployer key.** It sends the deployment and the handover. What it holds afterwards depends on
`VERIFIER_ADDRESS` in step 7: nothing but `VERIFIER_ROLE` in mode B, and nothing at all with a dedicated key.

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
# (PRIVATE_KEY is accepted in either documented form - 0x + 64 hex digits, or the 64 digits bare)
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

**7a. Take the Safe off the deployer key (`script/SafeOwnerSwap.s.sol`).** The handover below refuses a `NEW_ADMIN`
Safe the deployer can sign for, and the Safe supplied for mainnet, `0x3B36b3446fCB0729B0046520156933E56352D551`
(SafeL2 1.5.0, threshold 1, nonce 0), had the deployer hot key as its **sole owner**, as had the other address supplied
on 1 October 2026, `0xe7042bC31A13E4FD2D5C4176ec52D28907E1311E`. Handing admin to it would leave the pen in the same
hand, so its owner is moved first, in one Safe transaction: `swapOwner(0x1, deployer, NEW_OWNER)`, hashed by the
Safe's own `getTransactionHash`, signed by the deployer and sent with `execTransaction`, then read back (owners exactly
`[NEW_OWNER]`, threshold 1, deployer not an owner, nonce advanced by one). `NEW_OWNER` is the address Adam controls
and the hot key does not: a hardware wallet or another key, ideally an EOA.

```bash
export SAFE_ADDRESS=0x3B36b3446fCB0729B0046520156933E56352D551 NEW_OWNER=0x...   # the address the hot key cannot sign for
NEW_OWNER=$NEW_OWNER SAFE_ADDRESS=$SAFE_ADDRESS forge script script/SafeOwnerSwap.s.sol:SafeOwnerSwap --rpc-url "$RPC_URL"   # simulate
NEW_OWNER=$NEW_OWNER SAFE_ADDRESS=$SAFE_ADDRESS forge script script/SafeOwnerSwap.s.sol:SafeOwnerSwap --rpc-url "$RPC_URL" --broadcast
cast call "$SAFE_ADDRESS" "getOwners()(address[])" --rpc-url "$RPC_URL"   # [NEW_OWNER], and the deployer is gone
```

**Run on 1 October 2026** with `NEW_OWNER=0xD314e37FD8538fe66231EE670B74C9428d03feEa`: one Safe transaction,
`execTransaction` on the Safe in block `78991457`, tx `0x7a99f8092aa924018bab62ab4b0362c9d291376fc96065f614d44a3712288012`,
gas 105,580, **0.021116106 CELO**, carrying `swapOwner(0x1, 0x1DB0084Db70bF8D0E06c1785D693Fc6a95317890,
0xD314e37FD8538fe66231EE670B74C9428d03feEa)`. The Safe's own `getTransactionHash` for it was
`0xc697ea1fc74ae8b3953f6a1ae550fb3265ea1a3c351fc4d696f6ea25981ef916358fbea7b2887cbd9bae2efb92f4ba895b1ad753733b7779b22e5b9e602152321b`.
Read back from the chain: `getOwners()` returns `[0xD314e37FD8538fe66231EE670B74C9428d03feEa]`, `getThreshold()` 1,
`nonce()` 1, and the deployer key is no longer an owner.

The preflight runs before anything is signed and refuses, saying what to do:

| Refusal | When |
| --- | --- |
| `CHAIN_ID mismatch` | `CHAIN_ID` and the RPC's `eth_chainId` disagree |
| `SAFE_ADDRESS has no code` / `does not answer getThreshold()` / `getOwners()` | `SAFE_ADDRESS` is not a Safe |
| `SAFE_ADDRESS has threshold N, not 1` | one key's signature cannot satisfy the threshold; use the Safe app |
| `the deployer key cannot sign for this Safe; nothing to swap` | the deployer is not an owner: already swapped (so a re-run is harmless), or the wrong `PRIVATE_KEY` |
| `NEW_OWNER is the zero address` / `is the deployer` / `is already an owner` | `NEW_OWNER` would not change who holds the Safe |
| `the deployer is one of N owners, not the sole owner` | not a 1-of-1 Safe; change multi-owner Safes in the Safe app |
| `the deployer is an owner of the NEW_OWNER Safe` / `an owner of the NEW_OWNER Safe is owned by the deployer` | `NEW_OWNER` is a Safe the hot key signs for, directly or through a nested Safe (the 1 October trap, re-entered one level down) |
| `NEW_OWNER is a contract this script cannot inspect` | a contract that does not answer `getOwners()`; accepted only with `ALLOW_UNINSPECTED_OWNER=true` after a human has checked it |

The ownership walk is the same code the handover runs (`script/SafeOwnershipGuard.sol`). Rehearse it all first:
`bash script/safe-owner-swap-fork-check.sh` forks the chain tip and reconstructs the pre-swap state on the fork, which
is the state this rehearsal rests on now that both steps have run for real. It makes every refusal above fire on its
own fixture, swaps the live Safe to a fresh stand-in EOA, proves the deployer's signature is then refused by the Safe
(`GS026`) and the stand-in's accepted, and then, on the same fork, runs this step 7 in mode B with `NEW_ADMIN` set to
the swapped Safe and asserts the end state with `hasRole`. It must print `REHEARSAL PASSED` and exit 0.

`FORK_MODE=pin` forks block `78991456` instead, the block the rehearsal rests on: that needs an archive `FORK_URL`,
because at a past block anvil reads chain state there and the public Celo RPCs serve historical state only
intermittently. With the default RPC it prints one `FATAL:` line and exits 2 without asserting anything. Both
rehearsals run as step 4b of `scripts/verify-demo.sh`.

**7b. Hand the roles over**, with `NEW_ADMIN` set to the Safe swapped in 7a. Simulate first; the broadcast reads every transition back and reverts on the first
surprise. Then read the roles from the chain itself, and sweep what is left of the deployer's CELO.

**Run on 1 October 2026**, `NEW_ADMIN` the swapped Safe and `VERIFIER_ADDRESS` the deployer key: four transactions,
every receipt `0x1`, all in the same minute.

| Call | Tx | Block | Gas |
| --- | --- | --- | --- |
| `grantRole(UPGRADER_ROLE, Safe)` | `0x1f4e63f5d972c9b8b93316da3c2a9dc2707c10a346a3839c0a869475a101853a` | 78991473 | 56,613 |
| `grantRole(DEFAULT_ADMIN_ROLE, Safe)` | `0xfa89432ecd8824a96597165e8402a93f7d1405a3ae2f2bc3a1ee0d6e675455cd` | 78991476 | 56,229 |
| `renounceRole(UPGRADER_ROLE, deployer)` | `0x84977e0e9aead685a5cdf2750b38d81e1dd623d981e596ea25ac1f3a571115a8` | 78991478 | 29,981 |
| `renounceRole(DEFAULT_ADMIN_ROLE, deployer)` | `0x631857c34f36401a0d503cdc3bbe75ebae2c16aaa090163c06b5ce231b034f55` | 78991482 | 29,597 |

172,420 gas, **0.034483190 CELO** at 200.001 gwei. Both grants land before either renounce, so the proxy is never
left without a `DEFAULT_ADMIN_ROLE` holder. Read back with the loop below, the deployer prints `false false true`
and the Safe `true true false`: the mode-B line, exactly. `bufferPool` is unchanged at the deployer address and
`ownerOf(1)` still reverts `ERC721NonexistentToken(1)`. The deployer's balance is `3.037630769622172860` CELO.

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
# mode B (VERIFIER_ADDRESS is the deployer): deployer: false false true    Safe: true true false

RETURN_TO=0x...                               # the address the CELO came from
LEFT=$(cast balance "$ADMIN" --rpc-url "$RPC_URL"); FEE=$((21000 * $(cast gas-price --rpc-url "$RPC_URL") * 2))
cast send "$RETURN_TO" --value $((LEFT - FEE)) --private-key "$PRIVATE_KEY" --rpc-url "$RPC_URL"
```

Once the explorer shows the handover and the sweep, what becomes of the deployer key depends on the mode.
With a dedicated `VERIFIER_ADDRESS` it has no further use: delete `.deploy/mainnet-deployer.json` and the
`PRIVATE_KEY` line of `.env.mainnet`. In mode B it still holds `VERIFIER_ROLE`, so it still signs every mint:
keep it, and keep the `PRIVATE_KEY` line - deleting it would leave the live tree with no way to mint.

**8. Record the deployment** in `dashboard/deployment.json`, from the broadcast artifact. The tool refuses an artifact
for another chain, a transaction without a successful receipt, a proxy without code, and an RPC that answers for a
different chain, and it adds mainnet beside Celo Sepolia without touching it. Run for mainnet on 1 October 2026, which recorded it at block
`78935900` and left the default alone. Later that day it was re-run with `--make-default`, which made Celo mainnet
the default chain, so the dashboard and the diagram switched to mainnet; the diagram was regenerated then
(`.venv/bin/python tools/generate_architecture.py`, whose "all four contracts verified" line is true). Celo Sepolia
stays recorded and selectable with `CHAIN_ID=11142220`.

```bash
.venv/bin/python scripts/record_deployment.py --chain-id 42220
.venv/bin/python scripts/record_deployment.py --chain-id 42220 --make-default   # the later switch of the default
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
dashboard` **89 passed** on the default chain and **61 passed** with `--chain-id 42220`; `pytest tools` **66 passed**;
and `check-hosted-entrypoint.py` green on the default chain and again with `CHAIN_ID=42220`.

`dashboard.smoke` and `scripts/check_dashboard_ui.py` read token #1 and simulate a mint from the configured
`PRIVATE_KEY`; the first pilot mint gave mainnet a token #1, so they run there: `CHAIN_ID=42220 .venv/bin/python -m
dashboard.smoke`, and `check_dashboard_ui.py` against a dashboard started with the same `CHAIN_ID` (now the default,
so a dashboard started with no `CHAIN_ID` and no `.env` renders it too). `check_dashboard_ui.py` pins mainnet token
#1's token-bound account, `0x453e89520DB8f374CFCeA95625B99DF5d4F1256A`.

The same steps serve Celo Sepolia: `--chain-id 11142220` in steps 3 and 8, a faucet instead of step 2, and a
`DeployAll` that sends five transactions where the registry is absent. The Celo Sepolia deployment of section 6
predates `HardenMainnetAdmin` and still has its deployer as admin.

## 9. Publishing the proposal carriers

Four files are published into the workspace Files for reviewers: `proposal.pdf`, `proposal.docx`, `proposal.md` and
`architecture.png`. Each derives from repo source: the pdf from `docs/prezenti-proposal.md` through
`tools/render_proposal_pdf.py` (with `tools/print/proposal.css` and `assets/brand/biorig-lockup.png`), the docx from
the same markdown through `tools/render_proposal_docx.py`, the md is the markdown itself, and the png is the committed
`BioRig_Architecture_Pro.png` (rendered from `assets/BioRig_Architecture_v5.svg`). `docs/carriers.json` records, per
carrier, the published copy's digest and the hash of every source it was made from, and `tools/check_carriers.py`
(step 7 of `scripts/verify-demo.sh`) fails when a source has moved since, when a fresh render no longer matches what
was published, or when a staged copy of the Files bytes is not what the pipeline produced.

The Files are not reachable from the repo, so publishing is a hand-off with one rule: the record is written only from
the bytes actually held in Files.

1. Edit `docs/prezenti-proposal.md` (or a renderer, the stylesheet, the lockup, the diagram).
2. Render:
   ```bash
   .venv/bin/python tools/render_proposal_pdf.py    # out/proposal/BioRig-Prezenti-Grant-Application-Proposal.pdf
   .venv/bin/python tools/render_proposal_docx.py   # out/proposal/BioRig-Prezenti-Grant-Application-Proposal.docx
   ```
   For the diagram, regenerate and commit `BioRig_Architecture_Pro.png` first.
3. Publish the four files into the workspace Files under the carrier names above.
4. Stage the published bytes: download the four copies back out of Files into `cache/carriers/published/` (git-ignored;
   never commit it), named `proposal.pdf`, `proposal.docx`, `proposal.md`, `architecture.png`.
5. Record: `.venv/bin/python tools/check_carriers.py --record`. It re-renders and refuses (exit 1, writing nothing)
   unless every staged copy agrees with the fresh render, so a stale or wrong upload is caught here, not by a reviewer.
6. Commit `docs/carriers.json` with the source change.

The pdf is byte-deterministic on one machine and compared by sha256. Byte-equality of the rendered pdf is attested in
the publishing environment, where the published copies are staged and the browser build and brand fonts (Caladea,
Lato) are the ones it was rendered with; elsewhere, such as a fresh clone in CI, Chromium print-to-PDF yields other
bytes from unchanged source, so the check enforces the recorded source digests plus whatever staged copies it can see,
and prints a `note:` saying the pdf bytes are not attested there. The docx is compared by a digest over its zip
entries' names, CRC32s and sizes, because python-docx stamps the render time into every entry; the module docstring of
`tools/check_carriers.py` carries the evidence. Without staged copies the check prints a note and still fails on any
repo-side drift; exit status is 0 clean, 1 drift, 2 setup failure.

## 10. Clean-clone proof, the pre-push gate and CI

A checkout that has been worked in for weeks passes things a fresh clone does not: initialised submodules, a built
`.venv`, a `.env`, a downloaded Chromium. The proof below removes that advantage. It is the answer to "does the
README actually work", run against the exact commit being shipped.

**What the proof does.** `tools/clean_clone_proof.py` clones the repository with a plain `git clone` (no
`--recurse-submodules`) into a temp directory outside the checkout (`/var/tmp` by default, or
`$CLEAN_CLONE_PROOF_WORKDIR`; a clone with its `.venv` needs about 2 GB), checks it out at the source commit and
asserts the clone's commit and tree equal the source's. It parses the `## Quick start` bash fence out of the clone's
`README.md` and runs every line in order, stopping at the first failure; a fence it cannot find or parse is a FAIL.
Exports and `cd` carry from line to line as in a terminal. The `PRIVATE_KEY=<verifier key>` placeholder is filled
from the key without printing it or writing it anywhere; the `streamlit run` line must answer its health endpoint
and is then stopped; the `scripts/verify-demo.sh` line is the acceptance gate itself. It prints a per-line table
(exit code, status, notes), the skipped steps and a verdict:

| verdict | exit | meaning |
| --- | --- | --- |
| `PASS` | 0 | every quick start line and every gate step ran and passed; the clone is the source commit |
| `FAIL` | 1 | a line or a gate step failed, or the identity check did not hold; the failing step is named |
| `ERROR` | 2 | it could not start: an unknown commit, a malformed key, or `CLEAN_CLONE_PROOF=1` already set |
| `PARTIAL` | 3 | green, but something was skipped (no key): never reported as a pass |

```bash
python3 tools/clean_clone_proof.py                                    # GitHub's main tip
python3 tools/clean_clone_proof.py --source local --commit HEAD --json /var/tmp/proof.json
python3 tools/clean_clone_proof.py --no-key                           # key-free: PARTIAL at best
```

The key comes from `--key-file`, else `PRIVATE_KEY` in the environment, else the checkout's gitignored `.env`; the
clone never receives the `.env`, so it runs on the repository's default chain (Celo mainnet). Everything it runs is
read-only against the chain: step 3 is an `eth_call` simulation and step 4b broadcasts only to an anvil fork. A full
proof takes about nine minutes, most of it the toolchain install and the gate's video render.

**Key-free mode.** `VERIFY_ALLOW_NO_KEY=1 bash scripts/verify-demo.sh` skips the steps that need the deployer key: step
3 (the live mint simulation), step 4-sim (the dashboard's simulation verdicts: with no signer the dashboard is read-only
by design, and the browser check asserts that state instead), step 4b (the two mainnet fork rehearsals) and step 6's
exact-key scan of tracked files, which falls back to a pattern scan for key-shaped assignments. Each prints `SKIPPED (no
key): step N`, and the run ends on `PARTIAL: DEMO CHECKS PASSED EXCEPT SKIPPED STEPS: 3 4-sim 4b 6 ...`, never on `ALL
DEMO CHECKS PASSED`. The flag is refused when a key is configured, so it cannot quietly weaken a real run.

**The pre-push hook.** Install it once per checkout, and again whenever `--check` says it is out of date:

```bash
python3 tools/install_git_hooks.py           # copies scripts/git-hooks/pre-push into .git/hooks/
python3 tools/install_git_hooks.py --check   # exit 1 unless the installed hook matches the committed one
```

On a push that updates `refs/heads/main` it proves the exact local commit being pushed (`--source local`) and refuses
the push unless the verdict is `PASS`, naming the failing step. Pushes to any other branch are not gated. A PASS
record for the same commit and tree under `.git/clean-clone-proof/` is reused rather than proving twice. Bypass only on
purpose: `git push --no-verify`, or `CLEAN_CLONE_PROOF_SKIP=1 git push ...`, which prints a loud warning that the
commit went up unverified.

**Pushing.** `scripts/push-verified.sh` is the way to push `main`. It first checks the push can land: the remote's
`main` is read with `git ls-remote`, and a local commit that is not a fast-forward of it is refused in seconds, naming
the remote sha and the rebase to run, instead of failing as `! [rejected] ... (fetch first)` after the whole proof. It
then proves the local commit, pushes it, and confirms what landed: `git ls-remote` must report the local sha as the
remote's `main`, and a `--source github` proof clones the pushed tip back and runs everything again. It exits nonzero
naming the stage that failed.

```bash
scripts/push-verified.sh            # HEAD to origin's main
```

**CI.** `.github/workflows/clean-clone-proof.yml` runs on every push to `main` and on demand. Its first job checks out
the pushed commit (a clean clone from GitHub), initialises the submodules as the quick start does, installs Foundry,
Python, `tools/requirements.txt` and Playwright's Chromium, runs `forge test`, then the acceptance gate in key-free
mode; any red step fails the job, and the job summary states that the run was partial and lists the skipped steps.
Its second job checks remote identity: `git ls-remote` reports the pushed sha, and a second pristine clone has the
pushed commit's tree.

**The deployer key is never used in CI.** The workflow reads no secret, and no step would use one. Steps 3, 4-sim, 4b
and the exact-key scan are therefore proven only by the pre-push hook and `scripts/push-verified.sh`, on the machine
where the key already lives. A green CI run means the key-free part of the gate passed on a fresh clone, nothing more.
