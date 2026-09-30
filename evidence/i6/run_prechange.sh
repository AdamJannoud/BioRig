#!/usr/bin/env bash
# Runs the new I-6 tests (test_I6_*) against a pre-change contract, then restores the real one.
# usage: evidence/i6/run_prechange.sh evidence/i6/orig-stubbed.sol   (or prei6-stubbed.sol)
set -u
cd "$(dirname "$0")/../.."
variant="$1"
cp src/BioRigCoreV5.sol evidence/i6/.BioRigCoreV5.sol.keep
restore() { cp evidence/i6/.BioRigCoreV5.sol.keep src/BioRigCoreV5.sol && rm evidence/i6/.BioRigCoreV5.sol.keep; }
trap restore EXIT
cp "$variant" src/BioRigCoreV5.sol
forge test --match-test 'test_I6_' 2>&1
