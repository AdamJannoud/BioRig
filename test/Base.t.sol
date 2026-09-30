// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

import {Test} from "forge-std/Test.sol";
import {ERC1967Proxy} from "@openzeppelin/contracts/proxy/ERC1967/ERC1967Proxy.sol";
import {IAccessControl} from "@openzeppelin/contracts/access/IAccessControl.sol";
import {PausableUpgradeable} from "@openzeppelin/contracts-upgradeable/utils/PausableUpgradeable.sol";
import {BioRigCoreV5} from "../src/BioRigCoreV5.sol";
import {ERC6551RegistryMock} from "./mocks/Registries.sol";
import {URIGeneratorMock} from "./mocks/Misc.sol";
import {TokenBoundAccount} from "./mocks/TokenBoundAccount.sol";

/// @notice Shared fixture. The target is always deployed behind a real ERC1967Proxy
/// and initialized through the proxy, exactly like production.
abstract contract BaseTest is Test {
    BioRigCoreV5 internal impl;
    BioRigCoreV5 internal core; // proxy, typed as V5
    ERC6551RegistryMock internal registry;
    URIGeneratorMock internal generator;

    address internal admin = makeAddr("admin");
    address internal verifier = makeAddr("verifier");
    address internal upgrader; // == admin, granted in initialize
    address internal stranger = makeAddr("stranger");
    address internal planter = makeAddr("planter");
    address internal alice = makeAddr("alice");
    address internal bob = makeAddr("bob");
    /// Real ERC-6551 account implementation (deployed in setUp). mintTree validates the
    /// registry's returned account by calling it, so the ERC-1167 proxies need live code behind them.
    address internal accountImpl;
    address internal bufferPool = makeAddr("bufferPool");

    bytes32 internal VERIFIER_ROLE;
    bytes32 internal UPGRADER_ROLE;
    bytes32 internal constant DEFAULT_ADMIN_ROLE = 0x00;

    bytes32 internal constant N1 = keccak256("plot-1");
    bytes32 internal constant N2 = keccak256("plot-2");
    bytes32 internal constant N3 = keccak256("plot-3");

    event TreeMinted(uint256 indexed tokenId, address indexed tba, bytes32 indexed spatialNullifier);
    event GrowthUpdated(uint256 indexed tokenId, uint96 newDBH, uint96 newBiomass);
    event TreeMortalityReported(uint256 indexed tokenId, bytes32 releasedNullifier, address tba);
    event URIGeneratorUpdated(address indexed oldGenerator, address indexed newGenerator);
    event BufferPoolUpdated(address indexed oldPool, address indexed newPool);
    event Transfer(address indexed from, address indexed to, uint256 indexed tokenId);

    function setUp() public virtual {
        vm.warp(1_700_000_000);
        accountImpl = address(new TokenBoundAccount());
        registry = new ERC6551RegistryMock();
        generator = new URIGeneratorMock();
        impl = new BioRigCoreV5();
        core = _deployProxy(address(registry), address(generator));
        VERIFIER_ROLE = core.VERIFIER_ROLE();
        UPGRADER_ROLE = core.UPGRADER_ROLE();
        upgrader = admin;
        vm.prank(admin);
        core.grantRole(VERIFIER_ROLE, verifier);
    }

    function _deployProxy(address reg, address gen) internal returns (BioRigCoreV5) {
        bytes memory init = abi.encodeCall(
            BioRigCoreV5.initialize, (admin, reg, accountImpl, block.chainid, bufferPool, gen)
        );
        return BioRigCoreV5(address(new ERC1967Proxy(address(impl), init)));
    }

    /// @dev Fresh proxy wired to an arbitrary registry, with `verifier` granted VERIFIER_ROLE.
    function _deployWithRegistry(address reg) internal returns (BioRigCoreV5 c) {
        c = _deployProxy(reg, address(generator));
        vm.startPrank(admin);
        c.grantRole(VERIFIER_ROLE, verifier);
        vm.stopPrank();
    }

    function _mint(address to, bytes32 nullifier) internal returns (uint256) {
        return _mint(to, nullifier, 10, 20);
    }

    function _mint(address to, bytes32 nullifier, uint96 dbh, uint96 biomass) internal returns (uint256) {
        vm.prank(verifier);
        return core.mintTree(to, nullifier, dbh, biomass);
    }

    function _salt(uint256 tokenId, address to, bytes32 nullifier) internal pure returns (bytes32) {
        return keccak256(abi.encodePacked(tokenId, to, nullifier));
    }

    function _expectedTba(uint256 tokenId, address to, bytes32 nullifier) internal view returns (address) {
        return registry.account(accountImpl, _salt(tokenId, to, nullifier), block.chainid, address(core), tokenId);
    }

    function _unauthorized(address who, bytes32 role) internal pure returns (bytes memory) {
        return abi.encodeWithSelector(IAccessControl.AccessControlUnauthorizedAccount.selector, who, role);
    }

    function _enforcedPause() internal pure returns (bytes memory) {
        return abi.encodeWithSelector(PausableUpgradeable.EnforcedPause.selector);
    }
}
