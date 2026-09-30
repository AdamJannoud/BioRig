// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

import {IERC721} from "@openzeppelin/contracts/token/ERC721/IERC721.sol";
import {IERC721Metadata} from "@openzeppelin/contracts/token/ERC721/extensions/IERC721Metadata.sol";
import {IERC721Errors} from "@openzeppelin/contracts/interfaces/draft-IERC6093.sol";
import {IAccessControl} from "@openzeppelin/contracts/access/IAccessControl.sol";
import {IERC165} from "@openzeppelin/contracts/utils/introspection/IERC165.sol";
import {BaseTest} from "./Base.t.sol";
import {BioRigCoreV5} from "../src/BioRigCoreV5.sol";
import {AcceptingPlanter, RejectingPlanter} from "./mocks/Misc.sol";

contract ERC721BehaviorTest is BaseTest {
    uint256 internal id;

    function setUp() public override {
        super.setUp();
        id = _mint(planter, N1, 100, 200);
    }

    function test_transfer_liveTree_keepsStatsAndTba() public {
        BioRigCoreV5.TreeStats memory before = core.getTreeStats(id);
        vm.prank(planter);
        core.transferFrom(planter, alice, id);
        assertEq(core.ownerOf(id), alice);
        assertEq(core.balanceOf(planter), 0);
        assertEq(core.balanceOf(alice), 1);
        BioRigCoreV5.TreeStats memory afterT = core.getTreeStats(id);
        assertEq(afterT.tbaAddress, before.tbaAddress, "TBA follows the token, not the owner");
        assertEq(afterT.dbh, before.dbh);
        assertTrue(afterT.isAlive);
    }

    function test_transfer_deadTree_isAllowed() public {
        vm.prank(verifier);
        core.reportMortality(id);
        vm.prank(planter);
        core.transferFrom(planter, alice, id);
        assertEq(core.ownerOf(id), alice);
        assertFalse(core.getTreeStats(id).isAlive);
        assertFalse(core.isNullifierActive(N1));
    }

    function test_transfer_byStranger_reverts() public {
        vm.prank(stranger);
        vm.expectRevert(abi.encodeWithSelector(IERC721Errors.ERC721InsufficientApproval.selector, stranger, id));
        core.transferFrom(planter, stranger, id);
    }

    function test_approve_thenTransferByApproved() public {
        vm.prank(planter);
        core.approve(alice, id);
        assertEq(core.getApproved(id), alice);
        vm.prank(alice);
        core.transferFrom(planter, bob, id);
        assertEq(core.ownerOf(id), bob);
        assertEq(core.getApproved(id), address(0), "approval cleared on transfer");
    }

    function test_setApprovalForAll_operatorTransfers() public {
        vm.prank(planter);
        core.setApprovalForAll(alice, true);
        assertTrue(core.isApprovedForAll(planter, alice));
        vm.prank(alice);
        core.safeTransferFrom(planter, bob, id);
        assertEq(core.ownerOf(id), bob);
    }

    function test_approve_byNonOwner_reverts() public {
        vm.prank(stranger);
        vm.expectRevert(abi.encodeWithSelector(IERC721Errors.ERC721InvalidApprover.selector, stranger));
        core.approve(stranger, id);
    }

    function test_safeTransfer_toRejectingReceiver_reverts() public {
        RejectingPlanter r = new RejectingPlanter();
        vm.prank(planter);
        vm.expectRevert(abi.encodeWithSelector(IERC721Errors.ERC721InvalidReceiver.selector, address(r)));
        core.safeTransferFrom(planter, address(r), id);
        assertEq(core.ownerOf(id), planter);
    }

    function test_safeTransfer_toAcceptingReceiver() public {
        AcceptingPlanter r = new AcceptingPlanter();
        vm.prank(planter);
        core.safeTransferFrom(planter, address(r), id, "hi");
        assertEq(core.ownerOf(id), address(r));
        assertEq(r.received(), 1);
    }

    function test_transfer_toZero_reverts() public {
        vm.prank(planter);
        vm.expectRevert(abi.encodeWithSelector(IERC721Errors.ERC721InvalidReceiver.selector, address(0)));
        core.transferFrom(planter, address(0), id);
    }

    function test_ownerOf_unknown_reverts() public {
        vm.expectRevert(abi.encodeWithSelector(IERC721Errors.ERC721NonexistentToken.selector, 77));
        core.ownerOf(77);
    }

    function test_supportsInterface() public view {
        assertTrue(core.supportsInterface(type(IERC721).interfaceId));
        assertTrue(core.supportsInterface(type(IERC721Metadata).interfaceId));
        assertTrue(core.supportsInterface(type(IAccessControl).interfaceId));
        assertTrue(core.supportsInterface(type(IERC165).interfaceId));
        assertEq(type(IERC721).interfaceId, bytes4(0x80ac58cd));
        assertEq(type(IERC721Metadata).interfaceId, bytes4(0x5b5e139f));
        assertEq(type(IAccessControl).interfaceId, bytes4(0x7965db0b));
        assertFalse(core.supportsInterface(0xffffffff));
        assertFalse(core.supportsInterface(0xdeadbeef));
    }
}
