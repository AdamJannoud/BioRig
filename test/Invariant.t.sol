// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

import {Test} from "forge-std/Test.sol";
import {BaseTest} from "./Base.t.sol";
import {BioRigCoreV5} from "../src/BioRigCoreV5.sol";

/// @notice Drives the proxy with random mints / growth / mortality / transfers / pause toggles.
/// A small nullifier pool forces collisions and re-plants.
contract TreeHandler is Test {
    BioRigCoreV5 public core;
    address public verifier;
    address public admin;

    uint256[] public ids;
    mapping(uint256 => uint96) public ghostDbh;
    mapping(uint256 => uint96) public ghostBio;
    mapping(uint256 => bool) public ghostDead;
    uint256 public minted;
    uint256 public kills;

    address[4] internal owners = [address(0xA1), address(0xA2), address(0xA3), address(0xA4)];

    constructor(BioRigCoreV5 _core, address _verifier, address _admin) {
        core = _core;
        verifier = _verifier;
        admin = _admin;
    }

    function idsLength() external view returns (uint256) {
        return ids.length;
    }

    function nullifier(uint256 seed) public pure returns (bytes32) {
        return keccak256(abi.encode("plot", seed % 6));
    }

    uint256 public constant MAX_TREES = 40; // keeps the O(n^2) invariant checks cheap

    function mint(uint256 ownerSeed, uint256 nSeed, uint96 dbh, uint96 bio) external {
        if (core.paused() || ids.length >= MAX_TREES) return;
        bytes32 n = nullifier(nSeed);
        if (core.isNullifierActive(n)) {
            vm.expectRevert(BioRigCoreV5.NullifierInUse.selector);
            vm.prank(verifier);
            core.mintTree(owners[ownerSeed % 4], n, dbh, bio);
            return;
        }
        vm.prank(verifier);
        uint256 id = core.mintTree(owners[ownerSeed % 4], n, dbh, bio);
        ids.push(id);
        ghostDbh[id] = dbh;
        ghostBio[id] = bio;
        minted++;
    }

    function grow(uint256 idSeed, uint96 dDbh, uint96 dBio) external {
        if (ids.length == 0 || core.paused()) return;
        uint256 id = ids[idSeed % ids.length];
        uint96 d = uint96(bound(uint256(ghostDbh[id]) + dDbh, ghostDbh[id], type(uint96).max));
        uint96 b = uint96(bound(uint256(ghostBio[id]) + dBio, ghostBio[id], type(uint96).max));
        vm.prank(verifier);
        if (ghostDead[id]) {
            vm.expectRevert(BioRigCoreV5.TreeIsDead.selector);
            core.updateTreeGrowth(id, d, b);
            return;
        }
        core.updateTreeGrowth(id, d, b);
        ghostDbh[id] = d;
        ghostBio[id] = b;
    }

    function shrink(uint256 idSeed) external {
        if (ids.length == 0 || core.paused()) return;
        uint256 id = ids[idSeed % ids.length];
        if (ghostDead[id] || ghostDbh[id] == 0) return;
        vm.prank(verifier);
        vm.expectRevert(BioRigCoreV5.InvalidGrowthData.selector);
        core.updateTreeGrowth(id, ghostDbh[id] - 1, ghostBio[id]);
    }

    function kill(uint256 idSeed) external {
        if (ids.length == 0 || core.paused()) return;
        uint256 id = ids[idSeed % ids.length];
        vm.prank(verifier);
        if (ghostDead[id]) {
            vm.expectRevert(BioRigCoreV5.TreeIsDead.selector);
            core.reportMortality(id);
            return;
        }
        core.reportMortality(id);
        ghostDead[id] = true;
        kills++;
    }

    function transfer(uint256 idSeed, uint256 toSeed) external {
        if (ids.length == 0) return;
        uint256 id = ids[idSeed % ids.length];
        address from = core.ownerOf(id);
        vm.prank(from);
        core.transferFrom(from, owners[toSeed % 4], id);
    }

    function togglePause() external {
        bool p = core.paused();
        vm.prank(admin);
        if (p) core.unpause();
        else core.pause();
    }
}

/// forge-config: default.invariant.runs = 128
/// forge-config: default.invariant.depth = 100
/// forge-config: default.invariant.fail-on-revert = true
contract InvariantTest is BaseTest {
    TreeHandler internal handler;

    function setUp() public override {
        super.setUp();
        handler = new TreeHandler(core, verifier, admin);
        targetContract(address(handler));
    }

    /// Guard against a vacuous pass: the handler must actually have minted trees.
    function afterInvariant() public view {
        assertGt(handler.minted(), 0, "handler never minted");
    }

    /// For every live tree, its recorded nullifier is active, and no two live trees share one.
    function invariant_liveTreeNullifiersActiveAndUnique() public view {
        uint256 n = handler.idsLength();
        for (uint256 i; i < n; ++i) {
            BioRigCoreV5.TreeStats memory si = core.getTreeStats(handler.ids(i));
            if (!si.isAlive) continue;
            assertTrue(core.isNullifierActive(si.spatialNullifier), "live tree nullifier inactive");
            for (uint256 j = i + 1; j < n; ++j) {
                BioRigCoreV5.TreeStats memory sj = core.getTreeStats(handler.ids(j));
                if (sj.isAlive) assertTrue(si.spatialNullifier != sj.spatialNullifier, "shared nullifier");
            }
        }
    }

    /// An active nullifier is always backed by exactly one live tree (no leaked/locked nullifiers).
    function invariant_activeNullifierHasLiveTree() public view {
        uint256 n = handler.idsLength();
        for (uint256 s; s < 6; ++s) {
            bytes32 nul = handler.nullifier(s);
            uint256 live;
            for (uint256 i; i < n; ++i) {
                BioRigCoreV5.TreeStats memory si = core.getTreeStats(handler.ids(i));
                if (si.isAlive && si.spatialNullifier == nul) live++;
            }
            assertEq(core.isNullifierActive(nul) ? 1 : 0, live);
        }
    }

    function invariant_statsMatchGhostAndAreConsistent() public view {
        uint256 n = handler.idsLength();
        for (uint256 i; i < n; ++i) {
            uint256 id = handler.ids(i);
            BioRigCoreV5.TreeStats memory s = core.getTreeStats(id);
            assertEq(s.dbh, handler.ghostDbh(id));
            assertEq(s.biomass, handler.ghostBio(id));
            assertEq(s.isAlive, !handler.ghostDead(id));
            assertTrue(s.tbaAddress != address(0));
            assertEq(id, i + 1, "ids are dense from 1");
        }
    }

    function invariant_tokenCounter() public view {
        assertEq(uint256(vm.load(address(core), bytes32(0))), handler.minted() + 1);
        uint256 total;
        for (uint160 k = 0xA1; k <= 0xA4; ++k) {
            total += core.balanceOf(address(k));
        }
        assertEq(total, handler.minted());
    }
}
