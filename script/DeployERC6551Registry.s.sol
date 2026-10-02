// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

import {console} from "forge-std/Script.sol";
import {DeployBase} from "./DeployCommon.sol";
import {ERC6551Registry} from "../src/vendor/ERC6551Registry.sol";

/// @notice OPTIONAL. Deploys an ERC-6551 registry on chains that lack one, and grants nothing else. DeployAll.s.sol
/// covers this case as part of the full deployment; use this script when you want the registry on its own.
///
/// ERC6551_REGISTRY_MODE=canonical (default): sends the EIP-6551 canonical creation code through Nick's factory with
/// the canonical salt, so the registry lands at the same address as on every other chain
/// (0x000000006551c19487814612e58FE06813775758). No-op if that address already has code.
///
/// ERC6551_REGISTRY_MODE=source: deploys src/vendor/ERC6551Registry.sol as compiled by this repo, at a fresh
/// CREATE address. Use only where Nick's factory is absent; you then set ERC6551_REGISTRY to the printed address.
contract DeployERC6551Registry is DeployBase {
    function run() external returns (address registry) {
        uint256 deployerKey = _deployerKey();
        _checkChainId(vm.envUint("CHAIN_ID"));
        string memory mode = vm.envOr("ERC6551_REGISTRY_MODE", string("canonical"));

        vm.startBroadcast(deployerKey);
        if (keccak256(bytes(mode)) == keccak256("canonical")) {
            registry = _deployCanonicalRegistry();
        } else if (keccak256(bytes(mode)) == keccak256("source")) {
            registry = address(new ERC6551Registry());
        } else {
            vm.stopBroadcast();
            revert(string.concat("ERC6551_REGISTRY_MODE must be 'canonical' or 'source', got '", mode, "'"));
        }
        vm.stopBroadcast();

        _registrySmokeTest(registry);
        console.log("");
        console.log("=== ERC-6551 registry ===");
        console.log("chain id:", block.chainid);
        console.log("mode:    ", mode);
        _logAddress("registry:", registry);
        console.log("code size (bytes):", registry.code.length);
        console.log("Set ERC6551_REGISTRY to this address before running DeployBioRig.");
    }
}
