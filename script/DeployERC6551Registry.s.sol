// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

import {Script, console} from "forge-std/Script.sol";
import {ERC6551Registry} from "../src/vendor/ERC6551Registry.sol";

/// @notice OPTIONAL. Deploys an ERC-6551 registry on chains that lack one (Celo Sepolia, at the time of writing).
///
/// ERC6551_REGISTRY_MODE=canonical (default): sends the EIP-6551 canonical creation code through Nick's factory with
/// the canonical salt, so the registry lands at the same address as on every other chain
/// (0x000000006551c19487814612e58FE06813775758). No-op if that address already has code.
///
/// ERC6551_REGISTRY_MODE=source: deploys src/vendor/ERC6551Registry.sol as compiled by this repo, at a fresh
/// CREATE address. Use only where Nick's factory is absent; you then set ERC6551_REGISTRY to the printed address.
contract DeployERC6551Registry is Script {
    address internal constant NICKS_FACTORY = 0x4e59b44847b379578588920cA78FbF26c0B4956C;
    address internal constant CANONICAL_REGISTRY = 0x000000006551c19487814612e58FE06813775758;
    bytes32 internal constant CANONICAL_SALT = 0x0000000000000000000000000000000000000000fd8eb4e1dca713016c518e31;
    /// Copied from the deployment transaction in EIP-6551 (salt prefix removed). Its executable part is identical to
    /// src/vendor/ERC6551Registry.sol compiled with solc 0.8.17 / optimizer 200; only the CBOR metadata hash differs.
    bytes internal constant CANONICAL_INIT_CODE =
        hex"608060405234801561001057600080fd5b5061023b806100206000396000f3fe608060405234801561001057600080fd5b50600436106100365760003560e01c8063246a00211461003b5780638a54c52f1461006a575b600080fd5b61004e6100493660046101b7565b61007d565b6040516001600160a01b03909116815260200160405180910390f35b61004e6100783660046101b7565b6100e1565b600060806024608c376e5af43d82803e903d91602b57fd5bf3606c5285605d52733d60ad80600a3d3981f3363d3d373d3d3d363d7360495260ff60005360b76055206035523060601b60015284601552605560002060601b60601c60005260206000f35b600060806024608c376e5af43d82803e903d91602b57fd5bf3606c5285605d52733d60ad80600a3d3981f3363d3d373d3d3d363d7360495260ff60005360b76055206035523060601b600152846015526055600020803b61018b578560b760556000f580610157576320188a596000526004601cfd5b80606c52508284887f79f19b3655ee38b1ce526556b7731a20c8f218fbda4a3990b6cc4172fdf887226060606ca46020606cf35b8060601b60601c60005260206000f35b80356001600160a01b03811681146101b257600080fd5b919050565b600080600080600060a086880312156101cf57600080fd5b6101d88661019b565b945060208601359350604086013592506101f46060870161019b565b94979396509194608001359291505056fea2646970667358221220ea2fe53af507453c64dd7c1db05549fa47a298dfb825d6d11e1689856135f16764736f6c63430008110033";

    function run() external returns (address registry) {
        uint256 deployerKey = vm.envUint("PRIVATE_KEY");
        uint256 chainId = vm.envUint("CHAIN_ID");
        string memory mode = vm.envOr("ERC6551_REGISTRY_MODE", string("canonical"));
        require(
            chainId == block.chainid,
            string.concat("CHAIN_ID mismatch: env ", vm.toString(chainId), " vs RPC ", vm.toString(block.chainid))
        );

        if (keccak256(bytes(mode)) == keccak256("canonical")) {
            registry = _deployCanonical(deployerKey);
        } else if (keccak256(bytes(mode)) == keccak256("source")) {
            vm.startBroadcast(deployerKey);
            registry = address(new ERC6551Registry());
            vm.stopBroadcast();
        } else {
            revert(string.concat("ERC6551_REGISTRY_MODE must be 'canonical' or 'source', got '", mode, "'"));
        }

        _smokeTest(registry);
        console.log("");
        console.log("=== ERC-6551 registry ===");
        console.log("chain id:          ", block.chainid);
        console.log("mode:              ", mode);
        console.log("registry:          ", registry);
        console.log("code size (bytes): ", registry.code.length);
        console.log("Set ERC6551_REGISTRY to this address before running DeployBioRig.");
    }

    function _deployCanonical(uint256 deployerKey) internal returns (address) {
        require(
            vm.computeCreate2Address(CANONICAL_SALT, keccak256(CANONICAL_INIT_CODE), NICKS_FACTORY)
                == CANONICAL_REGISTRY,
            "canonical init code does not hash to the canonical registry address"
        );
        if (CANONICAL_REGISTRY.code.length != 0) {
            console.log("Canonical registry already deployed on this chain; nothing to do.");
            return CANONICAL_REGISTRY;
        }
        require(
            NICKS_FACTORY.code.length != 0,
            "Nick's factory (0x4e59b448...) has no code on this chain; rerun with ERC6551_REGISTRY_MODE=source"
        );

        vm.startBroadcast(deployerKey);
        (bool ok, bytes memory ret) = NICKS_FACTORY.call(abi.encodePacked(CANONICAL_SALT, CANONICAL_INIT_CODE));
        vm.stopBroadcast();

        require(ok && ret.length == 20 && address(bytes20(ret)) == CANONICAL_REGISTRY, "Nick's factory deploy failed");
        return CANONICAL_REGISTRY;
    }

    /// account() must agree with an independent CREATE2 computation over the EIP-6551 account bytecode layout.
    function _smokeTest(address registry) internal view {
        require(registry.code.length != 0, "registry has no code after deployment");
        address impl = address(0xBEbeBeBEbeBebeBeBEBEbebEBeBeBebeBeBebebe);
        address token = address(0xcfCFcfCfcFCFcFCfCfCFcFCfcfcfcfcfcfCfCfCf);
        bytes32 salt = bytes32(uint256(7));
        bytes memory accountCode = abi.encodePacked(
            hex"3d60ad80600a3d3981f3363d3d373d3d3d363d73",
            impl,
            hex"5af43d82803e903d91602b57fd5bf3",
            abi.encode(salt, block.chainid, token, uint256(123))
        );
        address expected = vm.computeCreate2Address(salt, keccak256(accountCode), registry);
        address got = ERC6551Registry(registry).account(impl, salt, block.chainid, token, 123);
        require(got == expected, "registry.account() disagrees with the EIP-6551 address derivation");
    }
}
