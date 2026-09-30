# BioRigCoreV5 — audit findings

Target: `src/BioRigCoreV5.sol` (pristine copy: `src/BioRigCoreV5.sol.orig`).
Toolchain: Forge 1.8.3, solc 0.8.28, OpenZeppelin (upgradeable) v5.1.0.
Every test deploys the contract behind a real `ERC1967Proxy` and initializes it through the proxy (`test/Base.t.sol`).
The bare implementation is only called directly in tests that are about the implementation
(`test_implementation_*` and `test_upgrade_calledOnImplementationDirectly_reverts`).

Result: **142 tests, 142 passed, 0 failed, 0 skipped** (13 suites: 137 unit tests, 4 fuzz tests at 256 runs each,
and 1 invariant suite with 4 invariants at 128 runs × depth 100 = 12,800 handler calls, 0 reverts).

## Contract change (the full diff)

```diff
--- src/BioRigCoreV5.sol.orig
+++ src/BioRigCoreV5.sol
@@ -121,6 +121,7 @@
             address(this),
             tokenId
         );
+        if (treeWallet == address(0)) revert InvalidAddress();
 
         _trees[tokenId] = TreeStats({
             dbh: initialDBH,
```

That one line is the only change. It adds no storage, reuses the existing `InvalidAddress()` error, and leaves the
ABI and every event signature as they were. `forge inspect BioRigCoreV5 storageLayout` shows the same slots 0–7 before
and after the change.

---

## Defects

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

### L-1 — A codeless or reverting `uriGenerator` makes `tokenURI` revert for every token (H3) — **Low (availability)** — DOCUMENTED, not fixed

- **Tests:** `test/TokenURI.t.sol::test_H3_codelessGenerator_bricksTokenURI_untilReset` and
  `test_H3_revertingGenerator_bubblesRevert_untilReset`. Both are marked in-source as documenting behaviour (`FINDINGS L-1`).
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
| I-1 | **(H2)** The account returned by the registry is never checked to be bound to the token. A registry returning an unrelated address gets it installed as the TBA. With `ArbitraryRegistry`, two trees end up sharing one codeless "wallet". This is a trust assumption, not a flaw in the contract's own logic: the registry is set once in `initialize` with no setter, so a hostile registry needs `DEFAULT_ADMIN_ROLE` at init or `UPGRADER_ROLE`, and either can do worse. A real check would mean re-deriving the reference registry's CREATE2 formula on-chain (a feature, tied to one registry implementation), so it is not added. | `test_H2_arbitraryRegistry_addressIsInstalledUnchecked`, `test_H2_registryIsNotChangeableWithoutUpgrade` | documented |
| I-2 | **(H4, H6 reentrancy-events)** `_safeMint` calls `onERC721Received` on the planter **before** `emit TreeMinted`. `updateTreeGrowth` and `reportMortality` are not `nonReentrant`, so a planter contract that **also holds VERIFIER_ROLE** can call them from the callback. Measured effect: `GrowthUpdated` (or `TreeMortalityReported`) is logged before `TreeMinted` for the same token. State stays consistent (the tree record is written before `_safeMint`). A planter without the role gets `AccessControlUnauthorizedAccount`. This only affects indexers that assume event order. | `test_H4_verifierPlanter_growsDuringMintCallback_eventOrderOnly`, `test_H4_verifierPlanter_killsDuringMintCallback_consistent`, `test_H4_nonVerifierPlanter_callbackReverts` | documented |
| I-3 | `pause()` blocks mint, growth and mortality but **not** ERC-721 transfers or approvals (`_update` is not overridden). Admin setters and upgrades also work while paused. This may be intended; it should be written down. | `test_paused_transfersAndApprovalsStillWork`, `test_paused_adminConfigStillWorks`, `test_paused_upgradeStillWorks` | documented |
| I-4 | `initialize` accepts any `_chainId`. It is not checked against `block.chainid`. With the reference account implementation, a wrong value makes every TBA report a foreign chain. | `test_initialize_acceptsForeignChainId` | documented |
| I-5 | `bytes32(0)` is accepted as a spatial nullifier. | `test_zeroNullifier_isAccepted` | documented |
| I-6 | With no generator set, `tokenURI` falls back to `ERC721Upgradeable.tokenURI`. `_baseURI()` is not overridden, so the result is `""`. | `test_tokenURI_noGeneratorFallback_returnsEmpty`, `test_tokenURI_noGeneratorFromInit` | documented |
| I-7 | **(H6)** `uint64(block.timestamp)` (l.128, l.153) truncates only after 2^64 − 1 s, which is about 5.8×10^11 years. The test warps to `type(uint64).max` (stored exactly) and to `type(uint64).max + 1` (stored as `0`). No practical impact. | `test_H6_timestampCast_truncatesOnlyBeyondUint64` | informational |
| I-8 | **(H6 missing-zero-check)** `_uriGenerator` / `setURIGenerator` accept `address(0)`, and that is intended: zero selects the fallback path, which is tested. The other address inputs are already zero-checked (`initialize`, `setBufferPool`, `mintTree` planter), and after F-1 the registry return is too. `erc6551Implementation` has no code check, but the reference registry doesn't require one either. | `test_initialize_revertsOnZero*`, `test_setBufferPool_revertsOnZero`, `test_setURIGenerator_toZero` | informational |

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
- **H2 and H3 are not refuted.** Both behaviours are confirmed by tests. They are rated I-1 (a trust assumption) and L-1
  (admin-caused availability) instead of being treated as vulnerabilities.

