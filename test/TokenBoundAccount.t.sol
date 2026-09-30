// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

import {BaseTest} from "./Base.t.sol";
import {BioRigCoreV5} from "../src/BioRigCoreV5.sol";
import {IERC6551Account} from "../src/BioRigCoreV5.sol";
import {ZeroRegistry, ArbitraryRegistry, MisbindingRegistry} from "./mocks/Registries.sol";
import {NoTokenAccount, NoErc165Account, LyingAccount} from "./mocks/TokenBoundAccount.sol";

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
        vm.assume(n != bytes32(0));
        vm.prank(verifier);
        uint256 id = core.mintTree(to, n, 0, 0);
        assertEq(core.getTreeStats(id).tbaAddress, _expectedTba(id, to, n));
    }

    // ---- Hypothesis 1: registry returns address(0) ----

    /// H1 / FINDINGS F-1. Correct behaviour: a mint whose registry returns address(0)
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

    /// H2 / FINDINGS I-1 -> R2. This test used to document that whatever the registry returned
    /// was installed as the tree's wallet unchecked (two trees ended up sharing one codeless
    /// address). The returned account is now validated, so the same registry cannot mint at all.
    function test_H2_arbitraryRegistry_addressIsInstalledUnchecked() public {
        address unrelated = makeAddr("attacker-wallet");
        BioRigCoreV5 c = _deployWithRegistry(address(new ArbitraryRegistry(unrelated)));
        vm.startPrank(verifier);
        vm.expectRevert(BioRigCoreV5.InvalidTba.selector);
        c.mintTree(planter, N1, 1, 1);
        vm.expectRevert(BioRigCoreV5.InvalidTba.selector);
        c.mintTree(alice, N2, 1, 1);
        vm.stopPrank();
        _assertNothingPersisted(c);
        assertFalse(c.isNullifierActive(N2));
        assertEq(c.balanceOf(alice), 0);
    }

    function test_H2_registryIsNotChangeableWithoutUpgrade() public view {
        // There is no setter for erc6551Registry: only initialize (once) or an UPGRADER_ROLE
        // upgrade can choose the registry. A hostile registry therefore requires a trusted role.
        assertEq(core.erc6551Registry(), address(registry));
    }

    // ---- R2: validation of the registry's returned account ----

    function _assertNothingPersisted(BioRigCoreV5 c) internal {
        assertFalse(c.isNullifierActive(N1), "nullifier not persisted");
        assertEq(c.balanceOf(planter), 0, "no token minted");
        assertEq(uint256(vm.load(address(c), bytes32(0))), 1, "token id counter rolled back");
        vm.expectRevert(BioRigCoreV5.InvalidTree.selector);
        c.getTreeStats(1);
    }

    function _mintExpectingInvalidTba(address reg) internal {
        BioRigCoreV5 c = _deployWithRegistry(reg);
        vm.prank(verifier);
        vm.expectRevert(BioRigCoreV5.InvalidTba.selector);
        c.mintTree(planter, N1, 10, 20);
        _assertNothingPersisted(c);
    }

    function test_R2_registryReturnsEoa_reverts() public {
        _mintExpectingInvalidTba(address(new ArbitraryRegistry(makeAddr("eoa"))));
    }

    /// A genuine ERC-6551 account (real proxy, real implementation, reports the interface),
    /// but bound to tokenId + 1.
    function test_R2_registryReturnsAccountForWrongTokenId_reverts() public {
        MisbindingRegistry reg = new MisbindingRegistry(MisbindingRegistry.Mode.WrongTokenId);
        // what the registry hands back is a live, conforming account, only for the wrong token
        address acct = reg.createAccount(accountImpl, bytes32(0), block.chainid, address(core), 1);
        (,, uint256 tid) = IERC6551Account(acct).token();
        assertEq(tid, 2);
        _mintExpectingInvalidTba(address(reg));
    }

    /// A genuine ERC-6551 account bound to a different token contract.
    function test_R2_registryReturnsAccountForWrongTokenContract_reverts() public {
        _mintExpectingInvalidTba(address(new MisbindingRegistry(MisbindingRegistry.Mode.WrongTokenContract)));
    }

    /// A genuine ERC-6551 account bound to a different chain id.
    function test_R2_registryReturnsAccountForWrongChainId_reverts() public {
        _mintExpectingInvalidTba(address(new MisbindingRegistry(MisbindingRegistry.Mode.WrongChainId)));
    }

    /// A contract that claims ERC-6551 support but has no token(): the staticcall fails.
    function test_R2_registryReturnsContractWithoutToken_reverts() public {
        _mintExpectingInvalidTba(address(new ArbitraryRegistry(address(new NoTokenAccount()))));
    }

    /// Correct binding from token(), but no ERC-165 support for IERC6551Account.
    function test_R2_registryReturnsContractWithoutErc165_reverts() public {
        // the fresh proxy is the next CREATE from this test contract after the account and registry
        address predictedCore = vm.computeCreateAddress(address(this), vm.getNonce(address(this)) + 2);
        NoErc165Account acct = new NoErc165Account(block.chainid, predictedCore, 1);
        ArbitraryRegistry reg = new ArbitraryRegistry(address(acct));
        BioRigCoreV5 c = _deployWithRegistry(address(reg));
        assertEq(address(c), predictedCore, "binding targets the proxy under test");
        vm.prank(verifier);
        vm.expectRevert(BioRigCoreV5.InvalidTba.selector);
        c.mintTree(planter, N1, 10, 20);
        _assertNothingPersisted(c);
    }

    /// Conforming registry: the mint succeeds, the TBA equals the independent CREATE2
    /// recomputation (init code rebuilt here, not taken from the registry mock), and the
    /// account itself reports the binding mintTree checked.
    function test_R2_conformingRegistry_mintSucceeds_tbaMatchesCreate2() public {
        uint256 id = _mint(planter, N1);
        bytes32 salt = keccak256(abi.encodePacked(id, planter, N1));
        bytes memory initCode = abi.encodePacked(
            hex"3d60ad80600a3d3981f3363d3d373d3d3d363d73",
            accountImpl,
            hex"5af43d82803e903d91602b57fd5bf3",
            abi.encode(salt, block.chainid, address(core), id)
        );
        address tba = core.getTreeStats(id).tbaAddress;
        assertEq(tba, vm.computeCreate2Address(salt, keccak256(initCode), address(registry)));
        assertEq(tba, _expectedTba(id, planter, N1), "_expectedTba still agrees");
        (uint256 cid, address tc, uint256 tid) = IERC6551Account(tba).token();
        assertEq(cid, block.chainid);
        assertEq(tc, address(core));
        assertEq(tid, id);
    }

    /// RESIDUAL TRUST (documented, not a defect of the check): the validation proves the account
    /// *claims* the right binding, not that it is the registry's canonical CREATE2 account. A
    /// hostile registry can return an attacker contract that simply echoes the expected tuple.
    function test_R2_residual_lyingAccountIsAccepted() public {
        address predictedCore = vm.computeCreateAddress(address(this), vm.getNonce(address(this)) + 2);
        LyingAccount liar = new LyingAccount(block.chainid, predictedCore, 1);
        BioRigCoreV5 c = _deployWithRegistry(address(new ArbitraryRegistry(address(liar))));
        assertEq(address(c), predictedCore);
        vm.prank(verifier);
        uint256 id = c.mintTree(planter, N1, 10, 20);
        assertEq(c.getTreeStats(id).tbaAddress, address(liar));
    }

    function _slice(bytes memory b, uint256 start, uint256 len) internal pure returns (bytes memory out) {
        out = new bytes(len);
        for (uint256 i; i < len; ++i) {
            out[i] = b[start + i];
        }
    }
}
