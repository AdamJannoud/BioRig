// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

import {PausableUpgradeable} from "@openzeppelin/contracts-upgradeable/utils/PausableUpgradeable.sol";
import {BaseTest} from "./Base.t.sol";
import {BioRigCoreV5} from "../src/BioRigCoreV5.sol";

contract PausingTest is BaseTest {
    uint256 internal id;

    function setUp() public override {
        super.setUp();
        id = _mint(planter, N1, 10, 20);
        vm.expectEmit(false, false, false, true, address(core));
        emit PausableUpgradeable.Paused(admin);
        vm.prank(admin);
        core.pause();
    }

    function test_paused_flag() public view {
        assertTrue(core.paused());
    }

    function test_paused_blocksMint() public {
        vm.prank(verifier);
        vm.expectRevert(_enforcedPause());
        core.mintTree(planter, N2, 1, 1);
        assertFalse(core.isNullifierActive(N2));
    }

    function test_paused_mintCheckedBeforeRole() public {
        // modifier order is nonReentrant, whenNotPaused, onlyRole: a stranger sees EnforcedPause
        vm.prank(stranger);
        vm.expectRevert(_enforcedPause());
        core.mintTree(planter, N2, 1, 1);
    }

    function test_paused_blocksGrowth() public {
        vm.prank(verifier);
        vm.expectRevert(_enforcedPause());
        core.updateTreeGrowth(id, 11, 21);
    }

    function test_paused_blocksMortality() public {
        vm.prank(verifier);
        vm.expectRevert(_enforcedPause());
        core.reportMortality(id);
        assertTrue(core.isNullifierActive(N1));
    }

    function test_pause_twice_reverts() public {
        vm.prank(admin);
        vm.expectRevert(_enforcedPause());
        core.pause();
    }

    function test_unpause_whenNotPaused_reverts() public {
        vm.startPrank(admin);
        core.unpause();
        vm.expectRevert(PausableUpgradeable.ExpectedPause.selector);
        core.unpause();
        vm.stopPrank();
    }

    function test_unpause_restores() public {
        vm.expectEmit(false, false, false, true, address(core));
        emit PausableUpgradeable.Unpaused(admin);
        vm.prank(admin);
        core.unpause();
        assertFalse(core.paused());

        vm.startPrank(verifier);
        assertEq(core.mintTree(planter, N2, 1, 1), 2);
        core.updateTreeGrowth(id, 11, 21);
        core.reportMortality(id);
        vm.stopPrank();
        assertFalse(core.getTreeStats(id).isAlive);
    }

    function test_paused_readPathsStillWork() public view {
        BioRigCoreV5.TreeStats memory s = core.getTreeStats(id);
        assertEq(s.dbh, 10);
        assertEq(core.tokenURI(id), "tree:1:10:20:alive");
        assertTrue(core.isNullifierActive(N1));
        assertEq(core.ownerOf(id), planter);
        assertEq(core.balanceOf(planter), 1);
        assertTrue(core.hasRole(VERIFIER_ROLE, verifier));
        assertEq(core.uriGenerator(), address(generator));
    }

    /// Informational (FINDINGS I-3): pause does not cover ERC721 transfers; _update is not overridden.
    function test_paused_transfersAndApprovalsStillWork() public {
        vm.startPrank(planter);
        core.approve(alice, id);
        core.transferFrom(planter, bob, id);
        vm.stopPrank();
        assertEq(core.ownerOf(id), bob);
    }

    function test_paused_adminConfigStillWorks() public {
        vm.startPrank(admin);
        core.setBufferPool(alice);
        core.setURIGenerator(address(0));
        core.grantRole(VERIFIER_ROLE, bob);
        vm.stopPrank();
        assertEq(core.bufferPool(), alice);
        assertTrue(core.hasRole(VERIFIER_ROLE, bob));
    }

    function test_paused_upgradeStillWorks() public {
        BioRigCoreV5 newImpl = new BioRigCoreV5();
        vm.prank(admin);
        core.upgradeToAndCall(address(newImpl), "");
        assertTrue(core.paused(), "pause state survives upgrade");
    }
}