## Could not verify

- **Interaction with the live canonical ERC-6551 registry and account implementation.** No fork test was run.
  `ERC6551RegistryMock` reproduces the reference registry's init code. Its constants were checked against
  `github.com/erc6551/reference/src/ERC6551Registry.sol`: header `3d60ad80600a3d3981f3363d3d373d3d3d363d73`, footer
  `5af43d82803e903d91602b57fd5bf3`, init code length 0xb7, CREATE2 with the raw salt. Whether the deployed registry
  behaves identically on a given chain is not established here.
- **Behaviour of a real ERC-6551 account** (e.g. `owner()` when `chainId` ≠ `block.chainid`, see I-4). The tests use
  `accountImpl` as an address only and never execute account code.
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

## Layout of `test/`

`Base.t.sol` (proxy fixture), `Lifecycle`, `AccessControl`, `Pausing`, `Nullifiers`, `Mint`, `TokenBoundAccount`,
`Growth`, `Mortality`, `TokenURI`, `ERC721Behavior`, `Upgrades`, `Reentrancy`, `Invariant` (`*.t.sol`).
Mocks are in `test/mocks/`: `Registries.sol` (conforming, zero, arbitrary and re-entrant registries), `Misc.sol`
(URI generators, rejecting/wrong-selector/accepting/verifier planters, a non-UUPS implementation) and `BioRigCoreV6.sol`.

## Evidence: final `forge test -vv`

