// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

import {Script, console} from "forge-std/Script.sol";

/// @dev The two Safe views the ownership walk needs; present on every Safe since v1.0.
interface ISafeOwners {
    function getThreshold() external view returns (uint256);
    function getOwners() external view returns (address[] memory);
}

/// @notice The deployer-ownership walk shared by the scripts that put a Safe, or a Safe owner, between the deployer hot
/// key and a privilege: HardenMainnetAdmin (NEW_ADMIN, the Safe that takes admin) and SafeOwnerSwap (NEW_OWNER, the
/// address that takes over a Safe). Both need the same answer to the same question: can the deployer still sign for
/// this address, directly or through a contract owner at any depth? The caller passes the deployer and the label the
/// refusals name, so one walk serves every variable without each script keeping its own copy.
abstract contract SafeOwnershipGuard is Script {
    /// @dev How many contract-ownership hops the walk follows before refusing. Three covers a Safe owned by a Safe
    /// owned by a Safe; past that the setup is beyond what a one-shot script should be second-guessing.
    uint256 internal constant MAX_OWNERSHIP_DEPTH = 3;

    /// @dev Walks one branch of the `label` Safe's ownership and refuses if `deployer` turns up in it. An EOA ends the
    /// walk: the deployer cannot sign for it. A contract is walked while it answers getOwners() - a Safe, at any depth.
    /// A contract that does not answer cannot be verified, so it is refused unless ALLOW_UNINSPECTED_OWNER=true records
    /// that a human checked it. That override is not a formality: an owner address can legitimately carry code, an
    /// EIP-7702 delegation for instance, and Celo mainnet already has delegated accounts among the well-known test
    /// keys. `level` counts the hops from the `label` Safe, so the refusal says which trap was hit.
    function _requireNotDeployerControlled(
        address deployer,
        string memory label,
        address candidate,
        uint256 depth,
        uint256 level
    ) internal view {
        if (candidate == deployer) {
            if (level == 1) {
                revert(string.concat("the deployer is an owner of the ", label, " Safe; use a Safe it cannot sign for"));
            }
            revert(
                string.concat("an owner of the ", label, " Safe is owned by the deployer; use a Safe it cannot sign for")
            );
        }
        if (candidate.code.length == 0) return;

        require(depth > 0, string.concat("the ", label, " Safe's owners are nested deeper than this script verifies"));

        (bool read, address[] memory owners) = _probeOwners(candidate);
        if (!read) {
            require(
                vm.envOr("ALLOW_UNINSPECTED_OWNER", false),
                string.concat(
                    "an owner of the ",
                    label,
                    " Safe is a contract this script cannot inspect (",
                    vm.toString(candidate),
                    "); admin must sit behind an address the deployer cannot sign for"
                )
            );
            console.log("WARNING: uninspected contract owner accepted by ALLOW_UNINSPECTED_OWNER:", candidate);
            return;
        }
        require(owners.length != 0, string.concat("a contract owner of the ", label, " Safe reports no owners"));
        for (uint256 i; i < owners.length; ++i) {
            _requireNotDeployerControlled(deployer, label, owners[i], depth - 1, level + 1);
        }
    }

    /// @dev These read a Safe through a low-level staticcall on purpose. A try/catch catches a call that reverts, but
    /// an account that answers with no data at all fails while its return value is being DECODED - which is not caught,
    /// so it escapes as a bare EvmError with nothing to act on. These return false instead, and the caller explains.
    function _probeOwners(address account) internal view returns (bool, address[] memory) {
        (bool ok, bytes memory data) = account.staticcall(abi.encodeWithSelector(ISafeOwners.getOwners.selector));
        if (!ok || data.length < 64) return (false, new address[](0));
        return (true, abi.decode(data, (address[])));
    }

    function _probeThreshold(address account) internal view returns (bool, uint256) {
        (bool ok, bytes memory data) = account.staticcall(abi.encodeWithSelector(ISafeOwners.getThreshold.selector));
        if (!ok || data.length < 32) return (false, 0);
        return (true, abi.decode(data, (uint256)));
    }
}
