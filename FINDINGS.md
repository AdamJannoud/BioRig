# BioRigCoreV5 — audit findings and hardening round

Target: `src/BioRigCoreV5.sol` (pristine copy: `src/BioRigCoreV5.sol.orig`; verbatim original also compiled as
`test/orig/OriginalV5.sol`. Neither was modified this round).
Toolchain: Forge 1.8.3, solc 0.8.28, OpenZeppelin (upgradeable) v5.1.0.
Every test deploys the contract behind a real `ERC1967Proxy` and initializes it through the proxy (`test/Base.t.sol`).
The bare implementation is only called directly in tests that are about the implementation
(`test_implementation_*` and `test_upgrade_calledOnImplementationDirectly_reverts`).

Result: **160 tests, 160 passed, 0 failed, 0 skipped** (15 suites: 155 unit tests, 4 fuzz tests at 256 runs each,
and 1 invariant suite with 4 invariants at 128 runs × depth 100 = 12,800 handler calls, 0 reverts).
The full output is at the end of this file and in `evidence/forge-test.txt`.

The first round (F-1 and everything under "Defects"/"Informational" below) was an audit with one minimal fix.
The **hardening round** implements four requirements (R1–R4) on top of it. The complete cumulative change against the
original is in `HARDENING.diff` (`diff -u src/BioRigCoreV5.sol.orig src/BioRigCoreV5.sol`).

---

## Hardening round

### What changed, in the contract

| Req | Change | Where |
|-----|--------|-------|
| R1 | `tokenURI` reads `uriGenerator` once. If it is non-zero **and has runtime code**, `generateURI` is called inside `try/catch`. If the call reverts or runs out of gas, execution falls through to `super.tokenURI(tokenId)`. A codeless generator skips the call entirely. | `tokenURI` |
| R2 | After `createAccount` (and after the existing F-1 `address(0)` → `InvalidAddress()` check, which comes first and is unchanged), `_validateTba(treeWallet, tokenId)` requires: (a) `code.length != 0`; (b) a `staticcall` to `supportsInterface(0x6faff5f1)` that succeeds and returns exactly the word `1`; (c) a `staticcall` to `token()` that succeeds, returns ≥ 96 bytes, and decodes to `(chainId, address(this), tokenId)`, compared against the **stored** `chainId`. Any failure → `InvalidTba()`. The whole mint reverts, so nothing persists. | `mintTree`, new `_validateTba` |
| R3 | `mintTree` rejects `spatialNullifier == bytes32(0)` with `InvalidNullifier()` (checked before the nullifier lookup, so no token id is consumed). `setURIGenerator` rejects a non-zero address with no code (`InvalidAddress()`). `address(0)` stays legal and still means "use the base path". | `mintTree`, `setURIGenerator` |
| R4 | Storage untouched. The only additions are two custom errors, one `private constant`, one interface declaration and one `private view` function. None of these occupy storage. | — |

Why each design choice:

- **R1, explicit code check plus `try/catch`.** `try/catch` alone does not cover the codeless case. Since solc 0.8.10 the
  `extcodesize` pre-check is skipped for calls that decode return data, so a call to a codeless address "succeeds"
  with empty returndata, and the `string` decode then fails in `tokenURI`'s own frame, which no `catch` clause
  reaches. The `generator.code.length != 0` guard closes that path.
- **R1, no gas cap on the generator call.** On-chain SVG generators can legitimately need tens of millions of gas in an
  `eth_call`, so no fixed cap was imposed. Out-of-gas recovery relies on EIP-150: the call can consume at most 63/64 of
  the remaining gas, and the 1/64 left over pays for the fallback (`_requireOwned` plus an empty string, a few
  thousand gas). The test gives `tokenURI` a 5,000,000 gas budget. A caller with roughly < 300k gas total could still
  run out in the fallback itself (see residuals).
- **R2, low-level `staticcall` (D3).** It cannot mutate state. It never reverts on its own. Every failure mode (missing
  function, revert, short returndata, wrong value) is turned into the same `InvalidTba()`. `token()` is decoded as three
  `uint256` words and the address is compared as `uint256(uint160(address(this)))`, so a dirty upper-bits address word
  is a mismatch, not a decoder panic. `supportsInterface` is compared as the raw word `== 1`, for the same reason
  (a `bool` decode of a dirty word would revert with no data).
- **R2, order of checks.** `address(0)` keeps its dedicated `InvalidAddress()` from F-1, so `test_H1_zeroRegistry_mintReverts`
  is unchanged and still passes. R2 checks run after it.
- **R3, errors.** `InvalidNullifier()` and `InvalidTba()` are new, as decided (D1). The setter reuses `InvalidAddress()`,
  which already means "bad address argument" everywhere else in the contract.

`initialize` was **not** changed: R3 names `setURIGenerator` only. A codeless generator can therefore still be installed
at initialization (or by an upgrade). R1 guards exactly that state (see `test_R1_zeroCodeGenerator_fallsBack`).

### R4 — storage layout, proven

1. **Compiler layout, before vs after, byte-identical.**
   `forge inspect src/BioRigCoreV5.sol:BioRigCoreV5 storageLayout` was captured before any edit
   (`evidence/storageLayout.before.txt`) and after (`evidence/storageLayout.after.txt`). `cmp` reports no difference.
   Both files have SHA-256 `6f16b5012f0e20e6db0d59b69026654c694249c0adb9a4526b5745b8091b4377`. The table (slots 0–7):
   `_nextTokenId` 0, `erc6551Registry` 1, `erc6551Implementation` 2, `chainId` 3, `bufferPool` 4, `uriGenerator` 5,
   `_trees` 6, `_activeNullifiers` 7.
2. **Full JSON layout, including struct members and types, identical to the verbatim original.** The raw `--json`
   dumps differ only in AST node ids (`astId`, plus the numeric suffix solc embeds in struct type ids, e.g.
   `t_struct(TreeStats)NNNN_storage`) and in the contract name. `evidence/normalize_layout.py` strips exactly those and
   keeps label, slot, offset and type for every variable and every `TreeStats` member, plus each type's encoding and size.
   Normalized, the original (`test/orig/OriginalV5.sol:OriginalBioRigCoreV5`), the pre-round contract and the hardened
   contract all hash to `d5dd06ff87acf04b8e3541ba2fa4af4449e73940bb556fbe2f463dd675183042`.
