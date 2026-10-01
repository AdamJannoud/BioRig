// SPDX-License-Identifier: MIT
pragma solidity ^0.8.28;

import "forge-std/Test.sol";
import "@openzeppelin/contracts/proxy/ERC1967/ERC1967Proxy.sol";
import "./OriginalV5.sol";

/// A registry that follows the ERC-6551 signature but returns the zero address.
contract ZeroReturningRegistry {
    function createAccount(
        address,
        bytes32,
        uint256,
        address,
        uint256
    ) external pure returns (address) {
        return address(0);
    }
}

/// INDEPENDENT FALSIFICATION TEST - written after the main suite ran, deliberately NOT part of the
/// delivered suite. It re-checks the headline finding against src/BioRigCoreV5.sol.orig, the
/// verbatim original text, so the finding does not rest on the suite testing its own fix.
/// It asserts the DEFECTIVE behaviour of the original, which is the point of the test.
contract IndependentH1Test is Test {
    OriginalBioRigCoreV5 internal core;
    address internal constant PLANTER = address(0xA11CE);
    address internal constant VERIFIER = address(0xBEEF);
    bytes32 internal constant NULLIFIER = keccak256("plot-1");

    function setUp() public {
        ZeroReturningRegistry registry = new ZeroReturningRegistry();
        OriginalBioRigCoreV5 impl = new OriginalBioRigCoreV5();
        bytes memory init = abi.encodeCall(
            OriginalBioRigCoreV5.initialize,
            (address(this), address(registry), address(0x1234), 1, address(0x5678), address(0))
        );
        core = OriginalBioRigCoreV5(address(new ERC1967Proxy(address(impl), init)));
        core.grantRole(core.VERIFIER_ROLE(), VERIFIER);
    }

    function test_H1_zeroRegistry_mintsUnusableToken_andLocksPlot() public {
        vm.prank(VERIFIER);
        uint256 id = core.mintTree(PLANTER, NULLIFIER, 100, 200);

        // The mint "succeeds": the token exists, is owned, but its tree is unusable.
        assertEq(id, 1);
        assertEq(core.ownerOf(id), PLANTER);

        vm.expectRevert(OriginalBioRigCoreV5.InvalidTree.selector);
        core.getTreeStats(id);

        vm.expectRevert(OriginalBioRigCoreV5.InvalidTree.selector);
        core.tokenURI(id);

        vm.prank(VERIFIER);
        vm.expectRevert(OriginalBioRigCoreV5.InvalidTree.selector);
        core.reportMortality(id);

        // reportMortality is the only path that releases a nullifier, so the plot stays claimed
        // forever and can never be minted again.
        vm.prank(VERIFIER);
        vm.expectRevert(OriginalBioRigCoreV5.NullifierInUse.selector);
        core.mintTree(PLANTER, NULLIFIER, 100, 200);
    }
}
