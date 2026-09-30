// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

import {IERC6551Account} from "../../src/BioRigCoreV5.sol";

/// @notice Minimal reference-style ERC-6551 account implementation. Deployed once and used as
/// the delegate of every ERC-1167 account the registry creates. Like the reference account it
/// keeps no binding in storage: the registry appends abi.encode(salt, chainId, tokenContract,
/// tokenId) to each proxy's runtime code, and token() reads the last three words of that footer.
contract TokenBoundAccount is IERC6551Account {
    /// runtime layout: 10-byte header + 20-byte implementation + 15-byte tail = 0x2d,
    /// then salt (0x2d..0x4d), then chainId, tokenContract, tokenId (0x4d..0xad)
    uint256 private constant _BINDING_OFFSET = 0x4d;

    receive() external payable {}

    function token() public view returns (uint256, address, uint256) {
        bytes memory footer = new bytes(0x60);
        assembly {
            extcodecopy(address(), add(footer, 0x20), _BINDING_OFFSET, 0x60)
        }
        return abi.decode(footer, (uint256, address, uint256));
    }

    function supportsInterface(bytes4 interfaceId) external pure returns (bool) {
        return interfaceId == 0x6faff5f1 // IERC6551Account
            || interfaceId == 0x01ffc9a7; // IERC165
    }
}

/// @notice Claims IERC6551Account support but has no token() function.
contract NoTokenAccount {
    function supportsInterface(bytes4) external pure returns (bool) {
        return true;
    }
}

/// @notice Returns a correct-looking binding from token() but does not report ERC-6551 support.
contract NoErc165Account {
    uint256 internal immutable cid;
    address internal immutable tc;
    uint256 internal immutable tid;

    constructor(uint256 _cid, address _tc, uint256 _tid) {
        cid = _cid;
        tc = _tc;
        tid = _tid;
    }

    function token() external view returns (uint256, address, uint256) {
        return (cid, tc, tid);
    }
}

/// @notice Residual-trust demonstrator: an attacker-controlled contract that is NOT a registry
/// account at all, yet reports ERC-6551 support and echoes whatever binding it was built with.
contract LyingAccount is NoErc165Account {
    constructor(uint256 _cid, address _tc, uint256 _tid) NoErc165Account(_cid, _tc, _tid) {}

    function supportsInterface(bytes4) external pure returns (bool) {
        return true;
    }
}
