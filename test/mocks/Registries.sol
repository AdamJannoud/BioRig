// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

import {IERC6551Registry} from "../../src/BioRigCoreV5.sol";

/// @notice Conforming ERC-6551 registry. Mirrors the reference registry (v0.3.x):
/// the account is an ERC-1167-style proxy whose init code carries
/// abi.encode(salt, chainId, tokenContract, tokenId) as a footer, deployed with
/// CREATE2 using `salt` directly. Idempotent: returns the existing account if deployed.
contract ERC6551RegistryMock is IERC6551Registry {
    event ERC6551AccountCreated(
        address account,
        address indexed implementation,
        bytes32 salt,
        uint256 chainId,
        address indexed tokenContract,
        uint256 indexed tokenId
    );

    function createAccount(
        address implementation,
        bytes32 salt,
        uint256 chainId,
        address tokenContract,
        uint256 tokenId
    ) external returns (address acct) {
        bytes memory code = accountInitCode(implementation, salt, chainId, tokenContract, tokenId);
        acct = account(implementation, salt, chainId, tokenContract, tokenId);
        if (acct.code.length != 0) return acct;
        emit ERC6551AccountCreated(acct, implementation, salt, chainId, tokenContract, tokenId);
        address deployed;
        assembly {
            deployed := create2(0, add(code, 0x20), mload(code), salt)
        }
        require(deployed == acct, "create2 failed");
    }

    function account(
        address implementation,
        bytes32 salt,
        uint256 chainId,
        address tokenContract,
        uint256 tokenId
    ) public view returns (address) {
        bytes32 h = keccak256(
            abi.encodePacked(
                bytes1(0xff),
                address(this),
                salt,
                keccak256(accountInitCode(implementation, salt, chainId, tokenContract, tokenId))
            )
        );
        return address(uint160(uint256(h)));
    }

    function accountInitCode(
        address implementation,
        bytes32 salt,
        uint256 chainId,
        address tokenContract,
        uint256 tokenId
    ) public pure returns (bytes memory) {
        return abi.encodePacked(
            hex"3d60ad80600a3d3981f3363d3d373d3d3d363d73",
            implementation,
            hex"5af43d82803e903d91602b57fd5bf3",
            abi.encode(salt, chainId, tokenContract, tokenId)
        );
    }
}

/// @notice Buggy registry: reports success but returns address(0).
contract ZeroRegistry is IERC6551Registry {
    function createAccount(address, bytes32, uint256, address, uint256) external pure returns (address) {
        return address(0);
    }
}

/// @notice Hostile/buggy registry: returns whatever address it was configured with,
/// regardless of the token it was asked to create an account for.
contract ArbitraryRegistry is IERC6551Registry {
    address public ret;

    constructor(address _ret) {
        ret = _ret;
    }

    function createAccount(address, bytes32, uint256, address, uint256) external view returns (address) {
        return ret;
    }
}

interface IBioRigTarget {
    function mintTree(address, bytes32, uint96, uint96) external returns (uint256);
    function updateTreeGrowth(uint256, uint96, uint96) external;
    function reportMortality(uint256) external;
}

/// @notice Buggy/hostile registry: deploys a genuine account, but for a different binding than the
/// one requested (the tokenId shifted by one, or a different tokenContract).
contract MisbindingRegistry is IERC6551Registry {
    enum Mode {
        WrongTokenId,
        WrongTokenContract,
        WrongChainId
    }

    ERC6551RegistryMock public immutable inner = new ERC6551RegistryMock();
    Mode public immutable mode;
    address public constant OTHER_CONTRACT = address(0xC0FFEE);

    constructor(Mode _mode) {
        mode = _mode;
    }

    function createAccount(address impl, bytes32 salt, uint256 chainId, address tokenContract, uint256 tokenId)
        external
        returns (address)
    {
        if (mode == Mode.WrongTokenId) tokenId += 1;
        else if (mode == Mode.WrongTokenContract) tokenContract = OTHER_CONTRACT;
        else chainId += 1;
        return inner.createAccount(impl, salt, chainId, tokenContract, tokenId);
    }
}

/// @notice Hostile registry that re-enters the core contract from inside createAccount
/// and bubbles up whatever revert the re-entrant call produced. When it does not re-enter
/// it behaves like the conforming registry, so the benign mint passes TBA validation.
contract ReentrantRegistry is IERC6551Registry {
    enum Mode {
        None,
        Mint,
        Growth,
        Mortality
    }

    IBioRigTarget public target;
    Mode public mode;
    uint256 public calls;
    ERC6551RegistryMock public immutable inner = new ERC6551RegistryMock();

    function configure(address _target, Mode _mode) external {
        target = IBioRigTarget(_target);
        mode = _mode;
    }

    function createAccount(address impl, bytes32 salt, uint256 chainId, address tokenContract, uint256 tokenId)
        external
        returns (address)
    {
        calls++;
        if (mode == Mode.Mint) {
            target.mintTree(address(0xBEEF), keccak256("reentrant"), 1, 1);
        } else if (mode == Mode.Growth) {
            target.updateTreeGrowth(tokenId, 100, 100);
        } else if (mode == Mode.Mortality) {
            target.reportMortality(tokenId);
        }
        return inner.createAccount(impl, salt, chainId, tokenContract, tokenId);
    }
}
