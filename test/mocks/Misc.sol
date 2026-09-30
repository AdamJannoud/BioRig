// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

import {Strings} from "@openzeppelin/contracts/utils/Strings.sol";
import {IERC721Receiver} from "@openzeppelin/contracts/token/ERC721/IERC721Receiver.sol";
import {ITokenURIGenerator} from "../../src/BioRigCoreV5.sol";

contract URIGeneratorMock is ITokenURIGenerator {
    function generateURI(uint256 tokenId, uint96 dbh, uint96 biomass, bool isAlive)
        external
        pure
        returns (string memory)
    {
        return string.concat(
            "tree:",
            Strings.toString(tokenId),
            ":",
            Strings.toString(dbh),
            ":",
            Strings.toString(biomass),
            ":",
            isAlive ? "alive" : "dead"
        );
    }
}

contract RevertingURIGenerator is ITokenURIGenerator {
    error GeneratorDown();

    function generateURI(uint256, uint96, uint96, bool) external pure returns (string memory) {
        revert GeneratorDown();
    }
}

/// @notice Burns every unit of gas it is given (unbounded loop), so the call always ends out-of-gas.
contract GasBurningURIGenerator is ITokenURIGenerator {
    uint256 public sink;

    function generateURI(uint256, uint96, uint96, bool) external view returns (string memory) {
        uint256 x = sink;
        while (true) {
            x = uint256(keccak256(abi.encode(x)));
        }
        return "";
    }
}

/// @notice Returns successfully, but with returndata that does not ABI-decode as a string
/// (a string header claiming 1000 bytes, followed by none).
contract MalformedURIGenerator {
    fallback() external {
        assembly {
            mstore(0x00, 0x20)
            mstore(0x20, 1000)
            return(0x00, 0x40)
        }
    }
}

/// @notice Contract planter with no onERC721Received: must be rejected by _safeMint/safeTransferFrom.
contract RejectingPlanter {}

/// @notice Contract planter that implements onERC721Received but returns the wrong selector.
contract WrongSelectorPlanter is IERC721Receiver {
    function onERC721Received(address, address, uint256, bytes calldata) external pure returns (bytes4) {
        return 0xdeadbeef;
    }
}

contract AcceptingPlanter is IERC721Receiver {
    uint256 public received;
    uint256 public lastTokenId;

    function onERC721Received(address, address, uint256 tokenId, bytes calldata) external returns (bytes4) {
        received++;
        lastTokenId = tokenId;
        return IERC721Receiver.onERC721Received.selector;
    }
}

interface IGrowthTarget {
    function updateTreeGrowth(uint256, uint96, uint96) external;
    function reportMortality(uint256) external;
}

/// @notice A planter that ALSO holds VERIFIER_ROLE and calls back into the core
/// from onERC721Received (i.e. mid-mintTree). Used to probe hypotheses 4 and 6.
contract VerifierPlanter is IERC721Receiver {
    IGrowthTarget public target;
    bool public killInCallback;

    constructor(address _target, bool _kill) {
        target = IGrowthTarget(_target);
        killInCallback = _kill;
    }

    function onERC721Received(address, address, uint256 tokenId, bytes calldata) external returns (bytes4) {
        if (killInCallback) target.reportMortality(tokenId);
        else target.updateTreeGrowth(tokenId, 500, 600);
        return IERC721Receiver.onERC721Received.selector;
    }
}

/// @notice Implementation without proxiableUUID: UUPS upgrade to it must fail.
contract NotUUPS {
    function hello() external pure returns (uint256) {
        return 42;
    }
}
