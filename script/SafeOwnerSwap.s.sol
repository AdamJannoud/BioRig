// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

import {console} from "forge-std/Script.sol";
import {DeployBase} from "./DeployCommon.sol";
import {SafeOwnershipGuard} from "./SafeOwnershipGuard.sol";

/// @dev The Safe surface the swap needs. getTransactionHash and execTransaction have kept these signatures from Safe
/// v1.3.0 through v1.5.0, which is what the mainnet Safe runs.
interface ISafeExec {
    function nonce() external view returns (uint256);
    function isOwner(address owner) external view returns (bool);
    function getOwners() external view returns (address[] memory);
    function getThreshold() external view returns (uint256);
    function swapOwner(address prevOwner, address oldOwner, address newOwner) external;
    function getTransactionHash(
        address to,
        uint256 value,
        bytes calldata data,
        uint8 operation,
        uint256 safeTxGas,
        uint256 baseGas,
        uint256 gasPrice,
        address gasToken,
        address refundReceiver,
        uint256 _nonce
    ) external view returns (bytes32);
    function execTransaction(
        address to,
        uint256 value,
        bytes calldata data,
        uint8 operation,
        uint256 safeTxGas,
        uint256 baseGas,
        uint256 gasPrice,
        address gasToken,
        address payable refundReceiver,
        bytes memory signatures
    ) external payable returns (bool success);
}