```
Compiling 18 files with Solc 0.8.28
Solc 0.8.28 finished in 7.05s
Compiler run successful!

Ran 8 tests for test/Mortality.t.sol:MortalityTest
[PASS] test_mortality_deadTreeCannotGrow() (gas: 88538)
[PASS] test_mortality_isOneShot() (gas: 87967)
[PASS] test_mortality_marksDead_releasesNullifier_emits() (gas: 83802)
[PASS] test_mortality_onlyAffectsTarget() (gas: 347983)
[PASS] test_mortality_secondReportCannotReleaseReplantedNullifier() (gas: 364718)
[PASS] test_mortality_statsStillReadableAfterDeath() (gas: 87004)
[PASS] test_mortality_unknownToken_reverts() (gas: 43850)
[PASS] test_mortality_whilePaused_reverts() (gas: 96586)
Suite result: ok. 8 passed; 0 failed; 0 skipped; finished in 2.29ms (729.47µs CPU time)

Ran 25 tests for test/AccessControl.t.sol:AccessControlTest
[PASS] test_grantRole_byNonAdmin_reverts() (gas: 45358)
[PASS] test_grantRole_byVerifier_reverts() (gas: 47381)
[PASS] test_grantRole_verifier() (gas: 360209)
[PASS] test_renounceAdmin_locksOutAdminFunctions() (gas: 118495)
[PASS] test_renounceRole_revertsOnBadConfirmation() (gas: 50622)
[PASS] test_renounceRole_verifier() (gas: 50992)
[PASS] test_revokeRole_byNonAdmin_reverts() (gas: 47304)
[PASS] test_revokeRole_verifier_blocksMinting() (gas: 113113)
[PASS] test_roleConstants() (gas: 43984)
[PASS] test_setBufferPool_emitsAndStores() (gas: 62389)
[PASS] test_setBufferPool_revertsOnZero() (gas: 49487)
[PASS] test_setURIGenerator_emitsAndStores() (gas: 62487)
[PASS] test_setURIGenerator_toZero() (gas: 48807)
[PASS] test_unauth_mintTree() (gas: 52987)
[PASS] test_unauth_mintTree_adminIsNotVerifier() (gas: 52985)
[PASS] test_unauth_pause() (gas: 39885)
[PASS] test_unauth_pause_byVerifier() (gas: 39885)
[PASS] test_unauth_reportMortality() (gas: 315176)
[PASS] test_unauth_setBufferPool() (gas: 42388)
[PASS] test_unauth_setURIGenerator() (gas: 40042)
[PASS] test_unauth_setURIGenerator_byVerifier() (gas: 40087)
[PASS] test_unauth_unpause() (gas: 94859)
[PASS] test_unauth_updateTreeGrowth() (gas: 315768)
[PASS] test_unauth_updateTreeGrowth_byOwner() (gas: 313744)
[PASS] test_unauth_upgradeToAndCall() (gas: 44012)
Suite result: ok. 25 passed; 0 failed; 0 skipped; finished in 3.83ms (1.54ms CPU time)

Ran 11 tests for test/ERC721Behavior.t.sol:ERC721BehaviorTest
[PASS] test_approve_byNonOwner_reverts() (gas: 45163)
[PASS] test_approve_thenTransferByApproved() (gas: 183461)
[PASS] test_ownerOf_unknown_reverts() (gas: 16111)
[PASS] test_safeTransfer_toAcceptingReceiver() (gas: 319537)
[PASS] test_safeTransfer_toRejectingReceiver_reverts() (gas: 191103)
[PASS] test_setApprovalForAll_operatorTransfers() (gas: 164168)
[PASS] test_supportsInterface() (gas: 64065)
[PASS] test_transfer_byStranger_reverts() (gas: 50189)
[PASS] test_transfer_deadTree_isAllowed() (gas: 161830)
[PASS] test_transfer_liveTree_keepsStatsAndTba() (gas: 155348)
[PASS] test_transfer_toZero_reverts() (gas: 40442)
Suite result: ok. 11 passed; 0 failed; 0 skipped; finished in 3.70ms (1.22ms CPU time)

Ran 9 tests for test/Reentrancy.t.sol:ReentrancyTest
[PASS] test_H4_nonVerifierPlanter_callbackReverts() (gas: 548873)
[PASS] test_H4_verifierPlanter_growsDuringMintCallback_eventOrderOnly() (gas: 648754)
[PASS] test_H4_verifierPlanter_killsDuringMintCallback_consistent() (gas: 607316)
[PASS] test_benignModeStillMints() (gas: 281657)
[PASS] test_reenterGrowth_withRole_seesNoTree() (gas: 293720)
[PASS] test_reenterGrowth_withoutRole_reverts() (gas: 232449)
[PASS] test_reenterMint_withVerifierRole_blockedByGuard() (gas: 288800)
[PASS] test_reenterMint_withoutRole_blockedByGuard() (gas: 227036)
[PASS] test_reenterMortality_withRole_seesNoTree() (gas: 293705)
Suite result: ok. 9 passed; 0 failed; 0 skipped; finished in 4.40ms (2.22ms CPU time)

Ran 15 tests for test/Growth.t.sol:GrowthTest
[PASS] testFuzz_growth_monotonic(uint96,uint96) (runs: 256, μ: 83134, ~: 88114)
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
Suite result: ok. 15 passed; 0 failed; 0 skipped; finished in 17.88ms (16.60ms CPU time)

Ran 12 tests for test/Pausing.t.sol:PausingTest
[PASS] test_pause_twice_reverts() (gas: 41712)
[PASS] test_paused_adminConfigStillWorks() (gas: 167876)
[PASS] test_paused_blocksGrowth() (gas: 42109)
[PASS] test_paused_blocksMint() (gas: 57009)
[PASS] test_paused_blocksMortality() (gas: 49590)
[PASS] test_paused_flag() (gas: 12632)
[PASS] test_paused_mintCheckedBeforeRole() (gas: 48190)
[PASS] test_paused_readPathsStillWork() (gas: 125820)
[PASS] test_paused_transfersAndApprovalsStillWork() (gas: 139947)
[PASS] test_paused_upgradeStillWorks() (gas: 56760)
[PASS] test_unpause_restores() (gas: 409826)
[PASS] test_unpause_whenNotPaused_reverts() (gas: 72409)
Suite result: ok. 12 passed; 0 failed; 0 skipped; finished in 2.12ms (875.56µs CPU time)

Ran 13 tests for test/Lifecycle.t.sol:LifecycleTest
[PASS] test_implementation_cannotBeInitialized() (gas: 42658)
[PASS] test_implementation_hasNoAdminAndIsUnusable() (gas: 82636)
[PASS] test_implementation_initializersDisabled() (gas: 7852)
[PASS] test_initialize_acceptsForeignChainId() (gas: 440795)
[PASS] test_initialize_allowsZeroUriGenerator() (gas: 441011)
[PASS] test_initialize_revertsOnDoubleInit() (gas: 49968)
[PASS] test_initialize_revertsOnDoubleInit_evenByAdmin() (gas: 50202)
[PASS] test_initialize_revertsOnZeroAccountImplementation() (gas: 166455)
[PASS] test_initialize_revertsOnZeroAdmin() (gas: 166321)
[PASS] test_initialize_revertsOnZeroBufferPool() (gas: 166466)
[PASS] test_initialize_revertsOnZeroRegistry() (gas: 166394)
[PASS] test_initialize_setsState() (gas: 170430)
[PASS] test_initialize_zeroAdminCheckedBeforeOtherArgs() (gas: 159321)
Suite result: ok. 13 passed; 0 failed; 0 skipped; finished in 1.80ms (648.76µs CPU time)

Ran 8 tests for test/Nullifiers.t.sol:NullifiersTest
[PASS] testFuzz_nullifierUniqueness(bytes32,bytes32) (runs: 256, μ: 527672, ~: 527880)
[PASS] test_killingReplantedTree_releasesAgain() (gas: 619324)
[PASS] test_mint_activatesNullifier() (gas: 311118)
[PASS] test_mint_duplicateNullifier_doesNotConsumeTokenId() (gas: 589179)
[PASS] test_mint_duplicateNullifier_reverts() (gas: 321350)
[PASS] test_mortality_releasesNullifier_andAllowsReplant() (gas: 686339)
[PASS] test_replantedTree_distinctTba() (gas: 601392)
[PASS] test_zeroNullifier_isAccepted() (gas: 283870)
Suite result: ok. 8 passed; 0 failed; 0 skipped; finished in 40.00ms (38.87ms CPU time)

Ran 8 tests for test/TokenURI.t.sol:TokenURITest
[PASS] test_H3_codelessGenerator_bricksTokenURI_untilReset() (gas: 528408)
[PASS] test_H3_revertingGenerator_bubblesRevert_untilReset() (gas: 289047)
[PASS] test_tokenURI_generatorPath() (gas: 183254)
[PASS] test_tokenURI_noGeneratorFallback_returnsEmpty() (gas: 63738)
[PASS] test_tokenURI_noGeneratorFromInit() (gas: 786521)
[PASS] test_tokenURI_passesStatsToGenerator() (gas: 34094)
[PASS] test_tokenURI_unknownToken_reverts() (gas: 21946)
[PASS] test_tokenURI_unknownToken_reverts_noGenerator() (gas: 55565)
Suite result: ok. 8 passed; 0 failed; 0 skipped; finished in 2.21ms (1.01ms CPU time)

Ran 12 tests for test/Upgrades.t.sol:UpgradesTest
[PASS] test_H5_parentsUseNamespacedStorage() (gas: 285632)
[PASS] test_proxy_pointsAtImplementation() (gas: 11063)
[PASS] test_treeStatsPacking() (gas: 299543)
[PASS] test_upgrade_adminWithoutUpgraderRole_reverts() (gas: 2806674)
[PASS] test_upgrade_byNonUpgrader_reverts() (gas: 2773645)
[PASS] test_upgrade_byUpgrader() (gas: 2787505)
[PASS] test_upgrade_byVerifier_reverts() (gas: 2770881)
[PASS] test_upgrade_calledOnImplementationDirectly_reverts() (gas: 2760704)
[PASS] test_upgrade_grantedUpgrader() (gas: 2838088)
[PASS] test_upgrade_toNonUUPS_reverts() (gas: 154760)
[PASS] test_upgrade_v6ReadsV5State_layoutPreserved() (gas: 4550779)
[PASS] test_upgrade_v6ReinitializerRunsOnce() (gas: 2891349)
Suite result: ok. 12 passed; 0 failed; 0 skipped; finished in 3.97ms (2.65ms CPU time)

Ran 12 tests for test/Mint.t.sol:MintTest
[PASS] testFuzz_mint_storesArbitraryStats(address,bytes32,uint96,uint96) (runs: 256, μ: 306478, ~: 306571)
[PASS] test_mint_emitsTreeMintedAndTransfer() (gas: 296395)
[PASS] test_mint_firstIdIsOne_andIncrements() (gas: 825082)
[PASS] test_mint_maxInitialStats() (gas: 310362)
[PASS] test_mint_storesStats() (gas: 305765)
[PASS] test_mint_toAcceptingContract() (gas: 524343)
[PASS] test_mint_toRejectingContract_revertsAtomically() (gas: 694734)
[PASS] test_mint_toWrongSelectorContract_reverts() (gas: 436648)
[PASS] test_mint_whilePaused_reverts() (gas: 103138)
[PASS] test_mint_withoutVerifierRole_reverts() (gas: 50933)
[PASS] test_mint_zeroInitialStats() (gas: 382351)
[PASS] test_mint_zeroPlanter_reverts() (gas: 56849)
Suite result: ok. 12 passed; 0 failed; 0 skipped; finished in 29.59ms (29.89ms CPU time)

Ran 8 tests for test/TokenBoundAccount.t.sol:TokenBoundAccountTest
[PASS] testFuzz_tba_matchesRecomputation(address,bytes32) (runs: 256, μ: 303793, ~: 303905)
[PASS] test_H1_zeroRegistry_mintReverts() (gas: 758113)
[PASS] test_H2_arbitraryRegistry_addressIsInstalledUnchecked() (gas: 1115813)
[PASS] test_H2_registryIsNotChangeableWithoutUpgrade() (gas: 14733)
[PASS] test_createAccount_calledWithExpectedArgs() (gas: 283696)
[PASS] test_salt_isDeterministic() (gas: 961)
[PASS] test_tba_distinctPerToken() (gas: 559711)
[PASS] test_tba_matchesIndependentRecomputation() (gas: 336254)
Suite result: ok. 8 passed; 0 failed; 0 skipped; finished in 51.71ms (51.65ms CPU time)

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
| TreeHandler | grow        | 2221  | 0       | 0        |
|-------------+-------------+-------+---------+----------|
| TreeHandler | kill        | 2104  | 0       | 0        |
|-------------+-------------+-------+---------+----------|
| TreeHandler | mint        | 2155  | 0       | 0        |
|-------------+-------------+-------+---------+----------|
| TreeHandler | shrink      | 2062  | 0       | 0        |
|-------------+-------------+-------+---------+----------|
| TreeHandler | togglePause | 2129  | 0       | 0        |
|-------------+-------------+-------+---------+----------|
| TreeHandler | transfer    | 2129  | 0       | 0        |
╰-------------+-------------+-------+---------+----------╯

Suite result: ok. 1 passed; 0 failed; 0 skipped; finished in 12.36s (12.36s CPU time)

Ran 13 test suites in 12.37s (12.52s CPU time): 142 tests passed, 0 failed, 0 skipped (142 total tests)
```
