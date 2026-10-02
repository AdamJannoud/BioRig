// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

import {console} from "forge-std/Script.sol";
import {PrivateKeyEnv} from "./PrivateKeyEnv.sol";
import {ERC6551Account} from "../src/vendor/ERC6551Account.sol";

/// @notice OPTIONAL. Deploys the EIP-6551 reference *example* account (src/vendor/ERC6551Account.sol) for use as
/// ERC6551_IMPLEMENTATION on chains with no account implementation. It is unaudited; prefer an audited
/// implementation (e.g. Tokenbound's) wherever one is deployed.
contract DeployERC6551Account is PrivateKeyEnv {
    function run() external returns (address account) {
        uint256 deployerKey = _deployerKey();
        uint256 chainId = vm.envUint("CHAIN_ID");
        require(
            chainId == block.chainid,
            string.concat("CHAIN_ID mismatch: env ", vm.toString(chainId), " vs RPC ", vm.toString(block.chainid))
        );

        vm.startBroadcast(deployerKey);
        account = address(new ERC6551Account());
        vm.stopBroadcast();

        // BioRigCoreV5._validateTba requires ERC-165 support for the ERC-6551 account id.
        require(ERC6551Account(payable(account)).supportsInterface(0x6faff5f1), "account lacks IERC6551Account");
        console.log("");
        console.log("=== ERC-6551 account implementation ===");
        console.log("chain id:       ", block.chainid);
        console.log("implementation: ", account);
        console.log("Set ERC6551_IMPLEMENTATION to this address before running DeployBioRig.");
    }
}