/// @notice The step before the role handover. HardenMainnetAdmin refuses a NEW_ADMIN Safe the deployer can sign for,
/// and the Safe set up for mainnet was exactly that: a 1-of-1 Safe whose sole owner is the deployer hot key. This moves
/// that Safe's sole owner from the deployer to NEW_OWNER, as one Safe transaction signed by the deployer, so the Safe
/// can then take admin without leaving the pen in the same hand.
///
/// The transaction is swapOwner(SENTINEL, deployer, NEW_OWNER) sent by the Safe to itself. Its digest comes from the
/// Safe's own getTransactionHash rather than a hand-encoded EIP-712 struct, so the signature is over exactly what this
/// Safe version checks; the deployer signs it with vm.sign and the same key sends execTransaction.
///
/// Fail-closed preflight, before anything is signed: the chain ids agree; SAFE_ADDRESS is a Safe; its threshold is 1;
/// the deployer is an owner (a re-run, or a wrong PRIVATE_KEY, stops here with nothing to swap); NEW_OWNER is not zero,
/// not the deployer and not already an owner; the deployer is the sole owner; and NEW_OWNER is an address the deployer
/// cannot sign for - an EOA, or a Safe whose ownership tree the deployer does not appear in at any depth.
///
/// Env: PRIVATE_KEY (the deployer), CHAIN_ID, SAFE_ADDRESS, NEW_OWNER, and optionally ALLOW_UNINSPECTED_OWNER=true to
/// accept a contract NEW_OWNER that does not answer getOwners() after a human has checked it.
contract SafeOwnerSwap is DeployBase, SafeOwnershipGuard {
    /// @dev The head of a Safe's owner linked list; the previous owner of the first (here the only) owner.
    address internal constant SENTINEL_OWNERS = address(0x1);
    /// @dev Enum.Operation.Call.
    uint8 internal constant OPERATION_CALL = 0;

    struct Swap {
        uint256 deployerKey;
        address deployer;
        uint256 chainId;
        address safe;
        address newOwner;
    }

    function run() external {
        Swap memory s = _loadSwapConfig();
        _preflightSwap(s);

        ISafeExec safe = ISafeExec(s.safe);
        bytes memory data = abi.encodeCall(ISafeExec.swapOwner, (SENTINEL_OWNERS, s.deployer, s.newOwner));
        uint256 nonceBefore = safe.nonce();
        bytes32 digest = safe.getTransactionHash(
            s.safe, 0, data, OPERATION_CALL, 0, 0, 0, address(0), address(0), nonceBefore
        );
        (uint8 v, bytes32 r, bytes32 sig) = vm.sign(s.deployerKey, digest);
        bytes memory signatures = abi.encodePacked(r, sig, v);
        console.log("Safe nonce:            ", nonceBefore);
        console.log("Safe tx hash:          ", vm.toString(digest));

        vm.startBroadcast(s.deployerKey);
        bool ok = safe.execTransaction(
            s.safe, 0, data, OPERATION_CALL, 0, 0, 0, address(0), payable(address(0)), signatures
        );
        vm.stopBroadcast();
        require(ok, "execTransaction returned false: the swapOwner call inside the Safe failed");

        _assertSwapped(s, nonceBefore);
        _reportSwap(s);
    }

    // ---------------------------------------------------------------- configuration

    function _loadSwapConfig() internal view returns (Swap memory s) {
        s.deployerKey = vm.envUint("PRIVATE_KEY");
        s.deployer = vm.addr(s.deployerKey);
        s.chainId = vm.envUint("CHAIN_ID");
        s.safe = vm.envAddress("SAFE_ADDRESS");
        s.newOwner = vm.envAddress("NEW_OWNER");
    }

    // -------------------------------------------------------------------- preflight

    /// @dev Reverts before anything is signed if any assumption the swap rests on is false.
    function _preflightSwap(Swap memory s) internal view {
        _checkChainId(s.chainId);

        _requireCode(s.safe, "SAFE_ADDRESS", "it is not a Safe; point it at the Safe whose owner is to be replaced");
        (bool thresholdRead, uint256 threshold) = _probeThreshold(s.safe);
        require(thresholdRead, "SAFE_ADDRESS does not answer getThreshold(); it is not a Safe");
        (bool ownersRead, address[] memory owners) = _probeOwners(s.safe);
        require(ownersRead, "SAFE_ADDRESS does not answer getOwners(); it is not a Safe");

        require(
            threshold == 1,
            string.concat(
                "SAFE_ADDRESS has threshold ",
                vm.toString(threshold),
                ", not 1: a swapOwner signed by the deployer alone cannot satisfy it; collect the other owners' signatures in the Safe app instead"
            )
        );

        require(
            _contains(owners, s.deployer),
            string.concat(
                "the deployer key cannot sign for this Safe; nothing to swap (already swapped, or wrong PRIVATE_KEY): deployer ",
                vm.toString(s.deployer),
                " is not an owner"
            )
        );

        require(s.newOwner != address(0), "NEW_OWNER is the zero address; set it to the address that takes the Safe over");
        require(s.newOwner != s.deployer, "NEW_OWNER is the deployer; the point is to take the Safe off the hot key");
        require(s.newOwner != SENTINEL_OWNERS, "NEW_OWNER is the Safe owner-list sentinel 0x1; use a real address");
        require(s.newOwner != s.safe, "NEW_OWNER is the Safe itself; a Safe cannot be its own owner");
        require(
            !_contains(owners, s.newOwner), "NEW_OWNER is already an owner of this Safe; remove the deployer in the Safe app instead"
        );

        require(
            owners.length == 1,
            string.concat(
                "the deployer is one of ",
                vm.toString(owners.length),
                " owners, not the sole owner; this script only swaps a 1-of-1 Safe, change multi-owner Safes in the Safe app"
            )
        );

        _requireOwnerCandidate(s);

        console.log("Chain id:              ", block.chainid);
        console.log("Deployer (signs):      ", s.deployer);
        _logAddress("SAFE_ADDRESS:          ", s.safe);
        _logAddress("NEW_OWNER:             ", s.newOwner);
        console.log("Safe threshold:        ", threshold);
        console.log("Safe nonce:            ", ISafeExec(s.safe).nonce());
    }

    /// @dev NEW_OWNER must be an address the deployer cannot sign for, or the swap only re-enters the trap it exists to
    /// get out of: both Safes supplied on 1 October 2026 were 1-of-1 Safes owned by the deployer, and handing this Safe
    /// to such a Safe would leave the hot key holding the pen one level down. A code-less EOA passes. A contract passes
    /// only if it answers getOwners() and the shared walk finds no deployer anywhere beneath it; a contract that cannot
    /// be inspected is refused unless ALLOW_UNINSPECTED_OWNER=true records that a human checked it.
    function _requireOwnerCandidate(Swap memory s) internal view {
        if (s.newOwner.code.length == 0) {
            console.log("NEW_OWNER is a code-less account (EOA)");
            return;
        }
        (bool read, address[] memory owners) = _probeOwners(s.newOwner);
        if (!read) {
            require(
                vm.envOr("ALLOW_UNINSPECTED_OWNER", false),
                string.concat(
                    "NEW_OWNER is a contract this script cannot inspect (",
                    vm.toString(s.newOwner),
                    " does not answer getOwners()); use an EOA or a Safe the deployer cannot sign for, or set ALLOW_UNINSPECTED_OWNER=true once a human has checked it"
                )
            );
            console.log("WARNING: uninspected contract NEW_OWNER accepted by ALLOW_UNINSPECTED_OWNER:", s.newOwner);
            return;
        }
        require(owners.length != 0, "NEW_OWNER answers getOwners() with no owners; it cannot sign for the Safe");
        for (uint256 i; i < owners.length; ++i) {
            _requireNotDeployerControlled(s.deployer, "NEW_OWNER", owners[i], MAX_OWNERSHIP_DEPTH, 1);
        }
        console.log("NEW_OWNER is a Safe; owners walked, deployer not found:", owners.length);
    }

    function _contains(address[] memory list, address who) internal pure returns (bool) {
        for (uint256 i; i < list.length; ++i) {
            if (list[i] == who) return true;
        }
        return false;
    }

    // ------------------------------------------------------------------- assertions

    function _assertSwapped(Swap memory s, uint256 nonceBefore) internal view {
        ISafeExec safe = ISafeExec(s.safe);
        address[] memory owners = safe.getOwners();
        require(owners.length == 1 && owners[0] == s.newOwner, "read-back: owners is not exactly [NEW_OWNER]");
        require(safe.getThreshold() == 1, "read-back: threshold is not 1");
        require(!safe.isOwner(s.deployer), "read-back: the deployer is still an owner");
        require(safe.isOwner(s.newOwner), "read-back: NEW_OWNER is not an owner");
        require(safe.nonce() == nonceBefore + 1, "read-back: Safe nonce did not advance by one");
    }

    function _reportSwap(Swap memory s) internal view {
        ISafeExec safe = ISafeExec(s.safe);
        console.log("");
        console.log("=== Safe owner swap ===");
        console.log("chain id:", block.chainid);
        console.log("Safe:    ", s.safe);
        console.log("owners:  [", safe.getOwners()[0], "]");
        console.log("threshold:", safe.getThreshold());
        console.log("nonce:    ", safe.nonce());
        console.log("deployer is owner:", safe.isOwner(s.deployer));
        console.log("The deployer key can no longer sign for this Safe. Next: DEPLOY.md section 8 step 7, the handover.");
        console.log("");
        console.log("Runbook (the same, single step):");
        console.log(
            string.concat(
                "NEW_OWNER=",
                vm.toString(s.newOwner),
                " SAFE_ADDRESS=",
                vm.toString(s.safe),
                " forge script script/SafeOwnerSwap.s.sol:SafeOwnerSwap --rpc-url ",
                _rpcUrl(),
                " --broadcast"
            )
        );
    }

    /// @dev This chain's rpc_url from dashboard/chains.json, the same registry the shell harnesses read.
    function _rpcUrl() internal view returns (string memory) {
        string memory chains = vm.readFile(CHAINS_PATH);
        string memory key = string.concat(".chains.", vm.toString(block.chainid), ".rpc_url");
        if (vm.keyExistsJson(chains, key)) return vm.parseJsonString(chains, key);
        return "<rpc url>";
    }
}
