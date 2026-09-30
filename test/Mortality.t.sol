// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

import {BaseTest} from "./Base.t.sol";
import {BioRigCoreV5} from "../src/BioRigCoreV5.sol";

contract MortalityTest is BaseTest {
    uint256 internal id;
    address internal tba;

    function setUp() public override {
        super.setUp();
        vm.warp(1_700_000_000);
        id = _mint(planter, N1, 100, 200);
        tba = core.getTreeStats(id).tbaAddress;
    }

    function _kill(uint256 tokenId) internal {
        vm.prank(verifier);
        core.reportMortality(tokenId);
    }

    function test_mortality_marksDead_releasesNullifier_emits() public {
        vm.expectEmit(true, false, false, true, address(core));
        emit TreeMortalityReported(id, N1, tba);
        _kill(id);
        assertFalse(core.getTreeStats(id).isAlive);
        assertFalse(core.isNullifierActive(N1));
    }

    function test_mortality_isOneShot() public {
        _kill(id);
        vm.prank(verifier);
        vm.expectRevert(BioRigCoreV5.TreeIsDead.selector);
        core.reportMortality(id);
    }

    /// Second report must not touch a replanted tree's nullifier.
    function test_mortality_secondReportCannotReleaseReplantedNullifier() public {
        _kill(id);
        _mint(alice, N1);
        vm.prank(verifier);
        vm.expectRevert(BioRigCoreV5.TreeIsDead.selector);
        core.reportMortality(id);
        assertTrue(core.isNullifierActive(N1));
    }

    function test_mortality_statsStillReadableAfterDeath() public {
        vm.warp(block.timestamp + 10);
        _kill(id);
        BioRigCoreV5.TreeStats memory s = core.getTreeStats(id);
        assertEq(s.dbh, 100);
        assertEq(s.biomass, 200);
        assertEq(s.lastUpdated, 1_700_000_000, "mortality does not touch lastUpdated");
        assertEq(s.tbaAddress, tba);
        assertFalse(s.isAlive);
        assertEq(s.spatialNullifier, N1);
        assertEq(core.ownerOf(id), planter, "dead tree NFT is not burned");
    }

    function test_mortality_deadTreeCannotGrow() public {
        _kill(id);
        vm.prank(verifier);
        vm.expectRevert(BioRigCoreV5.TreeIsDead.selector);
        core.updateTreeGrowth(id, 200, 300);
    }

    function test_mortality_unknownToken_reverts() public {
        vm.prank(verifier);
        vm.expectRevert(BioRigCoreV5.InvalidTree.selector);
        core.reportMortality(42);
    }

    function test_mortality_whilePaused_reverts() public {
        vm.prank(admin);
        core.pause();
        vm.prank(verifier);
        vm.expectRevert(_enforcedPause());
        core.reportMortality(id);
    }

    function test_mortality_onlyAffectsTarget() public {
        uint256 other = _mint(alice, N2);
        _kill(id);
        assertTrue(core.getTreeStats(other).isAlive);
        assertTrue(core.isNullifierActive(N2));
    }
}
