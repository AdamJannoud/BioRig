// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

import {IAccessControl} from "@openzeppelin/contracts/access/IAccessControl.sol";
import {BaseTest} from "./Base.t.sol";
import {BioRigCoreV5} from "../src/BioRigCoreV5.sol";

contract AccessControlTest is BaseTest {
    function test_roleConstants() public view {
        assertEq(VERIFIER_ROLE, keccak256("VERIFIER_ROLE"));
        assertEq(UPGRADER_ROLE, keccak256("UPGRADER_ROLE"));
        assertEq(core.DEFAULT_ADMIN_ROLE(), bytes32(0));
        assertEq(core.getRoleAdmin(VERIFIER_ROLE), DEFAULT_ADMIN_ROLE);
        assertEq(core.getRoleAdmin(UPGRADER_ROLE), DEFAULT_ADMIN_ROLE);
    }

    function test_grantRole_verifier() public {
        vm.expectEmit(true, true, true, true, address(core));
        emit IAccessControl.RoleGranted(VERIFIER_ROLE, alice, admin);
        vm.prank(admin);
        core.grantRole(VERIFIER_ROLE, alice);
        assertTrue(core.hasRole(VERIFIER_ROLE, alice));
        vm.prank(alice);
        assertEq(core.mintTree(planter, N1, 1, 1), 1);
    }

    function test_revokeRole_verifier_blocksMinting() public {
        vm.expectEmit(true, true, true, true, address(core));
        emit IAccessControl.RoleRevoked(VERIFIER_ROLE, verifier, admin);
        vm.prank(admin);
        core.revokeRole(VERIFIER_ROLE, verifier);
        assertFalse(core.hasRole(VERIFIER_ROLE, verifier));
        vm.prank(verifier);
        vm.expectRevert(_unauthorized(verifier, VERIFIER_ROLE));
        core.mintTree(planter, N1, 1, 1);
    }

    function test_renounceRole_verifier() public {
        vm.prank(verifier);
        core.renounceRole(VERIFIER_ROLE, verifier);
        assertFalse(core.hasRole(VERIFIER_ROLE, verifier));
    }

    function test_renounceRole_revertsOnBadConfirmation() public {
        vm.prank(stranger);
        vm.expectRevert(IAccessControl.AccessControlBadConfirmation.selector);
        core.renounceRole(VERIFIER_ROLE, verifier);
        assertTrue(core.hasRole(VERIFIER_ROLE, verifier));
    }

    function test_renounceAdmin_locksOutAdminFunctions() public {
        vm.startPrank(admin);
        core.renounceRole(DEFAULT_ADMIN_ROLE, admin);
        vm.expectRevert(_unauthorized(admin, DEFAULT_ADMIN_ROLE));
        core.pause();
        vm.expectRevert(_unauthorized(admin, DEFAULT_ADMIN_ROLE));
        core.grantRole(VERIFIER_ROLE, alice);
        vm.stopPrank();
        // UPGRADER_ROLE is independent and survives
        assertTrue(core.hasRole(UPGRADER_ROLE, admin));
    }

    function test_grantRole_byNonAdmin_reverts() public {
        vm.prank(stranger);
        vm.expectRevert(_unauthorized(stranger, DEFAULT_ADMIN_ROLE));
        core.grantRole(VERIFIER_ROLE, stranger);
    }

    function test_grantRole_byVerifier_reverts() public {
        vm.prank(verifier);
        vm.expectRevert(_unauthorized(verifier, DEFAULT_ADMIN_ROLE));
        core.grantRole(VERIFIER_ROLE, stranger);
    }

    function test_revokeRole_byNonAdmin_reverts() public {
        vm.prank(stranger);
        vm.expectRevert(_unauthorized(stranger, DEFAULT_ADMIN_ROLE));
        core.revokeRole(VERIFIER_ROLE, verifier);
    }

    // ---- every onlyRole-gated entry point, called by an unauthorized account ----

    function test_unauth_mintTree() public {
        vm.prank(stranger);
        vm.expectRevert(_unauthorized(stranger, VERIFIER_ROLE));
        core.mintTree(planter, N1, 1, 1);
    }

    function test_unauth_mintTree_adminIsNotVerifier() public {
        vm.prank(admin);
        vm.expectRevert(_unauthorized(admin, VERIFIER_ROLE));
        core.mintTree(planter, N1, 1, 1);
    }

    function test_unauth_updateTreeGrowth() public {
        uint256 id = _mint(planter, N1);
        vm.prank(stranger);
        vm.expectRevert(_unauthorized(stranger, VERIFIER_ROLE));
        core.updateTreeGrowth(id, 100, 100);
    }

    function test_unauth_updateTreeGrowth_byOwner() public {
        uint256 id = _mint(planter, N1);
        vm.prank(planter);
        vm.expectRevert(_unauthorized(planter, VERIFIER_ROLE));
        core.updateTreeGrowth(id, 100, 100);
    }

    function test_unauth_reportMortality() public {
        uint256 id = _mint(planter, N1);
        vm.prank(stranger);
        vm.expectRevert(_unauthorized(stranger, VERIFIER_ROLE));
        core.reportMortality(id);
    }

    function test_unauth_setURIGenerator() public {
        vm.prank(stranger);
        vm.expectRevert(_unauthorized(stranger, DEFAULT_ADMIN_ROLE));
        core.setURIGenerator(address(0));
    }

    function test_unauth_setURIGenerator_byVerifier() public {
        vm.prank(verifier);
        vm.expectRevert(_unauthorized(verifier, DEFAULT_ADMIN_ROLE));
        core.setURIGenerator(address(0));
    }

    function test_unauth_setBufferPool() public {
        vm.prank(stranger);
        vm.expectRevert(_unauthorized(stranger, DEFAULT_ADMIN_ROLE));
        core.setBufferPool(alice);
    }

    function test_unauth_pause() public {
        vm.prank(stranger);
        vm.expectRevert(_unauthorized(stranger, DEFAULT_ADMIN_ROLE));
        core.pause();
    }

    function test_unauth_pause_byVerifier() public {
        vm.prank(verifier);
        vm.expectRevert(_unauthorized(verifier, DEFAULT_ADMIN_ROLE));
        core.pause();
    }

    function test_unauth_unpause() public {
        vm.prank(admin);
        core.pause();
        vm.prank(stranger);
        vm.expectRevert(_unauthorized(stranger, DEFAULT_ADMIN_ROLE));
        core.unpause();
    }

    function test_unauth_upgradeToAndCall() public {
        BioRigCoreV5 newImpl = new BioRigCoreV5();
        vm.prank(stranger);
        vm.expectRevert(_unauthorized(stranger, UPGRADER_ROLE));
        core.upgradeToAndCall(address(newImpl), "");
    }

    // ---- admin setters happy paths ----

    function test_setURIGenerator_emitsAndStores() public {
        vm.expectEmit(true, true, false, false, address(core));
        emit URIGeneratorUpdated(address(generator), alice);
        vm.prank(admin);
        core.setURIGenerator(alice);
        assertEq(core.uriGenerator(), alice);
    }

    function test_setURIGenerator_toZero() public {
        vm.prank(admin);
        core.setURIGenerator(address(0));
        assertEq(core.uriGenerator(), address(0));
    }

    function test_setBufferPool_emitsAndStores() public {
        vm.expectEmit(true, true, false, false, address(core));
        emit BufferPoolUpdated(bufferPool, alice);
        vm.prank(admin);
        core.setBufferPool(alice);
        assertEq(core.bufferPool(), alice);
    }

    function test_setBufferPool_revertsOnZero() public {
        vm.prank(admin);
        vm.expectRevert(BioRigCoreV5.InvalidAddress.selector);
        core.setBufferPool(address(0));
        assertEq(core.bufferPool(), bufferPool);
    }
}
