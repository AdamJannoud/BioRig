// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

import {BioRigCoreV5} from "../../src/BioRigCoreV5.sol";

/// @notice Successor implementation. Inherits V5 unchanged and APPENDS one state
/// variable after V5's last slot (_baseTokenURI, slot 8), so it lands in slot 9. It was slot 8
/// until I-6 appended _baseTokenURI to V5 at slot 8; every successor's appended state shifts by one.
contract BioRigCoreV6 is BioRigCoreV5 {
    uint256 public v6Marker;

    function initializeV6(uint256 marker) external reinitializer(2) onlyRole(UPGRADER_ROLE) {
        v6Marker = marker;
    }

    function version() external pure returns (string memory) {
        return "6";
    }

    function nextTokenIdV6() external view returns (uint256) {
        // reads V5's private slot 0 through assembly to prove it was not shifted
        uint256 v;
        assembly {
            v := sload(0)
        }
        return v;
    }
}
