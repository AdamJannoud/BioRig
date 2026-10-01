// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

import {console} from "forge-std/Script.sol";
import {DeployBase} from "./DeployCommon.sol";
import {BioRigCoreV5} from "../src/BioRigCoreV5.sol";

/// @dev The two Safe views the preflight needs; present on every Safe since v1.0.
interface ISafeOwners {
    function getThreshold() external view returns (uint256);
    function getOwners() external view returns (address[] memory);
}

/// @notice The role handover run after DeployAll's broadcast. DeployAll has to deploy with ADMIN == deployer, which
/// leaves a hot key holding DEFAULT_ADMIN_ROLE, UPGRADER_ROLE and VERIFIER_ROLE. This moves admin and upgrade powers
/// to a Safe, and leaves VERIFIER_ROLE (minting) wherever VERIFIER_ADDRESS points. Two modes, chosen by that value:
///
///   A. a dedicated verifier key - VERIFIER_ADDRESS is an address other than the deployer:
///   1. UPGRADER_ROLE, then DEFAULT_ADMIN_ROLE, granted to NEW_ADMIN (the Safe);
///   2. VERIFIER_ROLE granted to VERIFIER_ADDRESS, a key that is neither the deployer nor the Safe;
///   3. the deployer renounces VERIFIER_ROLE, then UPGRADER_ROLE, then DEFAULT_ADMIN_ROLE last, so until the final
///      transaction the deployer can still repair a mistake in steps 1 and 2.
///
///   B. minting stays on the deployer - VERIFIER_ADDRESS is the deployer itself. VERIFIER_ROLE is left where it is
///      and the deployer renounces only UPGRADER_ROLE and then DEFAULT_ADMIN_ROLE, so it keeps mint, update and
///      reportMortality and loses pause, upgrade and role administration. The Safe can rotate the verifier later.
///
/// Every transition is read back with hasRole before the next one, and the end state is asserted in full for the mode
/// that ran: the deployer holds no admin and no upgrade, the Safe holds admin and upgrade only, and the verifier
/// address holds VERIFIER_ROLE only.
///
/// Env: PRIVATE_KEY (the deployer), CHAIN_ID, PROXY_ADDRESS, NEW_ADMIN, VERIFIER_ADDRESS (which may be the deployer,
/// mode B). The chain is refused unless CHAIN_ID, the RPC's eth_chainId and the chain id the proxy was initialised
/// with all agree.
contract HardenMainnetAdmin is DeployBase {
    struct Handover {
        uint256 deployerKey;
        address deployer;
        uint256 chainId;
        BioRigCoreV5 core;
        address newAdmin;
        address verifier;
    }

    function run() external {
        Handover memory h = _loadHandoverConfig();
        _preflightHandover(h);

        bytes32 adminRole = h.core.DEFAULT_ADMIN_ROLE();
        bytes32 upgraderRole = h.core.UPGRADER_ROLE();
        bytes32 verifierRole = h.core.VERIFIER_ROLE();

        bool mintingStaysOnDeployer = _mintingStaysOnDeployer(h);

        vm.startBroadcast(h.deployerKey);

        _grant(h.core, upgraderRole, "UPGRADER_ROLE", h.newAdmin, "NEW_ADMIN");
        _grant(h.core, adminRole, "DEFAULT_ADMIN_ROLE", h.newAdmin, "NEW_ADMIN");

        // Mode A moves minting to a dedicated key and strips the deployer of it; mode B leaves both alone. The Safe
        // holds DEFAULT_ADMIN_ROLE before either renounce below, so the proxy is never left without an administrator.
        if (!mintingStaysOnDeployer) {
            _grant(h.core, verifierRole, "VERIFIER_ROLE", h.verifier, "VERIFIER_ADDRESS");
            _renounce(h.core, verifierRole, "VERIFIER_ROLE", h.deployer);
        }

        _renounce(h.core, upgraderRole, "UPGRADER_ROLE", h.deployer);
        _renounce(h.core, adminRole, "DEFAULT_ADMIN_ROLE", h.deployer);

        vm.stopBroadcast();

        _assertHandedOver(h);
        _reportHandover(h);
    }

    // ---------------------------------------------------------------- configuration

    function _loadHandoverConfig() internal view returns (Handover memory h) {
        h.deployerKey = vm.envUint("PRIVATE_KEY");
        h.deployer = vm.addr(h.deployerKey);
        h.chainId = vm.envUint("CHAIN_ID");
        h.core = BioRigCoreV5(vm.envAddress("PROXY_ADDRESS"));
        h.newAdmin = vm.envAddress("NEW_ADMIN");
        h.verifier = vm.envAddress("VERIFIER_ADDRESS");
    }

    // -------------------------------------------------------------------- preflight

    /// @dev Mode B: VERIFIER_ADDRESS names the deployer, so minting deliberately stays on the hot key.
    function _mintingStaysOnDeployer(Handover memory h) internal pure returns (bool) {
        return h.verifier == h.deployer;
    }

    /// @dev Reverts before anything is broadcast if any assumption the handover rests on is false.
    function _preflightHandover(Handover memory h) internal view {
        _checkChainId(h.chainId);
        _requireCode(address(h.core), "PROXY_ADDRESS", "point it at the ERC1967Proxy DeployAll printed");
        require(
            h.core.chainId() == block.chainid,
            string.concat(
                "PROXY_ADDRESS was initialised for chain ",
                vm.toString(h.core.chainId()),
                ", not this chain (",
                vm.toString(block.chainid),
                ")"
            )
        );
        require(
            h.core.hasRole(h.core.DEFAULT_ADMIN_ROLE(), h.deployer),
            string.concat(
                "deployer ",
                vm.toString(h.deployer),
                " does not hold DEFAULT_ADMIN_ROLE on this proxy; nothing to hand over (already run, or wrong PRIVATE_KEY)"
            )
        );

        require(h.newAdmin != address(0), "NEW_ADMIN is the zero address");
        require(h.newAdmin != h.deployer, "NEW_ADMIN is the deployer; the point is to take admin off the hot key");
        _requireSafe(h);

        require(h.verifier != address(0), "VERIFIER_ADDRESS is the zero address");
        require(h.verifier != h.newAdmin, "VERIFIER_ADDRESS is NEW_ADMIN; the verifier key must not be the admin");
        if (_mintingStaysOnDeployer(h)) {
            // Mode B. The deployer is the verifier, so nothing grants it and nothing revokes it: if the role were
            // missing here the handover would finish with nobody able to mint. The deployer does hold admin and
            // upgrade at this point - the handover strips those below - so the check that a *separate* verifier key
            // must not already be privileged does not apply to it, and is deliberately not run in this mode.
            require(
                h.core.hasRole(h.core.VERIFIER_ROLE(), h.deployer),
                "VERIFIER_ADDRESS is the deployer, but the deployer does not hold VERIFIER_ROLE; grant it first"
            );
            console.log("VERIFIER_ADDRESS is the deployer: minting stays on the deployer key (mode B)");
        } else {
            require(
                !h.core.hasRole(h.core.DEFAULT_ADMIN_ROLE(), h.verifier)
                    && !h.core.hasRole(h.core.UPGRADER_ROLE(), h.verifier),
                "VERIFIER_ADDRESS already holds DEFAULT_ADMIN_ROLE or UPGRADER_ROLE; revoke that first"
            );
        }

        console.log("Chain id:              ", block.chainid);
        console.log("Deployer (hands over): ", h.deployer);
        _logAddress("BioRig proxy:          ", address(h.core));
        _logAddress("NEW_ADMIN (Safe):      ", h.newAdmin);
        _logAddress("VERIFIER_ADDRESS:      ", h.verifier);
    }

    /// @dev NEW_ADMIN must be a deployed Safe with a real threshold, and the deployer must not be one of its owners:
    /// a Safe the hot key can sign for alone would hand admin straight back to it.
    function _requireSafe(Handover memory h) internal view {
        _requireCode(h.newAdmin, "NEW_ADMIN", "deploy the Safe first (app.safe.global, Celo)");
        uint256 threshold;
        address[] memory owners;
        try ISafeOwners(h.newAdmin).getThreshold() returns (uint256 t) {
            threshold = t;
        } catch {
            revert("NEW_ADMIN does not answer getThreshold(); it is not a Safe");
        }
        try ISafeOwners(h.newAdmin).getOwners() returns (address[] memory o) {
            owners = o;
        } catch {
            revert("NEW_ADMIN does not answer getOwners(); it is not a Safe");
        }
        require(threshold != 0 && owners.length >= threshold, "NEW_ADMIN Safe has no usable threshold");
        for (uint256 i; i < owners.length; ++i) {
            require(owners[i] != h.deployer, "the deployer is an owner of the NEW_ADMIN Safe; use a Safe it cannot sign for");
        }
        console.log("NEW_ADMIN Safe threshold:", threshold);
        console.log("NEW_ADMIN Safe owners:   ", owners.length);
    }

    // -------------------------------------------------------------------- transitions

    /// @dev grantRole is a no-op for a holder, so a re-run after a partial broadcast does not send it twice.
    function _grant(BioRigCoreV5 core, bytes32 role, string memory roleName, address to, string memory toName)
        internal
    {
        if (!core.hasRole(role, to)) core.grantRole(role, to);
        require(core.hasRole(role, to), string.concat("read-back: ", toName, " lacks ", roleName, " after grantRole"));
        console.log(string.concat("read-back hasRole(", roleName, ", ", toName, "): true"));
    }

    function _renounce(BioRigCoreV5 core, bytes32 role, string memory roleName, address deployer) internal {
        core.renounceRole(role, deployer);
        require(!core.hasRole(role, deployer), string.concat("read-back: deployer still holds ", roleName));
        console.log(string.concat("read-back hasRole(", roleName, ", deployer): false"));
    }

    // ------------------------------------------------------------------- assertions

    function _assertHandedOver(Handover memory h) internal view {
        BioRigCoreV5 core = h.core;
        bytes32 adminRole = core.DEFAULT_ADMIN_ROLE();
        bytes32 upgraderRole = core.UPGRADER_ROLE();
        bytes32 verifierRole = core.VERIFIER_ROLE();

        require(!core.hasRole(adminRole, h.deployer), "end state: deployer holds DEFAULT_ADMIN_ROLE");
        require(!core.hasRole(upgraderRole, h.deployer), "end state: deployer holds UPGRADER_ROLE");
        if (_mintingStaysOnDeployer(h)) {
            require(core.hasRole(verifierRole, h.deployer), "end state: deployer lost VERIFIER_ROLE; nobody can mint");
        } else {
            require(!core.hasRole(verifierRole, h.deployer), "end state: deployer holds VERIFIER_ROLE");
        }

        require(core.hasRole(adminRole, h.newAdmin), "end state: NEW_ADMIN lacks DEFAULT_ADMIN_ROLE");
        require(core.hasRole(upgraderRole, h.newAdmin), "end state: NEW_ADMIN lacks UPGRADER_ROLE");
        require(!core.hasRole(verifierRole, h.newAdmin), "end state: NEW_ADMIN holds VERIFIER_ROLE");

        require(core.hasRole(verifierRole, h.verifier), "end state: VERIFIER_ADDRESS lacks VERIFIER_ROLE");
        require(!core.hasRole(adminRole, h.verifier), "end state: VERIFIER_ADDRESS holds DEFAULT_ADMIN_ROLE");
        require(!core.hasRole(upgraderRole, h.verifier), "end state: VERIFIER_ADDRESS holds UPGRADER_ROLE");

        // Every role is still administered by DEFAULT_ADMIN_ROLE, so the Safe can rotate the verifier later.
        require(core.getRoleAdmin(verifierRole) == adminRole, "end state: VERIFIER_ROLE admin changed");
        require(core.getRoleAdmin(upgraderRole) == adminRole, "end state: UPGRADER_ROLE admin changed");
    }

    function _reportHandover(Handover memory h) internal view {
        BioRigCoreV5 core = h.core;
        console.log("");
        console.log("=== BioRig role handover ===");
        console.log("chain id:", block.chainid);
        console.log("proxy:   ", address(core));
        console.log("deployer  ", h.deployer);
        console.log("  DEFAULT_ADMIN_ROLE:", core.hasRole(core.DEFAULT_ADMIN_ROLE(), h.deployer));
        console.log("  UPGRADER_ROLE:     ", core.hasRole(core.UPGRADER_ROLE(), h.deployer));
        console.log("  VERIFIER_ROLE:     ", core.hasRole(core.VERIFIER_ROLE(), h.deployer));
        console.log("NEW_ADMIN ", h.newAdmin);
        console.log("  DEFAULT_ADMIN_ROLE:", core.hasRole(core.DEFAULT_ADMIN_ROLE(), h.newAdmin));
        console.log("  UPGRADER_ROLE:     ", core.hasRole(core.UPGRADER_ROLE(), h.newAdmin));
        console.log("  VERIFIER_ROLE:     ", core.hasRole(core.VERIFIER_ROLE(), h.newAdmin));
        console.log("VERIFIER  ", h.verifier);
        console.log("  DEFAULT_ADMIN_ROLE:", core.hasRole(core.DEFAULT_ADMIN_ROLE(), h.verifier));
        console.log("  UPGRADER_ROLE:     ", core.hasRole(core.UPGRADER_ROLE(), h.verifier));
        console.log("  VERIFIER_ROLE:     ", core.hasRole(core.VERIFIER_ROLE(), h.verifier));
        console.log(
            _mintingStaysOnDeployer(h)
                ? "The deployer key holds VERIFIER_ROLE only: it can mint, update and report mortality, and cannot pause, upgrade or change roles."
                : "The deployer key now controls nothing on this proxy."
        );
    }
}
