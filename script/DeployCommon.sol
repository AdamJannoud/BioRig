// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

import {Script, console} from "forge-std/Script.sol";
import {ERC1967Proxy} from "@openzeppelin/contracts/proxy/ERC1967/ERC1967Proxy.sol";
import {ERC1967Utils} from "@openzeppelin/contracts/proxy/ERC1967/ERC1967Utils.sol";
import {BioRigCoreV5} from "../src/BioRigCoreV5.sol";
import {ERC6551Registry} from "../src/vendor/ERC6551Registry.sol";

/// @notice Everything the BioRig deploy scripts share: config loading, preflight guards, the canonical ERC-6551
/// registry deployment, the BioRig proxy deployment, the VERIFIER_ROLE grant and the read-back assertions.
/// DeployBioRig (contract only) and DeployAll (registry + account + contract in one command) both inherit this, so
/// the two entry points cannot drift apart.
abstract contract DeployBase is Script {
    /// Nick's CREATE2 factory, present on most chains including Celo Sepolia.
    address internal constant NICKS_FACTORY = 0x4e59b44847b379578588920cA78FbF26c0B4956C;
    /// The address EIP-6551's registry occupies wherever the canonical deployment has been replayed.
    address internal constant CANONICAL_REGISTRY = 0x000000006551c19487814612e58FE06813775758;
    bytes32 internal constant CANONICAL_SALT = 0x0000000000000000000000000000000000000000fd8eb4e1dca713016c518e31;
    /// The canonical registry creation code, taken from the EIP-6551 deployment transaction. Its executable part is
    /// identical to src/vendor/ERC6551Registry.sol compiled with solc 0.8.17 / optimizer 200; only the CBOR metadata
    /// hash differs. Held as a file so both scripts hash exactly the same bytes.
    string internal constant CANONICAL_INIT_CODE_PATH = "script/data/ERC6551Registry.canonical.bin";

    struct Config {
        uint256 deployerKey;
        address deployer;
        address admin;
        address registry;
        address accountImplementation;
        uint256 chainId;
        address bufferPool;
        address uriGenerator;
    }

    // ---------------------------------------------------------------- configuration

    /// @dev The fields every entry point needs. Registry and account implementation are absent by design: DeployBioRig
    /// reads them from the environment, DeployAll takes them from the deployments it just made.
    function _loadBaseConfig() internal view returns (Config memory cfg) {
        cfg.deployerKey = vm.envUint("PRIVATE_KEY");
        cfg.deployer = vm.addr(cfg.deployerKey);
        cfg.admin = vm.envAddress("ADMIN");
        cfg.chainId = vm.envUint("CHAIN_ID");
        cfg.bufferPool = vm.envAddress("BUFFER_POOL");
        // Required so the choice is explicit; 0x0 is legal (initialize does not validate it).
        cfg.uriGenerator = vm.envAddress("URI_GENERATOR");
    }

    function _loadDeployConfig() internal view returns (Config memory cfg) {
        cfg = _loadBaseConfig();
        cfg.registry = vm.envAddress("ERC6551_REGISTRY");
        cfg.accountImplementation = vm.envAddress("ERC6551_IMPLEMENTATION");
    }

    // -------------------------------------------------------------------- preflight

    /// @dev Guards that hold for every entry point. Reverts before anything is broadcast.
    function _preflightBase(Config memory cfg) internal view {
        _checkChainId(cfg.chainId);
        require(
            cfg.admin == cfg.deployer,
            string.concat(
                "ADMIN (",
                vm.toString(cfg.admin),
                ") must be the deployer (",
                vm.toString(cfg.deployer),
                ") for this script to grant VERIFIER_ROLE; a separate admin has to send that grant itself"
            )
        );
        // A non-zero generator without code would make every tokenURI call revert.
        if (cfg.uriGenerator != address(0)) {
            _requireCode(cfg.uriGenerator, "URI_GENERATOR", "use 0x0 to fall back to the base URI");
        }
        console.log("Deployer:              ", cfg.deployer);
        console.log("Deployer balance (wei):", cfg.deployer.balance);
    }

    /// @dev The registry and account implementation must already exist when DeployBioRig runs; DeployAll creates them.
    function _preflightExternalCode(Config memory cfg) internal view {
        _requireCode(
            cfg.registry, "ERC6551_REGISTRY", "deploy one with script/DeployAll.s.sol or DeployERC6551Registry.s.sol"
        );
        _requireCode(
            cfg.accountImplementation,
            "ERC6551_IMPLEMENTATION",
            "deploy one, e.g. script/DeployERC6551Account.s.sol or DeployAll.s.sol"
        );
    }

    function _checkChainId(uint256 expected) internal view {
        require(
            expected == block.chainid,
            string.concat(
                "CHAIN_ID mismatch: env CHAIN_ID=",
                vm.toString(expected),
                " but the RPC reports eth_chainId=",
                vm.toString(block.chainid)
            )
        );
    }

    function _requireCode(address target, string memory label, string memory hint) internal view {
        require(target.code.length != 0, string.concat(label, " has no code on this chain; ", hint));
    }

    // ------------------------------------------------------------------- deployments

    /// @notice Deploys the EIP-6551 registry at the canonical address through Nick's factory with the canonical salt.
    /// No-op if that address already has code. Call inside startBroadcast.
    function _deployCanonicalRegistry() internal returns (address) {
        bytes memory initCode = vm.readFileBinary(CANONICAL_INIT_CODE_PATH);
        require(
            vm.computeCreate2Address(CANONICAL_SALT, keccak256(initCode), NICKS_FACTORY) == CANONICAL_REGISTRY,
            "canonical init code does not hash to the canonical registry address"
        );
        if (CANONICAL_REGISTRY.code.length != 0) {
            console.log("Canonical ERC-6551 registry already deployed on this chain; reusing it.");
            return CANONICAL_REGISTRY;
        }
        require(NICKS_FACTORY.code.length != 0, "Nick's factory (0x4e59b448...) has no code on this chain");

        (bool ok, bytes memory ret) = NICKS_FACTORY.call(abi.encodePacked(CANONICAL_SALT, initCode));
        require(ok && ret.length == 20 && address(bytes20(ret)) == CANONICAL_REGISTRY, "Nick's factory deploy failed");
        return CANONICAL_REGISTRY;
    }

    /// @notice BioRigCoreV5 implementation plus an ERC1967Proxy that runs initialize in its own constructor, so the
    /// proxy is never live-but-uninitialised, then VERIFIER_ROLE granted to the admin. Call inside startBroadcast.
    function _deployCore(Config memory cfg) internal returns (BioRigCoreV5 core, address implementation) {
        implementation = address(new BioRigCoreV5());
        bytes memory initData = abi.encodeCall(
            BioRigCoreV5.initialize,
            (cfg.admin, cfg.registry, cfg.accountImplementation, cfg.chainId, cfg.bufferPool, cfg.uriGenerator)
        );
        core = BioRigCoreV5(address(new ERC1967Proxy(implementation, initData)));
        _grantVerifierRole(core, cfg.admin);
    }

    /// @dev mintTree, updateTreeGrowth and reportMortality are VERIFIER_ROLE-gated and initialize grants only
    /// DEFAULT_ADMIN_ROLE and UPGRADER_ROLE, so without this the deployment cannot mint anything. The broadcaster
    /// holds DEFAULT_ADMIN_ROLE because _preflightBase requires ADMIN == deployer.
    function _grantVerifierRole(BioRigCoreV5 core, address admin) internal {
        require(
            core.hasRole(core.DEFAULT_ADMIN_ROLE(), admin),
            "admin lacks DEFAULT_ADMIN_ROLE; nothing in this script can grant VERIFIER_ROLE"
        );
        core.grantRole(core.VERIFIER_ROLE(), admin);
        require(core.hasRole(core.VERIFIER_ROLE(), admin), "VERIFIER_ROLE grant did not take effect");
    }

    // ------------------------------------------------------------------- assertions

    /// @dev Reads every configured value back through the proxy, so a deployment that only looks successful fails
    /// here instead.
    function _readBack(Config memory cfg, BioRigCoreV5 core, address implementation) internal view {
        address slotImplementation =
            address(uint160(uint256(vm.load(address(core), ERC1967Utils.IMPLEMENTATION_SLOT))));
        require(slotImplementation == implementation, "read-back: ERC1967 implementation slot mismatch");
        require(core.erc6551Registry() == cfg.registry, "read-back: erc6551Registry mismatch");
        require(core.erc6551Implementation() == cfg.accountImplementation, "read-back: erc6551Implementation mismatch");
        require(core.chainId() == cfg.chainId, "read-back: chainId mismatch");
        require(core.bufferPool() == cfg.bufferPool, "read-back: bufferPool mismatch");
        require(core.uriGenerator() == cfg.uriGenerator, "read-back: uriGenerator mismatch");
        require(core.hasRole(core.DEFAULT_ADMIN_ROLE(), cfg.admin), "read-back: admin lacks DEFAULT_ADMIN_ROLE");
        require(core.hasRole(core.UPGRADER_ROLE(), cfg.admin), "read-back: admin lacks UPGRADER_ROLE");
        require(core.hasRole(core.VERIFIER_ROLE(), cfg.admin), "read-back: admin lacks VERIFIER_ROLE");
        require(!core.paused(), "read-back: contract should start unpaused");
    }

    /// account() must agree with an independent CREATE2 computation over the EIP-6551 account bytecode layout.
    function _registrySmokeTest(address registry) internal view {
        require(registry.code.length != 0, "registry has no code after deployment");
        address impl = address(0xBEbeBeBEbeBebeBeBEBEbebEBeBeBebeBeBebebe);
        address token = address(0xcfCFcfCfcFCFcFCfCfCFcFCfcfcfcfcfcfCfCfCf);
        bytes32 salt = bytes32(uint256(7));
        bytes memory accountCode = abi.encodePacked(
            hex"3d60ad80600a3d3981f3363d3d373d3d3d363d73",
            impl,
            hex"5af43d82803e903d91602b57fd5bf3",
            abi.encode(salt, block.chainid, token, uint256(123))
        );
        address expected = vm.computeCreate2Address(salt, keccak256(accountCode), registry);
        address got = ERC6551Registry(registry).account(impl, salt, block.chainid, token, 123);
        require(got == expected, "registry.account() disagrees with the EIP-6551 address derivation");
    }

    // ---------------------------------------------------------------------- reporting

    function _explorerUrl() internal view returns (string memory) {
        return vm.envOr("EXPLORER_URL", string("https://celo-sepolia.blockscout.com"));
    }

    function _logAddress(string memory label, address value) internal view {
        console.log(label, value);
        console.log(string.concat("   ", _explorerUrl(), "/address/", vm.toString(value)));
    }

    /// @notice The summary table: every address this deployment is reachable at, with its explorer link.
    function _report(Config memory cfg, address registry, address accountImplementation, address implementation, BioRigCoreV5 core)
        internal
        view
    {
        console.log("");
        console.log("=== BioRig deployment summary ===");
        console.log("chain id:", cfg.chainId);
        _logAddress("ERC-6551 registry:     ", registry);
        _logAddress("ERC-6551 account impl: ", accountImplementation);
        _logAddress("BioRig implementation: ", implementation);
        _logAddress("BioRig proxy:          ", address(core));
        console.log("admin (= deployer):    ", cfg.admin);
        console.log("buffer pool:           ", cfg.bufferPool);
        console.log("uri generator:         ", cfg.uriGenerator);
        console.log("VERIFIER_ROLE held by admin:", core.hasRole(core.VERIFIER_ROLE(), cfg.admin));
        console.log("");
        console.log("Set these in .env for later runs:");
        console.log(string.concat("ERC6551_REGISTRY=", vm.toString(registry)));
        console.log(string.concat("ERC6551_IMPLEMENTATION=", vm.toString(accountImplementation)));
    }
}
