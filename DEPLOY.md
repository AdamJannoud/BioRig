# Deploying BioRigCoreV5

`script/DeployBioRig.s.sol` deploys the `BioRigCoreV5` implementation, then an OpenZeppelin `ERC1967Proxy` whose
constructor runs `initialize(...)`. The proxy is therefore never live without being initialised. `BioRigCoreV5` is
UUPS: upgrades are gated by `UPGRADER_ROLE` inside the implementation. That means no `TransparentUpgradeableProxy`
and no `ProxyAdmin`.

**Target network: Celo Sepolia** (chain id `11142220`, RPC `https://forno.celo-sepolia.celo-testnet.org`, currency
CELO, explorer Blockscout at <https://celo-sepolia.blockscout.com>). Celo Alfajores (`44787`) was shut down and
replaced by Celo Sepolia. Its RPC no longer resolves, so nothing here targets it. Every value comes from the
environment, so the same commands work on another chain once `.env` is changed.

Faucets: <https://faucet.celo.org/celo-sepolia> and the Google Cloud Web3 faucet (Celo Sepolia). The Celo faucet's
browser flow is gated on reCAPTCHA v3 and its unauthenticated API path rejects requests without a captcha token, so
headless callers need either a real browser or a self-serve API key from <https://faucet.celo.org/keys>.

## One command, when the chain has neither prerequisite

On a chain with no ERC-6551 registry and no account implementation (Celo Sepolia, at the time of writing),
`script/DeployAll.s.sol` deploys **all three** in a single broadcast, in dependency order:

```bash
cp .env.example .env          # PRIVATE_KEY, ADMIN, BUFFER_POOL (CHAIN_ID defaults to Celo Sepolia)
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
read-back looks fine. On Celo Sepolia, when this was written:

| Contract | Address | Celo Sepolia | Celo mainnet |
| --- | --- | --- | --- |
| Canonical ERC-6551 registry | `0x000000006551c19487814612e58FE06813775758` | **no code** | code present |
| Nick's CREATE2 factory | `0x4e59b44847b379578588920cA78FbF26c0B4956C` | code present | — |
| Tokenbound AccountV3 / AccountV3Upgradable | `0x41C8…44eC` / `0x5526…6E7F` | **no code** | not checked |

`DeployBioRig` therefore refuses to run unless `ERC6551_REGISTRY` and `ERC6551_IMPLEMENTATION` both have code on
the target chain. It also refuses if a non-zero `URI_GENERATOR` has no code, and if `CHAIN_ID` differs from the RPC's
`eth_chainId`. On Celo Sepolia you must first deploy the optional prerequisites below.

## 0. Setup

```bash
cp .env.example .env          # then edit .env: PRIVATE_KEY, ADMIN, BUFFER_POOL, ERC6551_IMPLEMENTATION, ...
set -a; source .env; set +a   # export every variable into this shell
cast chain-id --rpc-url "$RPC_URL"                       # must print 11142220 (= $CHAIN_ID)
cast balance "$(cast wallet address --private-key "$PRIVATE_KEY")" --rpc-url "$RPC_URL" --ether
```

`.env` is gitignored. Use a dedicated, low-value testnet deployer key. On a fork of Celo Sepolia, the full
`DeployBioRig` run was estimated at about 4.33M gas (~0.33 CELO at the fork's 76.7 gwei max fee). The registry was
estimated at about 259k gas.

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

The explorer is **Blockscout, not CeloScan or Etherscan**. Use `--verifier blockscout` with
`--verifier-url https://celo-sepolia.blockscout.com/api/`. No API key is needed.

What was actually observed (`evidence/blockscout-verify-probe.log`): with no API key set, `forge verify-contract
--verifier blockscout --verifier-url https://celo-sepolia.blockscout.com/api/` against Celo Sepolia was accepted,
returned a GUID, and polled to a final status. This was a deliberate negative control, submitting a source that does
not match the target, and it reported `Fail - Unable to verify` as expected. **No positive verification was observed,
because nothing was deployed.** Unauthenticated status polling can hit Blockscout's rate limit (`Too many requests`).
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
already. It was not observed for this deployment, though. If the proxy page does not show "Read/Write as Proxy"
pointing at the implementation, verify the proxy as above, then use the proxy-detection button on its Blockscout page.

## 4. After deploying: make it usable, then prove it

No `VERIFIER_ROLE` is granted at initialisation. The admin must grant it:

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

`mintTree` uses `_safeMint`. A planter with code must implement `onERC721Received`. That includes EOAs with an
EIP-7702 delegation, whose code begins `0xef0100...`. On Celo Sepolia, anvil's well-known test accounts carry exactly
such a delegation, and minting to them reverts.

## 5. Local fork dry run (evidence)

`script/fork-dry-run.sh` starts anvil forked from Celo Sepolia, runs everything against real chain state, and stops
anvil on exit. It sends nothing to Celo Sepolia. Its output is saved in `evidence/deploy-fork-dry-run.log`.

```bash
script/fork-dry-run.sh > evidence/deploy-fork-dry-run.log 2>&1; echo "exit $?"
```

> **The `PRIVATE_KEY` in that script is anvil's public account #0 key.** It exists only for this local fork dry run.
> Never use it for a broadcast to any real network. Funds sent to it are taken immediately.

The script runs these steps:

1. **Registry guard:** `DeployBioRig` runs with the canonical registry, which has no code on Celo Sepolia. It is
   refused: `ERC6551_REGISTRY 0x0000…5758 has no code on chain 11142220. Refusing to deploy…`.
2. **Chain-id guard:** `CHAIN_ID=44787` is set against the Celo Sepolia RPC. It is refused: `CHAIN_ID mismatch`.
3. `DeployERC6551Registry` dry run (no `--broadcast`), which simulates deployment to the canonical address.
4. Local setup, on the anvil fork only: the registry and example account are broadcast to the fork.
5. **`DeployBioRig` dry run (no `--broadcast`):** the proxy is deployed and every read-back passes.
6. Fork smoke test: BioRig is broadcast to the fork, `VERIFIER_ROLE` is granted, and one tree is minted. This proves
   the registry and account path works, not just the deployment.

## 6. Executed deployment: Celo Sepolia, 30 September 2026

Run with `DeployAll` exactly as in "One command" above, plus `--verify --verifier blockscout --verifier-url
"$VERIFIER_URL"`. One broadcast, 5 transactions, 4,192,380 gas, 0.2096 CELO at a ~50 gwei base fee. Deployer and
admin were the throwaway account `0xb5aB2054b43040593805Cf662A938eFE924F2778`, with `BUFFER_POOL` the same address and
`URI_GENERATOR` zero.

| Contract | Address | Tx | Gas | Blockscout |
| --- | --- | --- | --- | --- |
| ERC-6551 registry (canonical) | `0x000000006551c19487814612e58FE06813775758` | `0xb8f54434…451320` | 177,170 | not verified, see below |
| ERC-6551 account implementation | `0x3d8a53dB1bBcab6D47097B25080527e5560C5165` | `0x5abd3074…8c6e99` | 626,504 | verified |
| BioRigCoreV5 implementation | `0x4c998C6553C78bb9d5A67Aac6fBC526d64DBa3a4` | `0x32c7fdff…33199d` | 2,942,890 | verified |
| ERC1967Proxy (the address to use) | `0x21ab8B36177F65ce69e04E281E4aFf3Db6b5f7E6` | `0xdcf0dd8b…39184e` | 389,203 | submission rate-limited |
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

Two contracts are not source-verified on Blockscout:

- **The proxy.** It was submitted during the broadcast, but Blockscout rate-limited its verification endpoint
  (`status=0, Too many requests`) while the run was still going. Resubmitting later works, with the source and
  settings unchanged from the build that produced it:
  ```bash
  ARGS=$(cast abi-encode "f(address,bytes)" 0x4c998C6553C78bb9d5A67Aac6fBC526d64DBa3a4 "$(cast calldata \
    'initialize(address,address,address,uint256,address,address)' 0xb5aB2054b43040593805Cf662A938eFE924F2778 \
    0x000000006551c19487814612e58FE06813775758 0x3d8a53dB1bBcab6D47097B25080527e5560C5165 11142220 \
    0xb5aB2054b43040593805Cf662A938eFE924F2778 0x0000000000000000000000000000000000000000)")
  forge verify-contract 0x21ab8B36177F65ce69e04E281E4aFf3Db6b5f7E6 \
    lib/openzeppelin-contracts/contracts/proxy/ERC1967/ERC1967Proxy.sol:ERC1967Proxy \
    --verifier blockscout --verifier-url "$VERIFIER_URL" --chain 11142220 --constructor-args "$ARGS"
  ```
- **The canonical registry** cannot be exact-match verified from this repository at all. On chain it is the EIP-6551
  canonical creation code, compiled with solc 0.8.17; this repo compiles the vendored source with solc 0.8.28, so
  neither the executable bytes nor the metadata match. Blockscout's "similar match" submission, from the explorer UI,
  is the route. It is behaviourally proven regardless: `DeployAll` checks `account()` against an independent CREATE2
  derivation before broadcasting, and a real tree minted through it.
