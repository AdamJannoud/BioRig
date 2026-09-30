// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

import {IERC721Errors} from "@openzeppelin/contracts/interfaces/draft-IERC6093.sol";
import {BaseTest} from "./Base.t.sol";
import {BioRigCoreV5} from "../src/BioRigCoreV5.sol";
import {AcceptingPlanter, RejectingPlanter, WrongSelectorPlanter} from "./mocks/Misc.sol";

contract MintTest is BaseTest {
    function test_mint_firstIdIsOne_andIncrements() public {
        assertEq(_mint(planter, N1), 1);
        assertEq(_mint(planter, N2), 2);
        assertEq(_mint(alice, N3), 3);
        assertEq(core.balanceOf(planter), 2);
        assertEq(core.ownerOf(3), alice);
        assertEq(uint256(vm.load(address(core), bytes32(uint256(0)))), 4);
    }

    function test_mint_storesStats() public {
        vm.warp(1_800_000_000);
        uint256 id = _mint(planter, N1, 123, 456);
        BioRigCoreV5.TreeStats memory s = core.getTreeStats(id);
        assertEq(s.dbh, 123);
        assertEq(s.biomass, 456);
        assertEq(s.lastUpdated, 1_800_000_000);
        assertEq(s.tbaAddress, _expectedTba(id, planter, N1));
        assertTrue(s.isAlive);
        assertEq(s.spatialNullifier, N1);
    }

    function test_mint_emitsTreeMintedAndTransfer() public {
        address tba = _expectedTba(1, planter, N1);
        vm.expectEmit(true, true, true, false, address(core));
        emit Transfer(address(0), planter, 1);
        vm.expectEmit(true, true, true, true, address(core));
        emit TreeMinted(1, tba, N1);
        _mint(planter, N1);
    }

    function test_mint_zeroInitialStats() public {
        uint256 id = _mint(planter, N1, 0, 0);
        BioRigCoreV5.TreeStats memory s = core.getTreeStats(id);
        assertEq(s.dbh, 0);
        assertEq(s.biomass, 0);
        assertTrue(s.isAlive);
        vm.prank(verifier);
        core.updateTreeGrowth(id, 0, 0); // equal is allowed (non-decreasing)
        vm.prank(verifier);
        core.updateTreeGrowth(id, 1, 0);
    }

    function test_mint_maxInitialStats() public {
        uint256 id = _mint(planter, N1, type(uint96).max, type(uint96).max);
        assertEq(core.getTreeStats(id).dbh, type(uint96).max);
        assertEq(core.getTreeStats(id).biomass, type(uint96).max);
    }

    function test_mint_zeroPlanter_reverts() public {
        vm.prank(verifier);
        vm.expectRevert(BioRigCoreV5.InvalidAddress.selector);
        core.mintTree(address(0), N1, 1, 1);
        assertFalse(core.isNullifierActive(N1));
    }

    function test_mint_whilePaused_reverts() public {
        vm.prank(admin);
        core.pause();
        vm.prank(verifier);
        vm.expectRevert(_enforcedPause());
        core.mintTree(planter, N1, 1, 1);
    }

    function test_mint_withoutVerifierRole_reverts() public {
        vm.prank(planter);
        vm.expectRevert(_unauthorized(planter, VERIFIER_ROLE));
        core.mintTree(planter, N1, 1, 1);
    }

    function test_mint_toAcceptingContract() public {
        AcceptingPlanter p = new AcceptingPlanter();
        uint256 id = _mint(address(p), N1);
        assertEq(core.ownerOf(id), address(p));
        assertEq(p.received(), 1);
        assertEq(p.lastTokenId(), id);
    }

    function test_mint_toRejectingContract_revertsAtomically() public {
        RejectingPlanter p = new RejectingPlanter();
        address wouldBeTba = _expectedTba(1, address(p), N1);
        vm.prank(verifier);
        vm.expectRevert(abi.encodeWithSelector(IERC721Errors.ERC721InvalidReceiver.selector, address(p)));
        core.mintTree(address(p), N1, 1, 1);
        // nothing persisted: nullifier, token id counter, and the account deployment all rolled back
        assertFalse(core.isNullifierActive(N1));
        assertEq(wouldBeTba.code.length, 0);
        vm.expectRevert(BioRigCoreV5.InvalidTree.selector);
        core.getTreeStats(1);
        assertEq(_mint(planter, N1), 1);
    }

    function test_mint_toWrongSelectorContract_reverts() public {
        WrongSelectorPlanter p = new WrongSelectorPlanter();
        vm.prank(verifier);
        vm.expectRevert(abi.encodeWithSelector(IERC721Errors.ERC721InvalidReceiver.selector, address(p)));
        core.mintTree(address(p), N1, 1, 1);
    }

    function testFuzz_mint_storesArbitraryStats(address to, bytes32 n, uint96 dbh, uint96 bio) public {
        vm.assume(to != address(0) && to.code.length == 0);
        vm.assume(uint160(to) > 0xff); // skip precompiles
        vm.assume(n != bytes32(0)); // rejected by InvalidNullifier (tested separately)
        vm.prank(verifier);
        uint256 id = core.mintTree(to, n, dbh, bio);
        BioRigCoreV5.TreeStats memory s = core.getTreeStats(id);
        assertEq(s.dbh, dbh);
        assertEq(s.biomass, bio);
        assertEq(s.spatialNullifier, n);
        assertEq(core.ownerOf(id), to);
    }
}
