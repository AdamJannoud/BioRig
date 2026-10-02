// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

import {Script} from "forge-std/Script.sol";

/// @notice Reads the deployer key from the environment in either form the repository documents.
/// @dev forge's `vm.envUint` parses ONLY the `0x`-prefixed form. Handed the 64 bare hex digits the workspace secret
/// stores, it aborts inside the cheatcode with "missing hex prefix" before any script guard has run - and a script
/// that wraps its operations in `try`/`catch` then mis-reads that abort as one of its own refusals. That is exactly how
/// gate step 4b failed on 2 October 2026 (33 checks, both mainnet fork rehearsals) while the Python half of the same
/// gate, which accepts both forms, passed on the identical value.
///
/// The tolerance belongs here, where the value is consumed, not at each caller's boundary: `forge script` run by a
/// person against a hand-filled .env is a path no shell wrapper covers, and a new entry point cannot reintroduce the
/// trap while it inherits this. `dashboard/config.py validate_private_key` accepts the same two forms, so one copy of
/// the key serves every consumer in the repository.
abstract contract PrivateKeyEnv is Script {
    /// @dev `PRIVATE_KEY` as a uint256. Accepts `0x` + 64 hex digits, or the 64 digits bare.
    function _deployerKey() internal view returns (uint256) {
        return _parseDeployerKey(vm.envString("PRIVATE_KEY"));
    }

    /// @dev Separate from the read so the accepted forms are testable without an environment.
    function _parseDeployerKey(string memory raw) internal view returns (uint256) {
        bytes memory key = bytes(raw);
        require(
            key.length == 64 || key.length == 66,
            "PRIVATE_KEY: expected 0x plus 64 hex digits, or the 64 digits bare"
        );
        if (key.length == 66) {
            require(key[0] == 0x30 && (key[1] == 0x78 || key[1] == 0x58), "PRIVATE_KEY: a 66-character value must start with 0x");
        }
        bytes memory digits = new bytes(64);
        for (uint256 i = 0; i < 64; ++i) {
            digits[i] = key[key.length - 64 + i];
        }
        // A non-hex digit is the last way a value can be malformed; vm.parseUint reverts on one and names the value.
        return vm.parseUint(string.concat("0x", string(digits)));
    }
}
