// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

import {console} from "forge-std/Script.sol";
import {IERC165} from "@openzeppelin/contracts/utils/introspection/IERC165.sol";
import {DeployBase} from "./DeployCommon.sol";
import {BioRigCoreV5} from "../src/BioRigCoreV5.sol";
import {ERC6551Account} from "../src/vendor/ERC6551Account.sol";

/// @notice The single orchestrated command: on a chain that has neither an ERC-6551 registry nor a reference
/// account, this deploys all three in one broadcast, in dependency order.
///
///   1. the EIP-6551 registry at its canonical address, through Nick's CREATE2 factory (skipped if already there);
///   2. the ERC-6551 reference account implementation;
///   3. BioRigCoreV5's implementation and an ERC1967Proxy initialised in the proxy's own constructor;
///   4. VERIFIER_ROLE granted to the admin, since initialize grants only DEFAULT_ADMIN_ROLE and UPGRADER_ROLE and
///      minting is otherwise impossible.
///
/// The registry and account addresses are fed straight into initialize from the deployments themselves, so no
/// environment value can point the contract at a different registry than the one this run created.
///
/// Env: PRIVATE_KEY, ADMIN, BUFFER_POOL, URI_GENERATOR, CHAIN_ID. Nothing is chain-specific beyond those values.
contract DeployAll is DeployBase {
    function run()
        external
        returns (address registry, address accountImplementation, address implementation, BioRigCoreV5 core)
    {
        Config memory cfg = _loadBaseConfig();
        _preflightBase(cfg);

        vm.startBroadcast(cfg.deployerKey);

        registry = _deployCanonicalRegistry();

        accountImplementation = address(new ERC6551Account());
        require(
            IERC165(accountImplementation).supportsInterface(0x6faff5f1),
            "account implementation does not advertise IERC6551Account (0x6faff5f1)"
        );

        cfg.registry = registry;
        cfg.accountImplementation = accountImplementation;
        (core, implementation) = _deployCore(cfg);

        vm.stopBroadcast();

        _registrySmokeTest(registry);
        _readBack(cfg, core, implementation);
        _report(cfg, registry, accountImplementation, implementation, core);
    }
}