3. **Live upgrade from the verbatim original.** `test/UpgradeFromOriginal.t.sol::test_R4_upgradeFromVerbatimOriginal_preservesStateSlotForSlot`
   deploys `OriginalBioRigCoreV5` behind an `ERC1967Proxy` and writes state through it: three trees (one grown, one
   dead, one with the zero nullifier that the original allowed), a new generator, a new buffer pool and roles. It then
   UUPS-upgrades the proxy to the hardened implementation and asserts:
   - raw slots 0–7 are byte-identical, and so is the ERC-7201-namespaced ERC721 `_owners` entry;
   - every value reads back through the hardened ABI;
   - `tokenURI` works;
   - the next mint gets id 4 and passes TBA validation;
   - the pre-upgrade zero-nullifier tree can still be grown and killed; only *new* zero-nullifier mints are refused.
4. **Parents.** No import, base contract or inheritance order changed. The OZ v5 parents use ERC-7201 namespaced storage
   (H5 below), and the existing `test_upgrade_v6ReadsV5State_layoutPreserved` still passes.

### D2 — test fixture

`test/Base.t.sol` used `accountImpl = makeAddr("accountImpl")`, a codeless address. Every TBA was an ERC-1167 proxy
delegating to nothing, so `token()` returned empty data and R2 would have rejected every mint in the suite.
`test/mocks/TokenBoundAccount.sol::TokenBoundAccount` is now deployed in `setUp` and used as `accountImpl`. Like the
reference account, it keeps the binding in the proxy's runtime footer, not in storage: `token()` does
`extcodecopy(address(), …, 0x4d, 0x60)` (header 10 + implementation 20 + tail 15 = 0x2d bytes, then the salt, then
`chainId, tokenContract, tokenId`). `supportsInterface` returns true for `0x6faff5f1` and `0x01ffc9a7`.
`_expectedTba` still holds, and this was checked rather than assumed. It recomputes from `registry.account(accountImpl, …)`
with the new `accountImpl`. `testFuzz_tba_matchesRecomputation` (256 runs) passes. So do
`test_tba_matchesIndependentRecomputation` and `test_R2_conformingRegistry_mintSucceeds_tbaMatchesCreate2`, which rebuild
the init code from first principles, with no registry code involved.

Other existing tests adapted, not weakened:
- `ReentrantRegistry` now forwards to a conforming inner registry when it does not re-enter. Its benign mode used to
  return a synthetic address, which R2 correctly rejects. The hostile modes revert before returning and are unchanged.
- `testFuzz_mint_storesArbitraryStats`, `testFuzz_tba_matchesRecomputation` and `testFuzz_nullifierUniqueness` now
  `vm.assume(n != 0)`, because zero is rejected and has its own test. The invariant handler's nullifier pool never
  contains zero.
- `test_setURIGenerator_emitsAndStores` used `alice` (an EOA) as the generator and now uses a deployed `URIGeneratorMock`.
- `test_zeroNullifier_isAccepted` (I-5) was inverted to `test_zeroNullifier_isRejected`.

### D4 — the three behaviour-change tests, inverted (names kept as the record)

| Test | Old assertion | New assertion |
|------|---------------|---------------|
| `test_H2_arbitraryRegistry_addressIsInstalledUnchecked` | an unrelated codeless address is installed as the TBA, shared by two trees | both mints revert `InvalidTba()`; nullifiers inactive, balances 0, token counter still 1, `getTreeStats(1)` reverts |
| `test_H3_codelessGenerator_bricksTokenURI_untilReset` | `tokenURI` reverts with empty data for every token | `setURIGenerator(eoa)` reverts `InvalidAddress()`; the codeless state is planted with `vm.store` into slot 5 (D5, index confirmed by `forge inspect`, asserted in-test through `uriGenerator()`); `tokenURI` returns `""` for both tokens; resetting the generator restores real URIs |
| `test_H3_revertingGenerator_bubblesRevert_untilReset` | `GeneratorDown()` bubbles out of `tokenURI` | `tokenURI` returns `""` |

`test_H1_zeroRegistry_mintReverts` is unchanged and passes: F-1 is not regressed.

### New tests (one per scenario)

| Scenario | Test | Result |
|----------|------|--------|
| zero-code generator → falls back | `TokenURI.t.sol::test_R1_zeroCodeGenerator_fallsBack` (`vm.store` slot 5) | `""`, no revert |
| reverting generator → falls back | `test_R1_revertingGenerator_fallsBack` | `""`, no revert |
| generator burns all gas → falls back | `test_R1_gasExhaustingGenerator_fallsBack` (`GasBurningURIGenerator`, unbounded keccak loop; `tokenURI{gas: 5_000_000}`) | `""`, no revert |
| broken generator does not mask unknown token | `test_R1_unknownToken_stillReverts_withBrokenGenerator` | `InvalidTree()` |
| registry returns an EOA | `TokenBoundAccount.t.sol::test_R2_registryReturnsEoa_reverts` | `InvalidTba()`, nothing persisted |
| real account, wrong tokenId | `test_R2_registryReturnsAccountForWrongTokenId_reverts` (`MisbindingRegistry`; the test first shows the returned account is live and reports tokenId 2) | `InvalidTba()`, nothing persisted |
| real account, wrong tokenContract | `test_R2_registryReturnsAccountForWrongTokenContract_reverts` | `InvalidTba()`, nothing persisted |
| real account, wrong chainId (extra) | `test_R2_registryReturnsAccountForWrongChainId_reverts` | `InvalidTba()`, nothing persisted |
| contract with no `token()` | `test_R2_registryReturnsContractWithoutToken_reverts` (`NoTokenAccount` claims ERC-165 support, so it is the `token()` check that rejects it) | `InvalidTba()`, nothing persisted |
| correct `token()`, no ERC-165 support (extra) | `test_R2_registryReturnsContractWithoutErc165_reverts` (binding targets the predicted proxy address, asserted) | `InvalidTba()`, nothing persisted |
| conforming registry | `test_R2_conformingRegistry_mintSucceeds_tbaMatchesCreate2` | mint succeeds; TBA == independent CREATE2 == `_expectedTba`; `token()` == `(chainid, core, id)` |
| zero nullifier | `Nullifiers.t.sol::test_zeroNullifier_isRejected` | `InvalidNullifier()`, token id not consumed |
| `setURIGenerator(EOA)` | `TokenURI.t.sol::test_R3_setURIGenerator_eoa_reverts` | `InvalidAddress()`, generator unchanged |
| `setURIGenerator(address(0))` | `test_R3_setURIGenerator_zero_succeeds` | stored, event emitted, `tokenURI` → `""` |
| `setURIGenerator(contract)` | `test_R3_setURIGenerator_contract_succeeds` | stored |
| upgrade from the original | `UpgradeFromOriginal.t.sol::test_R4_upgradeFromVerbatimOriginal_preservesStateSlotForSlot` | see R4 |
| residual: lying account | `test_R2_residual_lyingAccountIsAccepted` | **accepted**, documents the residual trust |
| residual: malformed generator returndata | `test_R1_residual_malformedReturndata_stillReverts` | **reverts**, documents the residual |

