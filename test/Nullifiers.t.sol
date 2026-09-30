// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

import {BaseTest} from "./Base.t.sol";
import {BioRigCoreV5} from "../src/BioRigCoreV5.sol";

contract NullifiersTest is BaseTest {
    function test_mint_activatesNullifier() public {
        assertFalse(core.isNullifierActive(N1));
        _mint(planter, N1);
        assertTrue(core.isNullifierActive(N1));
        assertFalse(core.isNullifierActive(N2));
    }

    function test_mint_duplicateNullifier_reverts() public {
        _mint(planter, N1);
        vm.prank(verifier);
        vm.expectRevert(BioRigCoreV5.NullifierInUse.selector);
        core.mintTree(alice, N1, 1, 1);
    }

    function test_mint_duplicateNullifier_doesNotConsumeTokenId() public {
        _mint(planter, N1);
        vm.prank(verifier);
        vm.expectRevert(BioRigCoreV5.NullifierInUse.selector);
        core.mintTree(alice, N1, 1, 1);
        assertEq(_mint(alice, N2), 2);
    }

    function test_mortality_releasesNullifier_andAllowsReplant() public {
        uint256 id1 = _mint(planter, N1);
        vm.prank(verifier);
        core.reportMortality(id1);
        assertFalse(core.isNullifierActive(N1));

        uint256 id2 = _mint(alice, N1);
        assertEq(id2, 2);
        assertTrue(core.isNullifierActive(N1));
        // the dead tree still records the same nullifier; only one of the two is alive
        assertEq(core.getTreeStats(id1).spatialNullifier, N1);
        assertEq(core.getTreeStats(id2).spatialNullifier, N1);
        assertFalse(core.getTreeStats(id1).isAlive);
        assertTrue(core.getTreeStats(id2).isAlive);
    }

    function test_replantedTree_distinctTba() public {
        uint256 id1 = _mint(planter, N1);
        vm.prank(verifier);
        core.reportMortality(id1);
        uint256 id2 = _mint(planter, N1);
        assertTrue(core.getTreeStats(id1).tbaAddress != core.getTreeStats(id2).tbaAddress);
    }

    function test_killingReplantedTree_releasesAgain() public {
        uint256 id1 = _mint(planter, N1);
        vm.prank(verifier);
        core.reportMortality(id1);
        uint256 id2 = _mint(planter, N1);
        vm.prank(verifier);
        core.reportMortality(id2);
        assertFalse(core.isNullifierActive(N1));
    }

    /// Informational (FINDINGS I-5): bytes32(0) is accepted as a nullifier.
    function test_zeroNullifier_isAccepted() public {
        uint256 id = _mint(planter, bytes32(0));
        assertTrue(core.isNullifierActive(bytes32(0)));
        assertEq(core.getTreeStats(id).spatialNullifier, bytes32(0));
    }

    function testFuzz_nullifierUniqueness(bytes32 a, bytes32 b) public {
        _mint(planter, a);
        vm.prank(verifier);
        if (a == b) {
            vm.expectRevert(BioRigCoreV5.NullifierInUse.selector);
            core.mintTree(planter, b, 1, 1);
        } else {
            assertEq(core.mintTree(planter, b, 1, 1), 2);
        }
    }
}
