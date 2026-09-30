// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

import {Script, console} from "forge-std/Script.sol";
import {ERC1967Proxy} from "@openzeppelin/contracts/proxy/ERC1967/ERC1967Proxy.sol";
import {ERC1967Utils} from "@openzeppelin/contracts/proxy/ERC1967/ERC1967Utils.sol";
import {BioRigCoreV5} from "../src/BioRigCoreV5.sol";

/// @notice Deploys the BioRigCoreV5 implementation and an ERC1967Proxy initialised in its constructor, then reads
/// the state back through the proxy. BioRigCoreV5 is UUPS, so there is no ProxyAdmin. Every input comes from the
/// environment; see .env.example and DEPLOY.md.
contract DeployBioRig is Script {
    struct Config {
        uint256 deployerKey;
        address admin;
        address registry;
        address accountImplementation;
        uint256 chainId;
        address bufferPool;
        address uriGenerator;
    }

    function run() external returns (BioRigCoreV5 core, address implementation) {
        Config memory cfg = _loadConfig();
        _preflight(cfg);

        vm.startBroadcast(cfg.deployerKey);
        implementation = address(new BioRigCoreV5());
        // The proxy runs initialize in its own constructor, so it is never live-but-uninitialised.
        bytes memory initData = abi.encodeCall(
            BioRigCoreV5.initialize,
            (cfg.admin, cfg.registry, cfg.accountImplementation, cfg.chainId, cfg.bufferPool, cfg.uriGenerator)
        );
        core = BioRigCoreV5(address(new ERC1967Proxy(implementation, initData)));
        vm.stopBroadcast();

        _verifyAndReport(cfg, core, implementation);
    }

    function _loadConfig() internal view returns (Config memory cfg) {
        cfg.deployerKey = vm.envUint("PRIVATE_KEY");
        cfg.admin = vm.envAddress("ADMIN");
        cfg.registry = vm.envAddress("ERC6551_REGISTRY");
        cfg.accountImplementation = vm.envAddress("ERC6551_IMPLEMENTATION");
        cfg.chainId = vm.envUint("CHAIN_ID");
        cfg.bufferPool = vm.envAddress("BUFFER_POOL");
        // Required so the choice is explicit; 0x0 is legal (initialize does not validate it).
        cfg.uriGenerator = vm.envAddress("URI_GENERATOR");
    }

    function _preflight(Config memory cfg) internal view {
        require(
            cfg.chainId == block.chainid,
            string.concat(
                "CHAIN_ID mismatch: env CHAIN_ID=",
                vm.toString(cfg.chainId),
                " but the RPC reports eth_chainId=",
                vm.toString(block.chainid)
            )
        );
        _requireCode(cfg.registry, "ERC6551_REGISTRY", "deploy one with script/DeployERC6551Registry.s.sol");
        _requireCode(
            cfg.accountImplementation, "ERC6551_IMPLEMENTATION", "deploy one, e.g. script/DeployERC6551Account.s.sol"
        );
        // A non-zero generator without code would make every tokenURI call revert.
        if (cfg.uriGenerator != address(0)) {
            _requireCode(cfg.uriGenerator, "URI_GENERATOR", "use 0x0 to fall back to the base URI");
        }

        address deployer = vm.addr(cfg.deployerKey);
        console.log("Deployer:              ", deployer);
        console.log("Deployer balance (wei):", deployer.balance);
    }

    function _requireCode(address target, string memory name, string memory hint) internal view {
        require(
            target.code.length != 0,
            string.concat(
                name,
                " ",
                vm.toString(target),
                " has no code on chain ",
                vm.toString(block.chainid),
                ". Refusing to deploy a BioRig whose mintTree would always revert; ",
                hint,
                " and set ",
                name,
                "."
            )
        );
    }

    function _verifyAndReport(Config memory cfg, BioRigCoreV5 core, address implementation) internal view {
        address slotImpl = address(uint160(uint256(vm.load(address(core), ERC1967Utils.IMPLEMENTATION_SLOT))));
        string memory name_ = core.name();
        string memory symbol_ = core.symbol();
        bool isAdmin = core.hasRole(core.DEFAULT_ADMIN_ROLE(), cfg.admin);
        bool isUpgrader = core.hasRole(core.UPGRADER_ROLE(), cfg.admin);

        require(slotImpl == implementation, "read-back: ERC1967 implementation slot mismatch");
        require(keccak256(bytes(name_)) == keccak256("BioRig Tree"), "read-back: name mismatch");
        require(keccak256(bytes(symbol_)) == keccak256("TREE"), "read-back: symbol mismatch");
        require(core.erc6551Registry() == cfg.registry, "read-back: erc6551Registry mismatch");
        require(core.erc6551Implementation() == cfg.accountImplementation, "read-back: erc6551Implementation mismatch");
        require(core.chainId() == cfg.chainId, "read-back: chainId mismatch");
        require(core.bufferPool() == cfg.bufferPool, "read-back: bufferPool mismatch");
        require(core.uriGenerator() == cfg.uriGenerator, "read-back: uriGenerator mismatch");
        require(isAdmin, "read-back: ADMIN lacks DEFAULT_ADMIN_ROLE");
        require(isUpgrader, "read-back: ADMIN lacks UPGRADER_ROLE");

        console.log("");
        console.log("=== BioRigCoreV5 deployment (values read back through the proxy) ===");
        console.log("chain id (block.chainid): ", block.chainid);
        console.log("implementation:           ", implementation);
        console.log("proxy (use this address): ", address(core));
        console.log("ERC1967 impl slot:        ", slotImpl);
        console.log("name():                   ", name_);
        console.log("symbol():                 ", symbol_);
        console.log("erc6551Registry():        ", core.erc6551Registry());
        console.log("erc6551Implementation():  ", core.erc6551Implementation());
        console.log("chainId():                ", core.chainId());
        console.log("bufferPool():             ", core.bufferPool());
        console.log("uriGenerator():           ", core.uriGenerator());
        console.log("admin:                    ", cfg.admin);
        console.log("admin DEFAULT_ADMIN_ROLE: ", isAdmin);
        console.log("admin UPGRADER_ROLE:      ", isUpgrader);
        console.log("NOTE: no VERIFIER_ROLE is granted; the admin must grant it before mintTree can be called.");
    }
}