### The new tests fail against the pre-change contract

Method: `src/BioRigCoreV5.sol` was replaced with the pre-round version (`git show HEAD:src/BioRigCoreV5.sol`, the
original plus the F-1 line). **Only** the two new error declarations and the `IERC6551Account` interface were added,
with no logic, so the tests compile. The hardened test suite (new fixture included) was then run against it, and the
hardened file was restored afterwards. Output (`evidence/prechange-run.txt`):

```
[FAIL: next call did not revert as expected] test_zeroNullifier_isRejected()
[FAIL: next call did not revert as expected] test_H2_arbitraryRegistry_addressIsInstalledUnchecked()
[FAIL: next call did not revert as expected] test_R2_registryReturnsAccountForWrongChainId_reverts()
[FAIL: next call did not revert as expected] test_R2_registryReturnsAccountForWrongTokenContract_reverts()
[FAIL: next call did not revert as expected] test_R2_registryReturnsAccountForWrongTokenId_reverts()
[FAIL: next call did not revert as expected] test_R2_registryReturnsContractWithoutErc165_reverts()
[FAIL: next call did not revert as expected] test_R2_registryReturnsContractWithoutToken_reverts()
[FAIL: next call did not revert as expected] test_R2_registryReturnsEoa_reverts()
[FAIL: next call did not revert as expected] test_H3_codelessGenerator_bricksTokenURI_untilReset()
[FAIL: GeneratorDown()] test_H3_revertingGenerator_bubblesRevert_untilReset()
[FAIL: EvmError: Revert] test_R1_gasExhaustingGenerator_fallsBack()
[FAIL: GeneratorDown()] test_R1_revertingGenerator_fallsBack()
[FAIL: EvmError: Revert] test_R1_zeroCodeGenerator_fallsBack()
[FAIL: next call did not revert as expected] test_R3_setURIGenerator_eoa_reverts()
[PASS] test_H1_zeroRegistry_mintReverts()                        <- F-1, already fixed pre-round
[PASS] test_R2_conformingRegistry_mintSucceeds_tbaMatchesCreate2() <- happy path, expected to pass
[PASS] test_R2_residual_lyingAccountIsAccepted()                 <- residual, accepted before and after
[PASS] test_R1_unknownToken_stillReverts_withBrokenGenerator()   <- InvalidTree check precedes the generator
[PASS] test_R3_setURIGenerator_zero_succeeds()                   <- zero was always legal
[PASS] test_R3_setURIGenerator_contract_succeeds()               <- contracts were always legal
```

(The run also included `test/orig/IndependentH1.t.sol`, which targets the frozen original and passes as before.)
All four hardening areas (R1 fallback, R2 validation, R3 nullifier and setter) have tests that fail without the
contract change and pass with it. The hardening is what makes them pass. They were not written to fit the code.
(`test_R1_residual_malformedReturndata_stillReverts` and the R4 upgrade test were added after this run. The first
documents a residual, and the second is not a behaviour-change test.)

### Updated verdicts for previously open items

| Item | Before | Now |
|------|--------|-----|
| **I-1 / H2** unchecked registry account | documented trust assumption | **FIXED (R2), with residual trust.** The returned account must be a contract that reports `IERC6551Account` support and claims exactly this token's binding. EOAs, wrong-token accounts and contracts without `token()` are rejected. |
| **L-1 / H3** generator availability (codeless / reverting generator reverts `tokenURI`) | Low, documented, not fixed | **FIXED (R1 + R3).** `tokenURI` no longer reverts on a codeless, reverting or gas-exhausting generator. The setter refuses codeless addresses. |
| **I-6** empty fallback | documented | **Still open, and now more visible.** The R1 fallback is `super.tokenURI`, and `_baseURI()` is not overridden, so the fallback returns **the empty string**. "Not bricked" is not the same as "useful metadata". While a generator is broken, marketplaces get `""`, not an error. That is arguably harder to notice than a revert. No `_baseURI` override was added (out of scope; it would need a storage or config decision). |
| **I-5** zero nullifier accepted | documented | **FIXED (R3)** for new mints. A zero-nullifier tree minted before an upgrade stays valid and manageable (tested). |
| **I-8** zero checks | informational | `setURIGenerator` now also checks code. `initialize` still accepts a codeless generator (not in R3), and R1 makes that harmless for availability. |
| **F-1 / H1** | fixed | unchanged, still passing |

### Residual trust after hardening

1. **A registry can return a contract that lies about `token()`.** R2 checks what the account *claims*, not where it
   came from. A hostile registry can return an attacker contract that reports ERC-6551 support and echoes
   `(chainId, this, tokenId)`. It is then accepted as the tree's wallet (`test_R2_residual_lyingAccountIsAccepted`
   proves it). Closing this would mean recomputing the canonical registry's CREATE2 address on-chain, which ties the
   contract to one registry and one proxy bytecode. That was not requested. The registry is fixed at `initialize` with
   no setter, so this still needs a trusted role (init-time admin or `UPGRADER_ROLE`).
2. **`erc6551Implementation` is trusted.** Validation calls through the proxy into the implementation. An
   implementation that reports a correct binding but has hostile `execute`/`owner` logic passes.
3. **The binding is checked once, at mint.** Reference accounts are immutable, so this is sufficient for them. An
   upgradeable account implementation could change its answer later.
4. **Stored `chainId` is trusted (I-4 unchanged).** R2 compares against the stored value, not `block.chainid`. With a
   wrong `chainId` from `initialize`, conforming accounts are bound to the foreign chain and pass the check consistently.
5. **Generator residuals.** (a) Malformed-but-successful returndata is decoded in `tokenURI`'s frame, so it still
   reverts (`test_R1_residual_malformedReturndata_stillReverts`). (b) A return bomb (a huge successful return) is copied
   into memory by `try` and can exhaust the caller's gas. (c) Out-of-gas recovery relies on the EIP-150 1/64 remainder,
   so a caller budget below roughly 300k gas could run out during the fallback. (d) Each `tokenURI` call may consume up
   to the caller's whole gas budget (it is a view, so only `eth_call` cost).
