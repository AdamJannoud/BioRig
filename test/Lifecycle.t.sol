// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

import {ERC1967Proxy} from "@openzeppelin/contracts/proxy/ERC1967/ERC1967Proxy.sol";
import {Initializable} from "@openzeppelin/contracts-upgradeable/proxy/utils/Initializable.sol";
import {BaseTest} from "./Base.t.sol";
import {BioRigCoreV5} from "../src/BioRigCoreV5.sol";

contract LifecycleTest is BaseTest {
    function _initData(address a, address reg, address accImpl, address pool, address gen)
        internal
        view
        returns (bytes memory)
    {
        return abi.encodeCall(BioRigCoreV5.initialize, (a, reg, accImpl, block.chainid, pool, gen));
    }

    function test_initialize_setsState() public view {
        assertEq(core.name(), "BioRig Tree");
        assertEq(core.symbol(), "TREE");
        assertEq(core.erc6551Registry(), address(registry));
        assertEq(core.erc6551Implementation(), accountImpl);
        assertEq(core.chainId(), block.chainid);
        assertEq(core.bufferPool(), bufferPool);
        assertEq(core.uriGenerator(), address(generator));
        assertTrue(core.hasRole(DEFAULT_ADMIN_ROLE, admin));
        assertTrue(core.hasRole(UPGRADER_ROLE, admin));
        assertFalse(core.hasRole(VERIFIER_ROLE, admin), "admin is not auto-granted VERIFIER_ROLE");
        assertFalse(core.paused());
        // _nextTokenId is private: slot 0
        assertEq(uint256(vm.load(address(core), bytes32(uint256(0)))), 1);
    }

    function test_initialize_allowsZeroUriGenerator() public {
        BioRigCoreV5 c = _deployProxy(address(registry), address(0));
        assertEq(c.uriGenerator(), address(0));
    }

    function test_initialize_revertsOnDoubleInit() public {
        vm.expectRevert(Initializable.InvalidInitialization.selector);
        core.initialize(admin, address(registry), accountImpl, block.chainid, bufferPool, address(generator));
    }

    function test_initialize_revertsOnDoubleInit_evenByAdmin() public {
        vm.prank(admin);
        vm.expectRevert(Initializable.InvalidInitialization.selector);
        core.initialize(stranger, address(registry), accountImpl, block.chainid, bufferPool, address(0));
    }

    function test_initialize_revertsOnZeroAdmin() public {
        bytes memory d = _initData(address(0), address(registry), accountImpl, bufferPool, address(0));
        vm.expectRevert(BioRigCoreV5.ZeroAdminAddress.selector);
        new ERC1967Proxy(address(impl), d);
    }

    function test_initialize_revertsOnZeroRegistry() public {
        bytes memory d = _initData(admin, address(0), accountImpl, bufferPool, address(0));
        vm.expectRevert(BioRigCoreV5.InvalidAddress.selector);
        new ERC1967Proxy(address(impl), d);
    }

    function test_initialize_revertsOnZeroAccountImplementation() public {
        bytes memory d = _initData(admin, address(registry), address(0), bufferPool, address(0));
        vm.expectRevert(BioRigCoreV5.InvalidAddress.selector);
        new ERC1967Proxy(address(impl), d);
    }

    function test_initialize_revertsOnZeroBufferPool() public {
        bytes memory d = _initData(admin, address(registry), accountImpl, address(0), address(0));
        vm.expectRevert(BioRigCoreV5.InvalidAddress.selector);
        new ERC1967Proxy(address(impl), d);
    }

    function test_initialize_zeroAdminCheckedBeforeOtherArgs() public {
        bytes memory d = _initData(address(0), address(0), address(0), address(0), address(0));
        vm.expectRevert(BioRigCoreV5.ZeroAdminAddress.selector);
        new ERC1967Proxy(address(impl), d);
    }

    /// Informational: _chainId is not checked against block.chainid (see FINDINGS I-4).
    function test_initialize_acceptsForeignChainId() public {
        bytes memory d =
            abi.encodeCall(BioRigCoreV5.initialize, (admin, address(registry), accountImpl, 999_999, bufferPool, address(0)));
        BioRigCoreV5 c = BioRigCoreV5(address(new ERC1967Proxy(address(impl), d)));
        assertEq(c.chainId(), 999_999);
        assertTrue(block.chainid != 999_999);
    }

    // ---- bare implementation (explicitly about the implementation contract) ----

    function test_implementation_cannotBeInitialized() public {
        vm.expectRevert(Initializable.InvalidInitialization.selector);
        impl.initialize(admin, address(registry), accountImpl, block.chainid, bufferPool, address(0));
    }

    function test_implementation_hasNoAdminAndIsUnusable() public {
        assertFalse(impl.hasRole(DEFAULT_ADMIN_ROLE, admin));
        assertEq(impl.erc6551Registry(), address(0));
        vm.prank(verifier);
        vm.expectRevert(_unauthorized(verifier, VERIFIER_ROLE));
        impl.mintTree(alice, N1, 1, 1);
    }

    function test_implementation_initializersDisabled() public view {
        // Initializable namespaced storage (ERC-7201): _initialized == type(uint64).max
        bytes32 slot = 0xf0c57e16840df040f15088dc2f81fe391c3923bec73e23a9662efc9c229c6a00;
        assertEq(uint64(uint256(vm.load(address(impl), slot))), type(uint64).max);
        assertEq(uint64(uint256(vm.load(address(core), slot))), 1);
    }
}
