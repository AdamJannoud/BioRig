// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

import {ERC1967Proxy} from "@openzeppelin/contracts/proxy/ERC1967/ERC1967Proxy.sol";
import {ERC1967Utils} from "@openzeppelin/contracts/proxy/ERC1967/ERC1967Utils.sol";
import {BaseTest} from "./Base.t.sol";
import {BioRigCoreV5} from "../src/BioRigCoreV5.sol";
import {OriginalBioRigCoreV5} from "./orig/OriginalV5.sol";
import {URIGeneratorMock} from "./mocks/Misc.sol";

/// @notice R4, proven on a live proxy: state written by the verbatim original implementation
/// (test/orig/OriginalV5.sol) survives a UUPS upgrade to the hardened BioRigCoreV5 slot-for-slot,
/// and the hardened code operates on it correctly.
contract UpgradeFromOriginalTest is BaseTest {
    /// ERC-7201 namespace of ERC721Upgradeable (OZ v5): slot of `_owners` is base + 2.
    bytes32 internal constant ERC721_STORAGE = 0x80bb2b638cc20bc4d0a60d66940f3ab4a00c1d7b313497ca82fb0b4ab0079300;

    OriginalBioRigCoreV5 internal orig;
    URIGeneratorMock internal gen2;
    uint256 internal a;
    uint256 internal b;
    uint256 internal z;

    /// State written by the ORIGINAL code, including a zero-nullifier tree it allowed.
    function _originalWithState() internal {
        OriginalBioRigCoreV5 origImpl = new OriginalBioRigCoreV5();
        bytes memory init = abi.encodeCall(
            OriginalBioRigCoreV5.initialize,
            (admin, address(registry), accountImpl, block.chainid, bufferPool, address(generator))
        );
        orig = OriginalBioRigCoreV5(address(new ERC1967Proxy(address(origImpl), init)));
        gen2 = new URIGeneratorMock();

        vm.startPrank(admin);
        orig.grantRole(VERIFIER_ROLE, verifier);
        orig.setURIGenerator(address(gen2));
        orig.setBufferPool(bob);
        vm.stopPrank();
        vm.startPrank(verifier);
        a = orig.mintTree(planter, N1, 10, 20);
        b = orig.mintTree(alice, N2, 30, 40);
        z = orig.mintTree(bob, bytes32(0), 5, 5);
        orig.updateTreeGrowth(a, 15, 25);
        orig.reportMortality(b);
        vm.stopPrank();
    }

    function test_R4_upgradeFromVerbatimOriginal_preservesStateSlotForSlot() public {
        _originalWithState();

        bytes32[8] memory before;
        for (uint256 i; i < 8; ++i) {
            before[i] = vm.load(address(orig), bytes32(i));
        }
        bytes32 ownerSlotA = keccak256(abi.encode(a, uint256(ERC721_STORAGE) + 2));
        bytes32 ownerBefore = vm.load(address(orig), ownerSlotA);
        assertEq(address(uint160(uint256(ownerBefore))), planter, "namespace slot located");

        // --- upgrade to the hardened implementation (no reinitializer needed) ---
        BioRigCoreV5 hardened = new BioRigCoreV5();
        vm.prank(admin);
        orig.upgradeToAndCall(address(hardened), "");
        BioRigCoreV5 c = BioRigCoreV5(address(orig));
        assertEq(address(uint160(uint256(vm.load(address(c), ERC1967Utils.IMPLEMENTATION_SLOT)))), address(hardened));

        // --- every sequential slot byte-identical; namespaced ERC721 slot untouched ---
        for (uint256 i; i < 8; ++i) {
            assertEq(vm.load(address(c), bytes32(i)), before[i], "slot moved");
        }
        assertEq(vm.load(address(c), ownerSlotA), ownerBefore);
        _assertHardenedOperatesOnOriginalState(c);
    }

    function _assertHardenedOperatesOnOriginalState(BioRigCoreV5 c) internal {
        assertEq(c.erc6551Registry(), address(registry));
        assertEq(c.erc6551Implementation(), accountImpl);
        assertEq(c.chainId(), block.chainid);
        assertEq(c.bufferPool(), bob);
        assertEq(c.uriGenerator(), address(gen2));
        assertTrue(c.hasRole(DEFAULT_ADMIN_ROLE, admin));
        assertTrue(c.hasRole(VERIFIER_ROLE, verifier));
        assertEq(c.getTreeStats(a).dbh, 15);
        assertEq(
            c.getTreeStats(a).tbaAddress,
            registry.account(accountImpl, _salt(a, planter, N1), block.chainid, address(c), a)
        );
        assertFalse(c.getTreeStats(b).isAlive);
        assertTrue(c.isNullifierActive(N1));
        assertFalse(c.isNullifierActive(N2));
        assertEq(c.ownerOf(z), bob);
        assertEq(c.tokenURI(a), "tree:1:15:25:alive");

        // keeps operating: next id is 4, and the new mint passes TBA validation
        vm.prank(verifier);
        assertEq(c.mintTree(planter, N3, 1, 1), 4);
        // a pre-upgrade zero-nullifier tree stays fully manageable; only NEW zero mints are refused
        vm.startPrank(verifier);
        c.updateTreeGrowth(z, 6, 6);
        c.reportMortality(z);
        vm.expectRevert(BioRigCoreV5.InvalidNullifier.selector);
        c.mintTree(bob, bytes32(0), 1, 1);
        vm.stopPrank();
        assertFalse(c.isNullifierActive(bytes32(0)));
    }

    event BaseURIUpdated(string oldBaseURI, string newBaseURI);

    /// I-6 on a live proxy: the original's state survives the upgrade, the appended slot 8
    /// (`_baseTokenURI`) reads as "" right after it, the fallback stays "" until setBaseURI,
    /// then returns base + tokenId, and the base URI survives a second upgrade.
    function test_I6_upgradeFromVerbatimOriginal_baseURIUnsetUntilConfigured() public {
        _originalWithState();
        bytes32[8] memory before;
        for (uint256 i; i < 8; ++i) {
            before[i] = vm.load(address(orig), bytes32(i));
        }
        assertEq(vm.load(address(orig), bytes32(uint256(8))), bytes32(0), "slot 8 unused by the original");

        BioRigCoreV5 v1 = new BioRigCoreV5();
        vm.prank(admin);
        orig.upgradeToAndCall(address(v1), "");
        BioRigCoreV5 c = BioRigCoreV5(address(orig));

        for (uint256 i; i < 8; ++i) {
            assertEq(vm.load(address(c), bytes32(i)), before[i], "slot moved");
        }
        assertEq(vm.load(address(c), bytes32(uint256(8))), bytes32(0), "slot 8 zero after upgrade");
        assertEq(c.baseURI(), "");
        assertEq(c.getTreeStats(a).dbh, 15);
        assertEq(c.getTreeStats(a).biomass, 25);
        assertFalse(c.getTreeStats(b).isAlive);
        assertTrue(c.isNullifierActive(N1));
        assertEq(c.ownerOf(a), planter);
        assertEq(c.tokenURI(a), "tree:1:15:25:alive", "generator still wins");

        // generator removed: fallback is "" until an admin configures the base URI
        vm.prank(admin);
        c.setURIGenerator(address(0));
        assertEq(c.tokenURI(a), "");
        assertEq(c.tokenURI(b), "");

        for (uint256 i; i < 8; ++i) {
            before[i] = vm.load(address(c), bytes32(i));
        }
        vm.expectEmit(false, false, false, true, address(c));
        emit BaseURIUpdated("", "ipfs://bafyroot/");
        vm.prank(admin);
        c.setBaseURI("ipfs://bafyroot/");
        assertEq(c.tokenURI(a), "ipfs://bafyroot/1");
        assertEq(c.tokenURI(b), "ipfs://bafyroot/2");
        assertEq(c.tokenURI(z), "ipfs://bafyroot/3");
        for (uint256 i; i < 8; ++i) {
            assertEq(vm.load(address(c), bytes32(i)), before[i], "setBaseURI touched slot 0-7");
        }

        // second upgrade: the base URI survives
        BioRigCoreV5 v2 = new BioRigCoreV5();
        bytes32 slot8 = vm.load(address(c), bytes32(uint256(8)));
        vm.prank(admin);
        c.upgradeToAndCall(address(v2), "");
        assertEq(address(uint160(uint256(vm.load(address(c), ERC1967Utils.IMPLEMENTATION_SLOT)))), address(v2));
        assertEq(vm.load(address(c), bytes32(uint256(8))), slot8);
        assertEq(c.baseURI(), "ipfs://bafyroot/");
        assertEq(c.tokenURI(a), "ipfs://bafyroot/1");
        vm.prank(verifier);
        uint256 d = c.mintTree(planter, N3, 1, 1);
        assertEq(c.tokenURI(d), "ipfs://bafyroot/4");
    }
}