6. **Mint gas.** The validation `staticcall`s forward all gas. A hostile account can make `mintTree` run out of gas, but
   a hostile registry could already revert the mint, so this adds no new power.

---

## Defects (round 1 audit; verdicts updated above where the hardening round changed them)

### F-1 — A registry returning `address(0)` produces a minted NFT that can never be used (H1) — **Low** — FIXED

- **Test:** `test/TokenBoundAccount.t.sol::test_H1_zeroRegistry_mintReverts` (uses `test/mocks/Registries.sol::ZeroRegistry`).
- **Failure against the original contract** (`forge test --match-test test_H1_zeroRegistry_mintReverts -vvvv`):
  `[FAIL: next call did not revert as expected]`. The trace shows
  `ZeroRegistry::createAccount(accountImpl, 0xe929…136f, 31337, proxy, 1) ← [Return] 0x0000000000000000000000000000000000000000`,
  then `emit Transfer(0x0 → planter, tokenId: 1)`, then `emit TreeMinted(tokenId: 1, tba: 0x0000…0000, …)`, and `mintTree` returned `1`.
- **Root cause:** `mintTree` (original line 117) stores the registry's return value as `tbaAddress` without checking it.
  Every other path uses `tbaAddress == address(0)` to mean "the tree does not exist": `updateTreeGrowth` (l.147),
  `reportMortality` (l.161), `getTreeStats` (l.171) and `tokenURI` (l.182). With `tbaAddress = 0x0`, token 1 is owned by
  `planter` in ERC-721 terms, yet all four revert `InvalidTree()` for it. `reportMortality` is the only thing that
  releases a nullifier, and it cannot run, so `_activeNullifiers[N]` stays `true` forever. That plot can never be minted
  again unless the contract is upgraded.
- **Why the test is at fault or the contract is:** the contract. The test asserts the correct behaviour: the mint reverts
  and nothing persists.
- **Severity:** Low. The impact would be serious (a permanently unusable token and a permanently locked plot), but the
  registry is fixed at `initialize` with no setter, so only an admin or an upgrade can install a bad one. The reference
  ERC-6551 registry (`erc6551/reference`, `ERC6551Registry.sol`) reverts with `AccountCreationFailed` rather than
  returning 0. The fix is defence-in-depth against a buggy or non-reference registry.
- **Fix:** revert `InvalidAddress()` when `treeWallet == address(0)`. After the fix the test passes and asserts:
  nullifier inactive, `balanceOf(planter) == 0`, and `_nextTokenId` (slot 0) still `1`.

### L-1 — A codeless or reverting `uriGenerator` makes `tokenURI` revert for every token (H3) — **Low (availability)** — FIXED in the hardening round (R1 + R3)

- **Superseded.** Everything below describes the round-1 behaviour. Both tests have since been inverted (D4) and now
  assert that `tokenURI` falls back to `""`. The round-1 analysis is kept as the record of why.
- **Tests:** `test/TokenURI.t.sol::test_H3_codelessGenerator_bricksTokenURI_untilReset` and
  `test_H3_revertingGenerator_bubblesRevert_untilReset`.
- **Root cause:** `tokenURI` (l.184–185) makes a high-level call to `uriGenerator` whenever it is non-zero. For an address
  with no code, solc ≥0.8.10 skips the `extcodesize` check on calls that return data. The call "succeeds" with empty
  returndata, and ABI-decoding the `string` then reverts **with empty revert data**. That is why the test asserts
  `vm.expectRevert(bytes(""))`: there is no custom error to name, and the empty-data assertion is exact. A generator that
  reverts has its error bubbled up (`GeneratorDown()`, asserted specifically).
- **Impact, measured:** only `tokenURI` is affected. The same test shows `getTreeStats`, transfers and the rest still work,
  and one `setURIGenerator` call from the same admin restores `tokenURI` immediately. No funds or state are at risk.
  Causing it requires `DEFAULT_ADMIN_ROLE`.
- **Why not fixed:** a code-length check in `setURIGenerator` would only catch the codeless case, not a reverting
  generator. A `try/catch` fallback in `tokenURI` would change behaviour silently (metadata would quietly become `""`).
  Neither counts as a minimal fix for an issue the admin causes and can undo in one call. Recommendation: validate
  `code.length` in `setURIGenerator`/`initialize` if the team wants the guard.

---

## Informational

| ID | Observation | Test | Status |
|----|-------------|------|--------|
| I-1 | **FIXED in the hardening round (R2); see residual trust.** Round-1 text: **(H2)** The account returned by the registry is never checked to be bound to the token. A registry returning an unrelated address gets it installed as the TBA. With `ArbitraryRegistry`, two trees end up sharing one codeless "wallet". This is a trust assumption, not a flaw in the contract's own logic: the registry is set once in `initialize` with no setter, so a hostile registry needs `DEFAULT_ADMIN_ROLE` at init or `UPGRADER_ROLE`, and either can do worse. A real check would mean re-deriving the reference registry's CREATE2 formula on-chain (a feature, tied to one registry implementation), so it is not added. | `test_H2_arbitraryRegistry_addressIsInstalledUnchecked` (inverted), `test_H2_registryIsNotChangeableWithoutUpgrade`, `test_R2_*` | fixed (R2) |
| I-2 | **(H4, H6 reentrancy-events)** `_safeMint` calls `onERC721Received` on the planter **before** `emit TreeMinted`. `updateTreeGrowth` and `reportMortality` are not `nonReentrant`, so a planter contract that **also holds VERIFIER_ROLE** can call them from the callback. Measured effect: `GrowthUpdated` (or `TreeMortalityReported`) is logged before `TreeMinted` for the same token. State stays consistent (the tree record is written before `_safeMint`). A planter without the role gets `AccessControlUnauthorizedAccount`. This only affects indexers that assume event order. | `test_H4_verifierPlanter_growsDuringMintCallback_eventOrderOnly`, `test_H4_verifierPlanter_killsDuringMintCallback_consistent`, `test_H4_nonVerifierPlanter_callbackReverts` | documented |
| I-3 | `pause()` blocks mint, growth and mortality but **not** ERC-721 transfers or approvals (`_update` is not overridden). Admin setters and upgrades also work while paused. This may be intended; it should be written down. | `test_paused_transfersAndApprovalsStillWork`, `test_paused_adminConfigStillWorks`, `test_paused_upgradeStillWorks` | documented |
| I-4 | `initialize` accepts any `_chainId`. It is not checked against `block.chainid`. With the reference account implementation, a wrong value makes every TBA report a foreign chain. | `test_initialize_acceptsForeignChainId` | documented |
| I-5 | `bytes32(0)` was accepted as a spatial nullifier. It is now rejected with `InvalidNullifier()` (R3). | `test_zeroNullifier_isRejected` (inverted), `test_R4_upgradeFromVerbatimOriginal_*` | fixed (R3) |
| I-6 | With no generator set, `tokenURI` falls back to `ERC721Upgradeable.tokenURI`. `_baseURI()` is not overridden, so the result is `""`. Since R1 this is also what a broken generator yields: no revert, but empty metadata. | `test_tokenURI_noGeneratorFallback_returnsEmpty`, `test_tokenURI_noGeneratorFromInit`, `test_R1_*`, `test_H3_*` | documented, still open (no `_baseURI` override, out of scope) |
| I-7 | **(H6)** `uint64(block.timestamp)` (l.128, l.153) truncates only after 2^64 − 1 s, which is about 5.8×10^11 years. The test warps to `type(uint64).max` (stored exactly) and to `type(uint64).max + 1` (stored as `0`). No practical impact. | `test_H6_timestampCast_truncatesOnlyBeyondUint64` | informational |
| I-8 | **(H6 missing-zero-check)** `_uriGenerator` / `setURIGenerator` accept `address(0)`, and that is intended: zero selects the fallback path, which is tested. The other address inputs are already zero-checked (`initialize`, `setBufferPool`, `mintTree` planter), and after F-1 the registry return is too. `erc6551Implementation` has no code check, but the reference registry doesn't require one either. Hardening round: `setURIGenerator` also rejects codeless non-zero addresses (R3), and the registry's return is validated in full (R2). | `test_initialize_revertsOnZero*`, `test_setBufferPool_revertsOnZero`, `test_setURIGenerator_toZero` | informational |

