// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

import {Vm, VmSafe} from "forge-std/Vm.sol";
import {BaseTest} from "./Base.t.sol";
import {BioRigCoreV5} from "../src/BioRigCoreV5.sol";

contract GrowthTest is BaseTest {
    uint256 internal id;

    function setUp() public override {
        super.setUp();
        id = _mint(planter, N1, 100, 200);
    }

    function _grow(uint256 tokenId, uint96 d, uint96 b) internal {
        vm.prank(verifier);
        core.updateTreeGrowth(tokenId, d, b);
    }

    function test_growth_updatesStatsAndTimestamp() public {
        uint64 t0 = core.getTreeStats(id).lastUpdated;
        vm.warp(block.timestamp + 30 days);
        _grow(id, 150, 260);
        BioRigCoreV5.TreeStats memory s = core.getTreeStats(id);
        assertEq(s.dbh, 150);
        assertEq(s.biomass, 260);
        assertEq(s.lastUpdated, t0 + 30 days);
        assertEq(s.lastUpdated, uint64(block.timestamp));
        // untouched fields
        assertTrue(s.isAlive);
        assertEq(s.spatialNullifier, N1);
        assertEq(s.tbaAddress, _expectedTba(id, planter, N1));
    }

    function test_growth_emitsEvent() public {
        vm.expectEmit(true, false, false, true, address(core));
        emit GrowthUpdated(id, 150, 260);
        _grow(id, 150, 260);
    }

    function test_growth_equalValuesAllowed_refreshesTimestamp() public {
        vm.warp(block.timestamp + 1);
        _grow(id, 100, 200);
        assertEq(core.getTreeStats(id).lastUpdated, uint64(block.timestamp));
    }

    function test_growth_dbhDecrease_reverts() public {
        vm.prank(verifier);
        vm.expectRevert(BioRigCoreV5.InvalidGrowthData.selector);
        core.updateTreeGrowth(id, 99, 300);
    }

    function test_growth_biomassDecrease_reverts() public {
        vm.prank(verifier);
        vm.expectRevert(BioRigCoreV5.InvalidGrowthData.selector);
        core.updateTreeGrowth(id, 300, 199);
    }

    function test_growth_bothDecrease_reverts() public {
        vm.prank(verifier);
        vm.expectRevert(BioRigCoreV5.InvalidGrowthData.selector);
        core.updateTreeGrowth(id, 0, 0);
    }

    function test_growth_failedUpdateLeavesStateUntouched() public {
        vm.warp(block.timestamp + 5);
        vm.prank(verifier);
        vm.expectRevert(BioRigCoreV5.InvalidGrowthData.selector);
        core.updateTreeGrowth(id, 101, 199);
        BioRigCoreV5.TreeStats memory s = core.getTreeStats(id);
        assertEq(s.dbh, 100);
        assertEq(s.biomass, 200);
        assertEq(s.lastUpdated, 1_700_000_000);
    }

    function test_growth_deadTree_reverts() public {
        vm.prank(verifier);
        core.reportMortality(id);
        vm.prank(verifier);
        vm.expectRevert(BioRigCoreV5.TreeIsDead.selector);
        core.updateTreeGrowth(id, 101, 201);
    }

    function test_growth_unknownToken_reverts() public {
        vm.prank(verifier);
        vm.expectRevert(BioRigCoreV5.InvalidTree.selector);
        core.updateTreeGrowth(999, 1, 1);
    }

    function test_growth_tokenZero_reverts() public {
        vm.prank(verifier);
        vm.expectRevert(BioRigCoreV5.InvalidTree.selector);
        core.updateTreeGrowth(0, 1, 1);
    }

    function test_growth_maxValues() public {
        _grow(id, type(uint96).max, type(uint96).max);
        assertEq(core.getTreeStats(id).dbh, type(uint96).max);
    }

    /// H4: the growth path makes NO external calls, so there is nothing to re-enter through.
    /// Every account touched during updateTreeGrowth is the proxy or its implementation.
    function test_H4_growthPath_makesNoExternalCalls() public {
        vm.prank(verifier);
        vm.startStateDiffRecording();
        core.updateTreeGrowth(id, 150, 260);
        VmSafe.AccountAccess[] memory acc = vm.stopAndReturnStateDiff();
        assertGt(acc.length, 0);
        for (uint256 i; i < acc.length; ++i) {
            if (acc[i].kind == VmSafe.AccountAccessKind.Call || acc[i].kind == VmSafe.AccountAccessKind.DelegateCall
                    || acc[i].kind == VmSafe.AccountAccessKind.StaticCall) {
                assertTrue(
                    acc[i].account == address(core) || acc[i].account == address(impl),
                    "growth path called an external account"
                );
            }
        }
    }

    function test_H4_mortalityPath_makesNoExternalCalls() public {
        vm.prank(verifier);
        vm.startStateDiffRecording();
        core.reportMortality(id);
        VmSafe.AccountAccess[] memory acc = vm.stopAndReturnStateDiff();
        for (uint256 i; i < acc.length; ++i) {
            if (acc[i].kind == VmSafe.AccountAccessKind.Call || acc[i].kind == VmSafe.AccountAccessKind.DelegateCall
                    || acc[i].kind == VmSafe.AccountAccessKind.StaticCall) {
                assertTrue(acc[i].account == address(core) || acc[i].account == address(impl));
            }
        }
    }

    /// H6: uint64(block.timestamp) only truncates past year ~584 billion. Showing where it would bite.
    function test_H6_timestampCast_truncatesOnlyBeyondUint64() public {
        vm.warp(type(uint64).max);
        _grow(id, 100, 200);
        assertEq(core.getTreeStats(id).lastUpdated, type(uint64).max);
        vm.warp(uint256(type(uint64).max) + 1);
        _grow(id, 100, 200);
        assertEq(core.getTreeStats(id).lastUpdated, 0, "wraps only after 2^64 seconds");
    }

    function testFuzz_growth_monotonic(uint96 d, uint96 b) public {
        vm.prank(verifier);
        if (d < 100 || b < 200) {
            vm.expectRevert(BioRigCoreV5.InvalidGrowthData.selector);
            core.updateTreeGrowth(id, d, b);
        } else {
            core.updateTreeGrowth(id, d, b);
            assertEq(core.getTreeStats(id).dbh, d);
            assertEq(core.getTreeStats(id).biomass, b);
        }
    }
}
