# I-6 evidence: settable base URI for the tokenURI fallback

All commands run from the repo root. Nothing here was committed (deliberate: `git diff` shows the change).

| File | Command |
| --- | --- |
| `forge-test.txt` | `forge test` before the authorized test edit → **174 passed, 1 failed, 0 skipped (175)** |
| `forge-test.after.txt` | `forge test` after it → **175 passed, 0 failed, 0 skipped (175)**, exit 0 |
| `prechange-orig.txt` | `evidence/i6/run_prechange.sh evidence/i6/orig-stubbed.sol` → **1 passed, 14 failed (15)** |
| `prechange-prei6.txt` | `evidence/i6/run_prechange.sh evidence/i6/prei6-stubbed.sol` → **1 passed, 14 failed (15)** |
| `storageLayout.{original,prei6,after}.{json,txt,normalized.json}` | `evidence/i6/inspect_layout.sh <src> evidence/i6/storageLayout.<name>` (sources: `src/BioRigCoreV5.sol.orig`, `evidence/i6/prei6.sol`, `src/BioRigCoreV5.sol`) |
| `storage-layout-comparison.txt` | `python3 evidence/i6/compare_layout.py` (exit 0 = slots 0-7 identical, exactly one appended `_baseTokenURI` at slot 8) plus the raw-JSON field diff |
| `upgrades-test.{before,after}.sol`, `upgrades-test.diff` | the edited test function, verbatim before/after |

`make_variants.py` builds the pre-change sources. `orig-stubbed.sol` = verbatim `.orig` + declarations only
(IERC6551Account, InvalidNullifier, InvalidTba, as in the previous round) + empty-bodied `setBaseURI`/`baseURI`
stubs so the suite compiles. `prei6.sol` = the hardened contract before this change; it is byte-identical to
`patch src/BioRigCoreV5.sol.orig HARDENING.diff`. `prei6-stubbed.sol` = that + the same two stubs.
The only new test passing against either is `test_I6_unsetBaseURI_fallbackIsEmpty`, which is the regression
pin and passes against both by design.

## The one failing test, and the authorized edit to it

`test/Upgrades.t.sol::test_upgrade_v6ReadsV5State_layoutPreserved` failed with `assertion failed: 0 != 12648430`.
Its mock `test/mocks/BioRigCoreV6.sol` inherits BioRigCoreV5 and appends `uint256 v6Marker`; the test asserted
`vm.load(core, 8) == 0xC0FFEE` ("appended var is in slot 8"). That `8` is bookkeeping for where the test-only mock's
appended variable lands, correct only while V5 occupied slots 0-7. V5 now owns slot 8 (`_baseTokenURI`), so solc
places `v6Marker` at slot 9 and slot 8 holds the base URI. Not a collision and not a weakened claim: any variable
appended to V5 shifts the next successor's first appended variable by one, and appending at slot 8 is the approved
design (plan Option A). The test's real claims (V5's slots unmoved, V5 state readable through the successor) held.

Edit (operator-authorized, this one function only; every other assertion in every test file is unchanged):
- `setBaseURI("ipfs://bafyI6layout/")` on the proxy before the snapshot (short string, so it is stored inline in
  slot 8), and an assertion that slot 8 is non-zero at snapshot time.
- Snapshot `bytes32[8]`/`i < 8` → `bytes32[9]`/`i < 9`; post-upgrade loop asserts all 9 slots unchanged.
- Marker slot `8` → `9`.
- Non-collision: for every V5 slot 0-8, `0xC0FFEE` was not there before the upgrade (so the check can't pass or fail
  by coincidence) and is not there after `initializeV6`. It does not depend on the slot count of the mock.
- After the upgrade: `v6.baseURI()` equals the value set; after clearing the generator, `tokenURI(a)` through the
  V6 implementation equals `base + vm.toString(a)` = `"ipfs://bafyI6layout/1"`.
- `test/mocks/BioRigCoreV6.sol`: doc comment only, "lands in slot 8" → slot 9 and why. No code change.

Mutation checks (temporary, reverted; not in the tree): with the mock also doing `sstore(5, marker)`, the test fails
`V5 slot moved`; with that mutation and the slot-equality assertion disabled, it fails
`V6 marker collided with a V5 slot`, so the non-collision assertion catches a real collision on its own.

Previously-green tests (name comparison, `evidence/i6/forge-test.txt` → `forge-test.after.txt`): none lost; the only
name that changed state is `test_upgrade_v6ReadsV5State_layoutPreserved` (FAIL → PASS). Also none lost against the
previous round's `evidence/forge-test.txt`.