## Hypotheses refuted

- **H4, "updateTreeGrowth is exploitable because it lacks nonReentrant": REFUTED as an exploit. It is only a style
  inconsistency.** `updateTreeGrowth` and `reportMortality` make **no external calls at all**. `test_H4_growthPath_makesNoExternalCalls`
  and `test_H4_mortalityPath_makesNoExternalCalls` record every account touched (`vm.startStateDiffRecording`) and
  assert each call went only to the proxy or its implementation. Since nothing on those paths can hand control to an
  attacker, there is nothing to re-enter through. The only way to reach them mid-transaction is from `mintTree`'s
  `onERC721Received` callback, and only for a caller holding VERIFIER_ROLE (see I-2). A hostile **registry**
  re-entering during `createAccount` is stopped everywhere: nested `mintTree` hits `ReentrancyGuardReentrantCall` (with
  or without the role), nested growth or mortality hits `AccessControlUnauthorizedAccount` or `InvalidTree` (the tree
  record isn't written yet), and the outer mint reverts atomically with no state persisted (`test/Reentrancy.t.sol`, 6 tests).
- **H5, "missing `__gap` makes upgrades unsafe": REFUTED.** Every OZ v5 parent (Initializable, ERC721, AccessControl,
  Pausable, ReentrancyGuard, UUPS) uses ERC-7201 namespaced storage. The only sequential slots belong to BioRigCoreV5
  itself (slots 0–7: `_nextTokenId, erc6551Registry, erc6551Implementation, chainId, bufferPool, uriGenerator, _trees, _activeNullifiers`).
  A `__gap` only protects a base contract whose children add variables after it. Appending to the most-derived contract
  is safe, and that is how `test/mocks/BioRigCoreV6.sol` adds `v6Marker`. `test_upgrade_v6ReadsV5State_layoutPreserved`
  snapshots raw slots 0–7, upgrades, and asserts they are byte-identical, that `v6Marker` lands in slot 8, and that every
  piece of V5 state reads back correctly through V6: trees (alive and dead), nullifiers, roles, approvals, pause state,
  generator, buffer pool and the private token counter. `test_H5_parentsUseNamespacedStorage` locates ERC721 `_owners`
  inside its namespace. A gap would only matter if someone later **inherits from** BioRigCoreV5 and adds state in a
  different order, which is a convention, not a present defect. No gap was added.
- **H6, "timestamp cast, missing-zero-check and reentrancy-events are real issues": no real impact shown.** They are
  ranked informational above (I-2, I-7, I-8).
- **H2 and H3 were not refuted.** Both behaviours were confirmed by tests in round 1 and rated I-1 (a trust assumption)
  and L-1 (admin-caused availability). Both are hardened in this round (R2, R1 + R3).

## Could not verify

- **Interaction with the live canonical ERC-6551 registry and account implementation.** No fork test was run.
  `ERC6551RegistryMock` reproduces the reference registry's init code. Its constants were checked against
  `github.com/erc6551/reference/src/ERC6551Registry.sol`: header `3d60ad80600a3d3981f3363d3d373d3d3d363d73`, footer
  `5af43d82803e903d91602b57fd5bf3`, init code length 0xb7, CREATE2 with the raw salt. Whether the deployed registry
  behaves identically on a given chain is not established here.
- **Behaviour of the canonical deployed ERC-6551 account implementation.** Since the hardening round, account code is
  executed: `test/mocks/TokenBoundAccount.sol` is a minimal reference-style account (`token()` from the runtime footer,
  ERC-165). It is not the reference `ERC6551Account`, and `owner()`/`execute` are not exercised. That the canonical
  implementation reports `supportsInterface(0x6faff5f1) == true` comes from the ERC-6551 spec and was not tested here
  against deployed bytecode. If a deployment's implementation does not report it, **every mint reverts `InvalidTba()`**.
  Check this with a fork test before upgrading.
- **Off-chain impact of I-2** (whether any indexer actually depends on `TreeMinted` coming before `GrowthUpdated`).

## How the suite was checked for vacuous passes

- The first invariant campaign passed with **every** `mint`/`togglePause` call reverting. The cause was in the test, not
  the contract: `vm.prank(verifier)` was consumed by the `core.isNullifierActive(n)` / `core.paused()` view call placed
  between the prank and the intended call, so `mintTree` ran as the handler and reverted `AccessControlUnauthorizedAccount`.
  Fixed by moving each `vm.prank` to directly before the call. The campaign now reports 0 reverts with `fail-on-revert = true`.
- Mutation checks on the invariants, each reverted with `git checkout` afterwards:
  (a) deleting `_activeNullifiers[tree.spatialNullifier] = false;` from `reportMortality` → `invariant_activeNullifierHasLiveTree` FAILS;
  (b) deleting `_activeNullifiers[spatialNullifier] = true;` from `mintTree` → `invariant_liveTreeNullifiersActiveAndUnique`
  ("live tree nullifier inactive") and `invariant_activeNullifierHasLiveTree` both FAIL.
- `test_H1_zeroRegistry_mintReverts` failed against the original contract and passes after the fix, so it does detect the defect.
- Hardening round: every R1/R2/R3 behaviour-change test was run against the pre-change contract and failed (see
  "The new tests fail against the pre-change contract").

## Layout of `test/`

`Base.t.sol` (proxy fixture, real account implementation), `Lifecycle`, `AccessControl`, `Pausing`, `Nullifiers`, `Mint`,
`TokenBoundAccount`, `Growth`, `Mortality`, `TokenURI`, `ERC721Behavior`, `Upgrades`, `UpgradeFromOriginal`, `Reentrancy`,
`Invariant` (`*.t.sol`), plus `orig/IndependentH1.t.sol` against the frozen `orig/OriginalV5.sol`.
Mocks are in `test/mocks/`:
- `Registries.sol`: conforming, zero, arbitrary, misbinding and re-entrant registries;
- `TokenBoundAccount.sol`: the reference-style account, plus the no-`token()`, no-ERC-165 and lying accounts;
- `Misc.sol`: URI generators (working, reverting, gas-burning, malformed), rejecting/wrong-selector/accepting/verifier
  planters, and a non-UUPS implementation;
- `BioRigCoreV6.sol`.

Evidence files: `evidence/storageLayout.{before,after}.txt` (byte-identical tables), `evidence/storageLayout.{original,before,after}.json`
and `.normalized.json`, `evidence/normalize_layout.py`, `evidence/prechange-run.txt`, `evidence/forge-test.txt`.

## Evidence: final `forge test`

```
Compiling 16 files with Solc 0.8.28
Solc 0.8.28 finished in 8.06s
Compiler run successful!

Ran 1 test for test/orig/IndependentH1.t.sol:IndependentH1Test
[PASS] test_H1_zeroRegistry_mintsUnusableToken_andLocksPlot() (gas: 329309)
Suite result: ok. 1 passed; 0 failed; 0 skipped; finished in 1.41ms (367.72µs CPU time)

Ran 25 tests for test/AccessControl.t.sol:AccessControlTest
[PASS] test_grantRole_byNonAdmin_reverts() (gas: 45358)
[PASS] test_grantRole_byVerifier_reverts() (gas: 47381)
[PASS] test_grantRole_verifier() (gas: 366049)
[PASS] test_renounceAdmin_locksOutAdminFunctions() (gas: 118495)
[PASS] test_renounceRole_revertsOnBadConfirmation() (gas: 50622)
[PASS] test_renounceRole_verifier() (gas: 50992)
[PASS] test_revokeRole_byNonAdmin_reverts() (gas: 47304)
[PASS] test_revokeRole_verifier_blocksMinting() (gas: 113113)
[PASS] test_roleConstants() (gas: 43984)
[PASS] test_setBufferPool_emitsAndStores() (gas: 62389)
[PASS] test_setBufferPool_revertsOnZero() (gas: 49487)
[PASS] test_setURIGenerator_emitsAndStores() (gas: 354785)
[PASS] test_setURIGenerator_toZero() (gas: 48871)
[PASS] test_unauth_mintTree() (gas: 52987)
[PASS] test_unauth_mintTree_adminIsNotVerifier() (gas: 52985)
[PASS] test_unauth_pause() (gas: 39885)
[PASS] test_unauth_pause_byVerifier() (gas: 39885)
[PASS] test_unauth_reportMortality() (gas: 321016)
[PASS] test_unauth_setBufferPool() (gas: 42388)
[PASS] test_unauth_setURIGenerator() (gas: 40042)
[PASS] test_unauth_setURIGenerator_byVerifier() (gas: 40087)
[PASS] test_unauth_unpause() (gas: 94859)
[PASS] test_unauth_updateTreeGrowth() (gas: 321608)
[PASS] test_unauth_updateTreeGrowth_byOwner() (gas: 319584)
[PASS] test_unauth_upgradeToAndCall() (gas: 44012)
Suite result: ok. 25 passed; 0 failed; 0 skipped; finished in 5.24ms (2.76ms CPU time)

Ran 11 tests for test/ERC721Behavior.t.sol:ERC721BehaviorTest
[PASS] test_approve_byNonOwner_reverts() (gas: 45163)
[PASS] test_approve_thenTransferByApproved() (gas: 183465)
[PASS] test_ownerOf_unknown_reverts() (gas: 16111)
[PASS] test_safeTransfer_toAcceptingReceiver() (gas: 319541)
[PASS] test_safeTransfer_toRejectingReceiver_reverts() (gas: 191095)
[PASS] test_setApprovalForAll_operatorTransfers() (gas: 164172)
[PASS] test_supportsInterface() (gas: 64065)
[PASS] test_transfer_byStranger_reverts() (gas: 50189)
[PASS] test_transfer_deadTree_isAllowed() (gas: 161834)
[PASS] test_transfer_liveTree_keepsStatsAndTba() (gas: 155352)
[PASS] test_transfer_toZero_reverts() (gas: 40442)
Suite result: ok. 11 passed; 0 failed; 0 skipped; finished in 3.17ms (1.24ms CPU time)

Ran 8 tests for test/Mortality.t.sol:MortalityTest
[PASS] test_mortality_deadTreeCannotGrow() (gas: 88538)
[PASS] test_mortality_isOneShot() (gas: 87967)
[PASS] test_mortality_marksDead_releasesNullifier_emits() (gas: 83802)
[PASS] test_mortality_onlyAffectsTarget() (gas: 353823)
[PASS] test_mortality_secondReportCannotReleaseReplantedNullifier() (gas: 370558)
[PASS] test_mortality_statsStillReadableAfterDeath() (gas: 87004)
[PASS] test_mortality_unknownToken_reverts() (gas: 43850)
[PASS] test_mortality_whilePaused_reverts() (gas: 96586)
Suite result: ok. 8 passed; 0 failed; 0 skipped; finished in 9.87ms (1.18ms CPU time)

Ran 15 tests for test/Growth.t.sol:GrowthTest
[PASS] testFuzz_growth_monotonic(uint96,uint96) (runs: 256, μ: 81013, ~: 88114)
[PASS] test_H4_growthPath_makesNoExternalCalls() (gas: 72615)
[PASS] test_H4_mortalityPath_makesNoExternalCalls() (gas: 73775)
[PASS] test_H6_timestampCast_truncatesOnlyBeyondUint64() (gas: 135349)
[PASS] test_growth_biomassDecrease_reverts() (gas: 49037)
[PASS] test_growth_bothDecrease_reverts() (gas: 48858)
[PASS] test_growth_dbhDecrease_reverts() (gas: 48923)
[PASS] test_growth_deadTree_reverts() (gas: 88567)
[PASS] test_growth_emitsEvent() (gas: 55892)
[PASS] test_growth_equalValuesAllowed_refreshesTimestamp() (gas: 67771)
[PASS] test_growth_failedUpdateLeavesStateUntouched() (gas: 63508)
[PASS] test_growth_maxValues() (gas: 67549)
[PASS] test_growth_tokenZero_reverts() (gas: 44430)
[PASS] test_growth_unknownToken_reverts() (gas: 44500)
[PASS] test_growth_updatesStatsAndTimestamp() (gas: 103923)
Suite result: ok. 15 passed; 0 failed; 0 skipped; finished in 28.26ms (26.33ms CPU time)

Ran 12 tests for test/Pausing.t.sol:PausingTest
[PASS] test_pause_twice_reverts() (gas: 41712)
[PASS] test_paused_adminConfigStillWorks() (gas: 167940)
[PASS] test_paused_blocksGrowth() (gas: 42109)
[PASS] test_paused_blocksMint() (gas: 57009)
[PASS] test_paused_blocksMortality() (gas: 49590)
[PASS] test_paused_flag() (gas: 12632)
[PASS] test_paused_mintCheckedBeforeRole() (gas: 48190)
[PASS] test_paused_readPathsStillWork() (gas: 125893)
[PASS] test_paused_transfersAndApprovalsStillWork() (gas: 139951)
[PASS] test_paused_upgradeStillWorks() (gas: 56760)
[PASS] test_unpause_restores() (gas: 415666)
[PASS] test_unpause_whenNotPaused_reverts() (gas: 72409)
Suite result: ok. 12 passed; 0 failed; 0 skipped; finished in 2.07ms (888.04µs CPU time)

Ran 9 tests for test/Reentrancy.t.sol:ReentrancyTest
[PASS] test_H4_nonVerifierPlanter_callbackReverts() (gas: 554725)
[PASS] test_H4_verifierPlanter_growsDuringMintCallback_eventOrderOnly() (gas: 654618)
[PASS] test_H4_verifierPlanter_killsDuringMintCallback_consistent() (gas: 613180)
[PASS] test_benignModeStillMints() (gas: 364487)
[PASS] test_reenterGrowth_withRole_seesNoTree() (gas: 293729)
[PASS] test_reenterGrowth_withoutRole_reverts() (gas: 232458)
[PASS] test_reenterMint_withVerifierRole_blockedByGuard() (gas: 288809)
[PASS] test_reenterMint_withoutRole_blockedByGuard() (gas: 227045)
[PASS] test_reenterMortality_withRole_seesNoTree() (gas: 293714)
Suite result: ok. 9 passed; 0 failed; 0 skipped; finished in 3.10ms (1.72ms CPU time)

Ran 13 tests for test/Lifecycle.t.sol:LifecycleTest
[PASS] test_implementation_cannotBeInitialized() (gas: 42670)
[PASS] test_implementation_hasNoAdminAndIsUnusable() (gas: 82636)
[PASS] test_implementation_initializersDisabled() (gas: 7852)
[PASS] test_initialize_acceptsForeignChainId() (gas: 440807)
[PASS] test_initialize_allowsZeroUriGenerator() (gas: 441023)
[PASS] test_initialize_revertsOnDoubleInit() (gas: 49980)
[PASS] test_initialize_revertsOnDoubleInit_evenByAdmin() (gas: 50214)
[PASS] test_initialize_revertsOnZeroAccountImplementation() (gas: 166455)
[PASS] test_initialize_revertsOnZeroAdmin() (gas: 166333)
[PASS] test_initialize_revertsOnZeroBufferPool() (gas: 166478)
[PASS] test_initialize_revertsOnZeroRegistry() (gas: 166406)
[PASS] test_initialize_setsState() (gas: 170430)
[PASS] test_initialize_zeroAdminCheckedBeforeOtherArgs() (gas: 159321)
Suite result: ok. 13 passed; 0 failed; 0 skipped; finished in 1.90ms (837.76µs CPU time)

Ran 16 tests for test/TokenBoundAccount.t.sol:TokenBoundAccountTest
[PASS] testFuzz_tba_matchesRecomputation(address,bytes32) (runs: 256, μ: 310082, ~: 310222)
[PASS] test_H1_zeroRegistry_mintReverts() (gas: 758163)
[PASS] test_H2_arbitraryRegistry_addressIsInstalledUnchecked() (gas: 914989)
[PASS] test_H2_registryIsNotChangeableWithoutUpgrade() (gas: 14756)
[PASS] test_R2_conformingRegistry_mintSucceeds_tbaMatchesCreate2() (gas: 328696)
[PASS] test_R2_registryReturnsAccountForWrongChainId_reverts() (gas: 1228232)
[PASS] test_R2_registryReturnsAccountForWrongTokenContract_reverts() (gas: 1228205)
[PASS] test_R2_registryReturnsAccountForWrongTokenId_reverts() (gas: 1339638)
[PASS] test_R2_registryReturnsContractWithoutErc165_reverts() (gas: 945553)
[PASS] test_R2_registryReturnsContractWithoutToken_reverts() (gas: 931324)
[PASS] test_R2_registryReturnsEoa_reverts() (gas: 807328)
[PASS] test_R2_residual_lyingAccountIsAccepted() (gas: 1063930)
[PASS] test_createAccount_calledWithExpectedArgs() (gas: 289693)
[PASS] test_salt_isDeterministic() (gas: 1050)
[PASS] test_tba_distinctPerToken() (gas: 571347)
[PASS] test_tba_matchesIndependentRecomputation() (gas: 342072)
Suite result: ok. 16 passed; 0 failed; 0 skipped; finished in 64.19ms (61.84ms CPU time)

Ran 8 tests for test/Nullifiers.t.sol:NullifiersTest
[PASS] testFuzz_nullifierUniqueness(bytes32,bytes32) (runs: 256, μ: 539766, ~: 539969)
[PASS] test_killingReplantedTree_releasesAgain() (gas: 630982)
[PASS] test_mint_activatesNullifier() (gas: 316958)
[PASS] test_mint_duplicateNullifier_doesNotConsumeTokenId() (gas: 600876)
[PASS] test_mint_duplicateNullifier_reverts() (gas: 327207)
[PASS] test_mortality_releasesNullifier_andAllowsReplant() (gas: 698008)
[PASS] test_replantedTree_distinctTba() (gas: 613072)
[PASS] test_zeroNullifier_isRejected() (gas: 78577)
Suite result: ok. 8 passed; 0 failed; 0 skipped; finished in 57.74ms (56.12ms CPU time)

Ran 1 test for test/UpgradeFromOriginal.t.sol:UpgradeFromOriginalTest
[PASS] test_R4_upgradeFromVerbatimOriginal_preservesStateSlotForSlot() (gas: 5166198)
Suite result: ok. 1 passed; 0 failed; 0 skipped; finished in 2.33ms (1.13ms CPU time)

Ran 12 tests for test/Upgrades.t.sol:UpgradesTest
[PASS] test_H5_parentsUseNamespacedStorage() (gas: 291472)
[PASS] test_proxy_pointsAtImplementation() (gas: 11063)
[PASS] test_treeStatsPacking() (gas: 305383)
[PASS] test_upgrade_adminWithoutUpgraderRole_reverts() (gas: 2965657)
[PASS] test_upgrade_byNonUpgrader_reverts() (gas: 2932628)
[PASS] test_upgrade_byUpgrader() (gas: 2946488)
[PASS] test_upgrade_byVerifier_reverts() (gas: 2929864)
[PASS] test_upgrade_calledOnImplementationDirectly_reverts() (gas: 2919687)
[PASS] test_upgrade_grantedUpgrader() (gas: 2997071)
[PASS] test_upgrade_toNonUUPS_reverts() (gas: 154760)
[PASS] test_upgrade_v6ReadsV5State_layoutPreserved() (gas: 4730054)
[PASS] test_upgrade_v6ReinitializerRunsOnce() (gas: 3050344)
Suite result: ok. 12 passed; 0 failed; 0 skipped; finished in 4.13ms (2.85ms CPU time)

Ran 12 tests for test/Mint.t.sol:MintTest
[PASS] testFuzz_mint_storesArbitraryStats(address,bytes32,uint96,uint96) (runs: 256, μ: 312668, ~: 312772)
[PASS] test_mint_emitsTreeMintedAndTransfer() (gas: 302235)
[PASS] test_mint_firstIdIsOne_andIncrements() (gas: 842602)
[PASS] test_mint_maxInitialStats() (gas: 316202)
[PASS] test_mint_storesStats() (gas: 311605)
[PASS] test_mint_toAcceptingContract() (gas: 530183)
[PASS] test_mint_toRejectingContract_revertsAtomically() (gas: 706402)
[PASS] test_mint_toWrongSelectorContract_reverts() (gas: 442488)
[PASS] test_mint_whilePaused_reverts() (gas: 103138)
[PASS] test_mint_withoutVerifierRole_reverts() (gas: 50933)
[PASS] test_mint_zeroInitialStats() (gas: 388191)
[PASS] test_mint_zeroPlanter_reverts() (gas: 56849)
Suite result: ok. 12 passed; 0 failed; 0 skipped; finished in 36.60ms (37.09ms CPU time)

Ran 16 tests for test/TokenURI.t.sol:TokenURITest
[PASS] test_H3_codelessGenerator_bricksTokenURI_untilReset() (gas: 550857)
[PASS] test_H3_revertingGenerator_bubblesRevert_untilReset() (gas: 293576)
[PASS] test_R1_gasExhaustingGenerator_fallsBack() (gas: 5070953)
[PASS] test_R1_residual_malformedReturndata_stillReverts() (gas: 174737)
[PASS] test_R1_revertingGenerator_fallsBack() (gas: 232213)
[PASS] test_R1_unknownToken_stillReverts_withBrokenGenerator() (gas: 220609)
[PASS] test_R1_zeroCodeGenerator_fallsBack() (gas: 44821)
[PASS] test_R3_setURIGenerator_contract_succeeds() (gas: 350492)
[PASS] test_R3_setURIGenerator_eoa_reverts() (gas: 54086)
[PASS] test_R3_setURIGenerator_zero_succeeds() (gas: 80557)
[PASS] test_tokenURI_generatorPath() (gas: 183518)
[PASS] test_tokenURI_noGeneratorFallback_returnsEmpty() (gas: 63833)
[PASS] test_tokenURI_noGeneratorFromInit() (gas: 792427)
[PASS] test_tokenURI_passesStatsToGenerator() (gas: 34212)
[PASS] test_tokenURI_unknownToken_reverts() (gas: 21997)
[PASS] test_tokenURI_unknownToken_reverts_noGenerator() (gas: 55648)
Suite result: ok. 16 passed; 0 failed; 0 skipped; finished in 17.95ms (17.84ms CPU time)

Ran 1 test for test/Invariant.t.sol:InvariantTest
[PASS]
InvariantTest invariants:
[PASS] invariant_activeNullifierHasLiveTree
[PASS] invariant_liveTreeNullifiersActiveAndUnique
[PASS] invariant_statsMatchGhostAndAreConsistent
[PASS] invariant_tokenCounter
 InvariantTest invariants (runs: 128, calls: 12800, reverts: 0)

╭-------------+-------------+-------+---------+----------╮
| Contract    | Selector    | Calls | Reverts | Discards |
+========================================================+
| TreeHandler | grow        | 2210  | 0       | 0        |
|-------------+-------------+-------+---------+----------|
| TreeHandler | kill        | 2125  | 0       | 0        |
|-------------+-------------+-------+---------+----------|
| TreeHandler | mint        | 2042  | 0       | 0        |
|-------------+-------------+-------+---------+----------|
| TreeHandler | shrink      | 2126  | 0       | 0        |
|-------------+-------------+-------+---------+----------|
| TreeHandler | togglePause | 2151  | 0       | 0        |
|-------------+-------------+-------+---------+----------|
| TreeHandler | transfer    | 2146  | 0       | 0        |
╰-------------+-------------+-------+---------+----------╯

Suite result: ok. 1 passed; 0 failed; 0 skipped; finished in 12.08s (12.08s CPU time)

Ran 15 test suites in 12.09s (12.32s CPU time): 160 tests passed, 0 failed, 0 skipped (160 total tests)
```
