// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

import {IERC1967} from "@openzeppelin/contracts/interfaces/IERC1967.sol";
import {ERC1967Utils} from "@openzeppelin/contracts/proxy/ERC1967/ERC1967Utils.sol";
import {UUPSUpgradeable} from "@openzeppelin/contracts-upgradeable/proxy/utils/UUPSUpgradeable.sol";
import {Initializable} from "@openzeppelin/contracts-upgradeable/proxy/utils/Initializable.sol";
import {BaseTest} from "./Base.t.sol";
import {BioRigCoreV5} from "../src/BioRigCoreV5.sol";
import {BioRigCoreV6} from "./mocks/BioRigCoreV6.sol";
import {NotUUPS, URIGeneratorMock} from "./mocks/Misc.sol";

contract UpgradesTest is BaseTest {
    function _implOf(address proxy) internal view returns (address) {
        return address(uint160(uint256(vm.load(proxy, ERC1967Utils.IMPLEMENTATION_SLOT))));
    }

    function test_proxy_pointsAtImplementation() public view {
        assertEq(_implOf(address(core)), address(impl));
        assertEq(impl.proxiableUUID(), ERC1967Utils.IMPLEMENTATION_SLOT);
    }

    function test_upgrade_byUpgrader() public {
        BioRigCoreV6 v6 = new BioRigCoreV6();
        vm.expectEmit(true, false, false, false, address(core));
        emit IERC1967.Upgraded(address(v6));
        vm.prank(admin);
        core.upgradeToAndCall(address(v6), "");
        assertEq(_implOf(address(core)), address(v6));
        assertEq(BioRigCoreV6(address(core)).version(), "6");
    }

    function test_upgrade_byNonUpgrader_reverts() public {
        BioRigCoreV6 v6 = new BioRigCoreV6();
        vm.prank(stranger);
        vm.expectRevert(_unauthorized(stranger, UPGRADER_ROLE));
        core.upgradeToAndCall(address(v6), "");
        assertEq(_implOf(address(core)), address(impl));
    }

    function test_upgrade_byVerifier_reverts() public {
        BioRigCoreV6 v6 = new BioRigCoreV6();
        vm.prank(verifier);
        vm.expectRevert(_unauthorized(verifier, UPGRADER_ROLE));
        core.upgradeToAndCall(address(v6), "");
    }

    function test_upgrade_adminWithoutUpgraderRole_reverts() public {
        vm.prank(admin);
        core.revokeRole(UPGRADER_ROLE, admin);
        BioRigCoreV6 v6 = new BioRigCoreV6();
        vm.prank(admin);
        vm.expectRevert(_unauthorized(admin, UPGRADER_ROLE));
        core.upgradeToAndCall(address(v6), "");
    }

    function test_upgrade_grantedUpgrader() public {
        vm.prank(admin);
        core.grantRole(UPGRADER_ROLE, alice);
        BioRigCoreV6 v6 = new BioRigCoreV6();
        vm.prank(alice);
        core.upgradeToAndCall(address(v6), "");
        assertEq(_implOf(address(core)), address(v6));
    }

    function test_upgrade_toNonUUPS_reverts() public {
        NotUUPS bad = new NotUUPS();
        vm.prank(admin);
        vm.expectRevert(abi.encodeWithSelector(ERC1967Utils.ERC1967InvalidImplementation.selector, address(bad)));
        core.upgradeToAndCall(address(bad), "");
    }

    function test_upgrade_calledOnImplementationDirectly_reverts() public {
        // explicitly about the bare implementation: UUPS forbids upgrading outside a proxy context
        BioRigCoreV6 v6 = new BioRigCoreV6();
        vm.prank(admin);
        vm.expectRevert(UUPSUpgradeable.UUPSUnauthorizedCallContext.selector);
        impl.upgradeToAndCall(address(v6), "");
    }

    function test_upgrade_v6ReinitializerRunsOnce() public {
        BioRigCoreV6 v6 = new BioRigCoreV6();
        vm.prank(admin);
        core.upgradeToAndCall(address(v6), abi.encodeCall(BioRigCoreV6.initializeV6, (77)));
        assertEq(BioRigCoreV6(address(core)).v6Marker(), 77);
        vm.prank(admin);
        vm.expectRevert(Initializable.InvalidInitialization.selector);
        BioRigCoreV6(address(core)).initializeV6(88);
        // V5 initializer still locked
        vm.expectRevert(Initializable.InvalidInitialization.selector);
        core.initialize(admin, address(registry), accountImpl, block.chainid, bufferPool, address(0));
    }

    /// Storage-layout preservation: write every kind of V5 state, upgrade, read it all back through V6.
    function test_upgrade_v6ReadsV5State_layoutPreserved() public {
        // --- V5 writes ---
        uint256 a = _mint(planter, N1, 10, 20);
        vm.warp(block.timestamp + 100);
        uint256 b = _mint(alice, N2, 30, 40);
        vm.prank(verifier);
        core.updateTreeGrowth(a, 15, 25);
        vm.prank(verifier);
        core.reportMortality(b);
        vm.prank(planter);
        core.approve(bob, a);
        URIGeneratorMock gen2 = new URIGeneratorMock();
        // short (< 32 bytes) so the whole string is stored inline in V5's slot 8
        string memory base = "ipfs://bafyI6layout/";
        vm.startPrank(admin);
        core.setURIGenerator(address(gen2));
        core.setBufferPool(bob);
        core.setBaseURI(base);
        core.pause();
        vm.stopPrank();

        BioRigCoreV5.TreeStats memory sa = core.getTreeStats(a);
        BioRigCoreV5.TreeStats memory sb = core.getTreeStats(b);

        // raw slots before upgrade: all of V5's own sequential slots, 0-7 plus _baseTokenURI at 8
        bytes32[9] memory before;
        for (uint256 i; i < 9; ++i) {
            before[i] = vm.load(address(core), bytes32(i));
        }
        assertTrue(before[8] != bytes32(0), "slot 8 must hold the base URI at snapshot time");

        // --- upgrade ---
        BioRigCoreV6 v6impl = new BioRigCoreV6();
        vm.prank(admin);
        core.upgradeToAndCall(address(v6impl), abi.encodeCall(BioRigCoreV6.initializeV6, (0xC0FFEE)));
        BioRigCoreV6 v6 = BioRigCoreV6(address(core));

        // --- raw slots unchanged, appended var is in slot 9 (V5 now ends at slot 8) ---
        for (uint256 i; i < 9; ++i) {
            assertEq(vm.load(address(core), bytes32(i)), before[i], "V5 slot moved");
        }
        assertEq(uint256(vm.load(address(core), bytes32(uint256(9)))), 0xC0FFEE);
        assertEq(v6.v6Marker(), 0xC0FFEE);
        // non-collision: initializeV6 wrote the marker into none of V5's own slots, and no V5 slot
        // held it before either (so the post-upgrade check can't be satisfied by coincidence)
        for (uint256 i; i < 9; ++i) {
            assertTrue(before[i] != bytes32(uint256(0xC0FFEE)), "marker value already in a V5 slot");
            assertTrue(vm.load(address(core), bytes32(i)) != bytes32(uint256(0xC0FFEE)), "V6 marker collided with a V5 slot");
        }
        assertEq(v6.baseURI(), base);

        // --- V6 reads V5 state ---
        assertEq(v6.nextTokenIdV6(), 3);
        assertEq(v6.erc6551Registry(), address(registry));
        assertEq(v6.erc6551Implementation(), accountImpl);
        assertEq(v6.chainId(), block.chainid);
        assertEq(v6.bufferPool(), bob);
        assertEq(v6.uriGenerator(), address(gen2));
        assertTrue(v6.paused());
        assertTrue(v6.hasRole(VERIFIER_ROLE, verifier));
        assertTrue(v6.hasRole(DEFAULT_ADMIN_ROLE, admin));
        assertEq(v6.name(), "BioRig Tree");
        assertEq(v6.ownerOf(a), planter);
        assertEq(v6.ownerOf(b), alice);
        assertEq(v6.getApproved(a), bob);
        assertEq(v6.balanceOf(planter), 1);
        assertTrue(v6.isNullifierActive(N1));
        assertFalse(v6.isNullifierActive(N2));

        BioRigCoreV5.TreeStats memory va = v6.getTreeStats(a);
        BioRigCoreV5.TreeStats memory vb = v6.getTreeStats(b);
        assertEq(keccak256(abi.encode(va)), keccak256(abi.encode(sa)));
        assertEq(keccak256(abi.encode(vb)), keccak256(abi.encode(sb)));
        assertEq(va.dbh, 15);
        assertFalse(vb.isAlive);

        // --- V6 continues where V5 stopped ---
        vm.prank(admin);
        v6.unpause();
        vm.prank(verifier);
        assertEq(v6.mintTree(planter, N3, 1, 1), 3);
        vm.prank(verifier);
        vm.expectRevert(BioRigCoreV5.NullifierInUse.selector);
        v6.mintTree(planter, N1, 1, 1);
        assertEq(v6.tokenURI(a), "tree:1:15:25:alive");
        // with the generator cleared, V6 resolves the fallback from V5's preserved base URI
        vm.prank(admin);
        v6.setURIGenerator(address(0));
        assertEq(v6.tokenURI(a), string.concat(base, vm.toString(a)));
        assertEq(v6.tokenURI(a), "ipfs://bafyI6layout/1");
    }

    /// H5: parents use ERC-7201 namespaced storage, so the only sequential slots are
    /// BioRigCoreV5's own (0..7). Appending in the most-derived contract cannot collide.
    function test_H5_parentsUseNamespacedStorage() public {
        _mint(planter, N1);
        // ERC721Upgradeable namespace: keccak256(abi.encode(uint256(keccak256("openzeppelin.storage.ERC721")) - 1)) & ~0xff
        bytes32 erc721Slot = keccak256(abi.encode(uint256(keccak256("openzeppelin.storage.ERC721")) - 1))
            & ~bytes32(uint256(0xff));
        assertEq(erc721Slot, 0x80bb2b638cc20bc4d0a60d66940f3ab4a00c1d7b313497ca82fb0b4ab0079300);
        // _owners mapping is at namespace + 2
        bytes32 ownerSlot = keccak256(abi.encode(uint256(1), uint256(erc721Slot) + 2));
        assertEq(address(uint160(uint256(vm.load(address(core), ownerSlot)))), planter);
        // slot 0 is V5's own _nextTokenId, not any parent's variable
        assertEq(uint256(vm.load(address(core), bytes32(0))), 2);
        // slot 1/2 are V5's registry / implementation
        assertEq(address(uint160(uint256(vm.load(address(core), bytes32(uint256(1)))))), address(registry));
        assertEq(address(uint160(uint256(vm.load(address(core), bytes32(uint256(2)))))), accountImpl);
    }

    /// TreeStats packing: slot A = dbh|biomass|lastUpdated, slot B = tbaAddress|isAlive, slot C = nullifier.
    function test_treeStatsPacking() public {
        uint256 id = _mint(planter, N1, 7, 9);
        bytes32 base = keccak256(abi.encode(id, uint256(6)));
        uint256 s0 = uint256(vm.load(address(core), base));
        assertEq(uint96(s0), 7);
        assertEq(uint96(s0 >> 96), 9);
        assertEq(uint64(s0 >> 192), uint64(block.timestamp));
        uint256 s1 = uint256(vm.load(address(core), bytes32(uint256(base) + 1)));
        assertEq(address(uint160(s1)), core.getTreeStats(id).tbaAddress);
        assertEq(uint8(s1 >> 160), 1);
        assertEq(vm.load(address(core), bytes32(uint256(base) + 2)), N1);
        assertEq(vm.load(address(core), keccak256(abi.encode(N1, uint256(7)))), bytes32(uint256(1)));
    }
}
