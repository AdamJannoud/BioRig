// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

import {Vm} from "forge-std/Vm.sol";
import {ReentrancyGuardUpgradeable} from "@openzeppelin/contracts-upgradeable/utils/ReentrancyGuardUpgradeable.sol";
import {BaseTest} from "./Base.t.sol";
import {BioRigCoreV5} from "../src/BioRigCoreV5.sol";
import {ReentrantRegistry} from "./mocks/Registries.sol";
import {VerifierPlanter} from "./mocks/Misc.sol";

contract ReentrancyTest is BaseTest {
    ReentrantRegistry internal evil;
    BioRigCoreV5 internal c;

    function setUp() public override {
        super.setUp();
        evil = new ReentrantRegistry();
        c = _deployWithRegistry(address(evil));
    }

    function _assertNothingPersisted() internal {
        assertFalse(c.isNullifierActive(N1));
        assertFalse(c.isNullifierActive(keccak256("reentrant")));
        assertEq(c.balanceOf(planter), 0);
        assertEq(c.balanceOf(address(0xBEEF)), 0);
        assertEq(uint256(vm.load(address(c), bytes32(0))), 1, "token id counter rolled back");
        vm.expectRevert(BioRigCoreV5.InvalidTree.selector);
        c.getTreeStats(1);
    }

    function test_reenterMint_withoutRole_blockedByGuard() public {
        evil.configure(address(c), ReentrantRegistry.Mode.Mint);
        vm.prank(verifier);
        vm.expectRevert(ReentrancyGuardUpgradeable.ReentrancyGuardReentrantCall.selector);
        c.mintTree(planter, N1, 1, 1);
        _assertNothingPersisted();
    }

    /// Even if the hostile registry is also a verifier, nonReentrant stops the nested mint.
    function test_reenterMint_withVerifierRole_blockedByGuard() public {
        vm.prank(admin);
        c.grantRole(VERIFIER_ROLE, address(evil));
        evil.configure(address(c), ReentrantRegistry.Mode.Mint);
        vm.prank(verifier);
        vm.expectRevert(ReentrancyGuardUpgradeable.ReentrancyGuardReentrantCall.selector);
        c.mintTree(planter, N1, 1, 1);
        _assertNothingPersisted();
    }

    function test_reenterGrowth_withoutRole_reverts() public {
        evil.configure(address(c), ReentrantRegistry.Mode.Growth);
        vm.prank(verifier);
        vm.expectRevert(_unauthorized(address(evil), VERIFIER_ROLE));
        c.mintTree(planter, N1, 1, 1);
        _assertNothingPersisted();
    }

    /// With the role, the nested growth call sees an unwritten tree (tbaAddress == 0) and reverts.
    function test_reenterGrowth_withRole_seesNoTree() public {
        vm.prank(admin);
        c.grantRole(VERIFIER_ROLE, address(evil));
        evil.configure(address(c), ReentrantRegistry.Mode.Growth);
        vm.prank(verifier);
        vm.expectRevert(BioRigCoreV5.InvalidTree.selector);
        c.mintTree(planter, N1, 1, 1);
        _assertNothingPersisted();
    }

    function test_reenterMortality_withRole_seesNoTree() public {
        vm.prank(admin);
        c.grantRole(VERIFIER_ROLE, address(evil));
        evil.configure(address(c), ReentrantRegistry.Mode.Mortality);
        vm.prank(verifier);
        vm.expectRevert(BioRigCoreV5.InvalidTree.selector);
        c.mintTree(planter, N1, 1, 1);
        _assertNothingPersisted();
    }

    function test_benignModeStillMints() public {
        evil.configure(address(c), ReentrantRegistry.Mode.None);
        vm.prank(verifier);
        assertEq(c.mintTree(planter, N1, 1, 1), 1);
        assertEq(evil.calls(), 1);
    }

    // ---- H4 / H6 (reentrancy-events): callback from _safeMint into the unguarded paths ----

    /// A planter that is ALSO a verifier can call updateTreeGrowth from onERC721Received,
    /// because growth is not nonReentrant. Only effect: GrowthUpdated is logged before TreeMinted.
    /// Requires a trusted role; no state is corrupted. (FINDINGS I-2, H4)
    function test_H4_verifierPlanter_growsDuringMintCallback_eventOrderOnly() public {
        VerifierPlanter vp = new VerifierPlanter(address(core), false);
        vm.prank(admin);
        core.grantRole(VERIFIER_ROLE, address(vp));

        vm.recordLogs();
        vm.prank(verifier);
        uint256 id = core.mintTree(address(vp), N1, 10, 20);
        Vm.Log[] memory logs = vm.getRecordedLogs();

        int256 growthIdx = -1;
        int256 mintedIdx = -1;
        for (uint256 i; i < logs.length; ++i) {
            if (logs[i].topics[0] == GrowthUpdated.selector) growthIdx = int256(i);
            if (logs[i].topics[0] == TreeMinted.selector) mintedIdx = int256(i);
        }
        assertTrue(growthIdx >= 0 && mintedIdx >= 0);
        assertLt(growthIdx, mintedIdx, "GrowthUpdated precedes TreeMinted");

        BioRigCoreV5.TreeStats memory s = core.getTreeStats(id);
        assertEq(s.dbh, 500);
        assertEq(s.biomass, 600);
        assertTrue(s.isAlive);
        assertTrue(core.isNullifierActive(N1));
        assertEq(core.ownerOf(id), address(vp));
    }

    /// Same for mortality: a verifier-planter can kill the tree mid-mint. State stays consistent
    /// (dead + nullifier released), TreeMortalityReported precedes TreeMinted.
    function test_H4_verifierPlanter_killsDuringMintCallback_consistent() public {
        VerifierPlanter vp = new VerifierPlanter(address(core), true);
        vm.prank(admin);
        core.grantRole(VERIFIER_ROLE, address(vp));
        vm.prank(verifier);
        uint256 id = core.mintTree(address(vp), N1, 10, 20);
        assertFalse(core.getTreeStats(id).isAlive);
        assertFalse(core.isNullifierActive(N1));
    }

    /// Without VERIFIER_ROLE the callback cannot touch tree state at all.
    function test_H4_nonVerifierPlanter_callbackReverts() public {
        VerifierPlanter vp = new VerifierPlanter(address(core), false);
        vm.prank(verifier);
        vm.expectRevert(_unauthorized(address(vp), VERIFIER_ROLE));
        core.mintTree(address(vp), N1, 10, 20);
        assertFalse(core.isNullifierActive(N1));
    }
}
