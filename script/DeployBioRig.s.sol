// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

import {DeployBase} from "./DeployCommon.sol";
import {BioRigCoreV5} from "../src/BioRigCoreV5.sol";

/// @notice Deploys the BioRigCoreV5 implementation and an ERC1967Proxy initialised in its own constructor (so the
/// proxy is never live-but-uninitialised), grants VERIFIER_ROLE to the admin, then reads the state back through the
/// proxy. BioRigCoreV5 is UUPS, so there is no ProxyAdmin.
///
/// The ERC-6551 registry and account implementation must already exist at the addresses in ERC6551_REGISTRY and
/// ERC6551_IMPLEMENTATION; on a chain that has neither, script/DeployAll.s.sol deploys all of it in one command.
/// Every input comes from the environment; see .env.example and DEPLOY.md.
contract DeployBioRig is DeployBase {
    function run() external returns (BioRigCoreV5 core, address implementation) {
        Config memory cfg = _loadDeployConfig();
        _preflightBase(cfg);
        _preflightExternalCode(cfg);

        vm.startBroadcast(cfg.deployerKey);
        (core, implementation) = _deployCore(cfg);
        vm.stopBroadcast();

        _readBack(cfg, core, implementation);
        _report(cfg, cfg.registry, cfg.accountImplementation, implementation, core);
    }
}
