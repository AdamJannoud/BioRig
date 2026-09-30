// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

import {BaseTest} from "./Base.t.sol";
import {BioRigCoreV5} from "../src/BioRigCoreV5.sol";
import {ZeroRegistry, ArbitraryRegistry} from "./mocks/Registries.sol";

contract TokenBoundAccountTest is BaseTest {
    function test_salt_isDeterministic() public pure {
        bytes32 n = keccak256("plot-1");
        address p = address(0x1234);
        assertEq(
            keccak256(abi.encodePacked(uint256(1), p, n)), keccak256(abi.encodePacked(uint256(1), p, n))
        );
        // abi.encodePacked(uint256, address, bytes32) is 32 + 20 + 32 = 84 bytes: no ambiguity
        assertEq(abi.encodePacked(uint256(1), p, n).length, 84);
    }

    /// The contract passes (accountImpl, salt, chainId, address(this), tokenId) to the registry.
    function test_createAccount_calledWithExpectedArgs() public {
        bytes32 salt = _salt(1, planter, N1);
        vm.expectCall(
            address(registry),
            abi.encodeCall(registry.createAccount, (accountImpl, salt, block.chainid, address(core), 1))
        );
        _mint(planter, N1);
    }

    /// Independent recomputation: CREATE2(0xff ++ registry ++ salt ++ keccak256(initCode)),
    /// with the ERC-6551 reference init code built here from first principles.
    function test_tba_matchesIndependentRecomputation() public {
        uint256 id = _mint(planter, N1);
        bytes32 salt = keccak256(abi.encodePacked(id, planter, N1));
        bytes memory initCode = abi.encodePacked(
            hex"3d60ad80600a3d3981f3363d3d373d3d3d363d73",
            accountImpl,
            hex"5af43d82803e903d91602b57fd5bf3",
            abi.encode(salt, block.chainid, address(core), id)
        );
        address expected = vm.computeCreate2Address(salt, keccak256(initCode), address(registry));
        address tba = core.getTreeStats(id).tbaAddress;
        assertEq(tba, expected);
        assertGt(tba.code.length, 0, "account was deployed");
        // runtime footer carries the token binding (chainId, tokenContract, tokenId)
        bytes memory rt = tba.code;
        (, uint256 cid, address tokenContract, uint256 tokenId) =
            abi.decode(_slice(rt, rt.length - 128, 128), (bytes32, uint256, address, uint256));
        assertEq(cid, block.chainid);
        assertEq(tokenContract, address(core));
        assertEq(tokenId, id);
    }

    function test_tba_distinctPerToken() public {
        uint256 a = _mint(planter, N1);
        uint256 b = _mint(planter, N2);
        assertTrue(core.getTreeStats(a).tbaAddress != core.getTreeStats(b).tbaAddress);
    }

    function testFuzz_tba_matchesRecomputation(address to, bytes32 n) public {
        vm.assume(to != address(0) && to.code.length == 0 && uint160(to) > 0xff);
        vm.prank(verifier);
        uint256 id = core.mintTree(to, n, 0, 0);
        assertEq(core.getTreeStats(id).tbaAddress, _expectedTba(id, to, n));
    }

    // ---- Hypothesis 1: registry returns address(0) ----

    /// H1 / FINDINGS M-1. Correct behaviour: a mint whose registry returns address(0)
    /// must revert, instead of producing an owned NFT that every tree path rejects.
    function test_H1_zeroRegistry_mintReverts() public {
        BioRigCoreV5 c = _deployWithRegistry(address(new ZeroRegistry()));
        vm.prank(verifier);
        vm.expectRevert(BioRigCoreV5.InvalidAddress.selector);
        c.mintTree(planter, N1, 10, 20);
        // nothing persisted
        assertFalse(c.isNullifierActive(N1));
        assertEq(c.balanceOf(planter), 0);
        assertEq(uint256(vm.load(address(c), bytes32(uint256(0)))), 1);
    }

    // ---- Hypothesis 2: registry returns an unrelated address ----

    /// H2 / FINDINGS I-1 (documents behaviour, trust assumption): the contract does not
    /// check that the returned account is bound to the token. Whatever the registry
    /// returns becomes the tree's wallet.
    function test_H2_arbitraryRegistry_addressIsInstalledUnchecked() public {
        address unrelated = makeAddr("attacker-wallet");
        BioRigCoreV5 c = _deployWithRegistry(address(new ArbitraryRegistry(unrelated)));
        vm.startPrank(verifier);
        uint256 a = c.mintTree(planter, N1, 1, 1);
        uint256 b = c.mintTree(alice, N2, 1, 1);
        vm.stopPrank();
        assertEq(c.getTreeStats(a).tbaAddress, unrelated);
        assertEq(c.getTreeStats(b).tbaAddress, unrelated, "two trees share one 'wallet'");
        assertEq(unrelated.code.length, 0, "not even a contract");
    }

    function test_H2_registryIsNotChangeableWithoutUpgrade() public view {
        // There is no setter for erc6551Registry: only initialize (once) or an UPGRADER_ROLE
        // upgrade can choose the registry. A hostile registry therefore requires a trusted role.
        assertEq(core.erc6551Registry(), address(registry));
    }

    function _slice(bytes memory b, uint256 start, uint256 len) internal pure returns (bytes memory out) {
        out = new bytes(len);
        for (uint256 i; i < len; ++i) {
            out[i] = b[start + i];
        }
    }
}
