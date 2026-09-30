// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

import {BaseTest} from "./Base.t.sol";
import {BioRigCoreV5} from "../src/BioRigCoreV5.sol";
import {
    RevertingURIGenerator, GasBurningURIGenerator, URIGeneratorMock, MalformedURIGenerator
} from "./mocks/Misc.sol";

contract TokenURITest is BaseTest {
    uint256 internal id;

    function setUp() public override {
        super.setUp();
        id = _mint(planter, N1, 100, 200);
    }

    function test_tokenURI_generatorPath() public {
        assertEq(core.tokenURI(id), "tree:1:100:200:alive");
        vm.prank(verifier);
        core.updateTreeGrowth(id, 150, 250);
        assertEq(core.tokenURI(id), "tree:1:150:250:alive");
        vm.prank(verifier);
        core.reportMortality(id);
        assertEq(core.tokenURI(id), "tree:1:150:250:dead");
    }

    function test_tokenURI_passesStatsToGenerator() public {
        vm.expectCall(address(generator), abi.encodeCall(generator.generateURI, (id, 100, 200, true)));
        core.tokenURI(id);
    }

    /// Fallback: no generator -> ERC721Upgradeable.tokenURI, whose _baseURI() is "" (not overridden),
    /// so the result is the empty string (FINDINGS I-6).
    function test_tokenURI_noGeneratorFallback_returnsEmpty() public {
        vm.prank(admin);
        core.setURIGenerator(address(0));
        assertEq(core.tokenURI(id), "");
    }

    function test_tokenURI_noGeneratorFromInit() public {
        BioRigCoreV5 c = _deployProxy(address(registry), address(0));
        vm.prank(admin);
        c.grantRole(VERIFIER_ROLE, verifier);
        vm.prank(verifier);
        uint256 t = c.mintTree(planter, N1, 1, 1);
        assertEq(c.tokenURI(t), "");
    }

    function test_tokenURI_unknownToken_reverts() public {
        vm.expectRevert(BioRigCoreV5.InvalidTree.selector);
        core.tokenURI(999);
    }

    function test_tokenURI_unknownToken_reverts_noGenerator() public {
        vm.prank(admin);
        core.setURIGenerator(address(0));
        vm.expectRevert(BioRigCoreV5.InvalidTree.selector);
        core.tokenURI(999);
    }

    // ---- Hypothesis 3: generator with no code / reverting generator ----
    // FINDINGS L-1 -> R1. These two tests used to document that tokenURI reverted for every token
    // until the admin reset the generator. tokenURI now falls back to super.tokenURI, which is ""
    // because _baseURI() is not overridden (I-6): "not bricked" is not "useful metadata".

    /// Codeless generator: setURIGenerator now refuses it (R3), so the state is planted directly
    /// in slot 5 (`uriGenerator`, per `forge inspect ... storageLayout`) as an upgrade could leave it.
    function test_H3_codelessGenerator_bricksTokenURI_untilReset() public {
        uint256 id2 = _mint(alice, N2);
        address eoa = makeAddr("not-a-contract");
        vm.prank(admin);
        vm.expectRevert(BioRigCoreV5.InvalidAddress.selector);
        core.setURIGenerator(eoa);

        _plantGenerator(eoa);
        assertEq(core.tokenURI(id), "", "falls back, does not revert");
        assertEq(core.tokenURI(id2), "");
        // no other path depends on the generator
        assertEq(core.getTreeStats(id).dbh, 100);
        vm.prank(planter);
        core.transferFrom(planter, bob, id);

        vm.prank(admin);
        core.setURIGenerator(address(generator));
        assertEq(core.tokenURI(id), "tree:1:100:200:alive");
    }

    function test_H3_revertingGenerator_bubblesRevert_untilReset() public {
        RevertingURIGenerator bad = new RevertingURIGenerator();
        vm.prank(admin);
        core.setURIGenerator(address(bad));
        assertEq(core.tokenURI(id), "", "falls back, does not bubble GeneratorDown");

        vm.prank(admin);
        core.setURIGenerator(address(0));
        assertEq(core.tokenURI(id), "");
    }

    // ---- R1: explicit fallback cases ----

    function _plantGenerator(address g) internal {
        vm.store(address(core), bytes32(uint256(5)), bytes32(uint256(uint160(g))));
        assertEq(core.uriGenerator(), g, "slot 5 is uriGenerator");
    }

    function test_R1_zeroCodeGenerator_fallsBack() public {
        _plantGenerator(makeAddr("codeless-generator"));
        assertEq(core.tokenURI(id), "");
    }

    function test_R1_revertingGenerator_fallsBack() public {
        address g = address(new RevertingURIGenerator());
        vm.prank(admin);
        core.setURIGenerator(g);
        assertEq(core.tokenURI(id), "");
    }

    /// The generator loops until its frame is out of gas. tokenURI keeps the 1/64 of gas the
    /// CALL leaves behind (EIP-150) and uses it for the fallback. The outer call is given a
    /// finite budget, as any eth_call has.
    function test_R1_gasExhaustingGenerator_fallsBack() public {
        address g = address(new GasBurningURIGenerator());
        vm.prank(admin);
        core.setURIGenerator(g);
        assertEq(core.tokenURI{gas: 5_000_000}(id), "");
    }

    /// The guard does not swallow the unknown-token check, which runs before the generator.
    function test_R1_unknownToken_stillReverts_withBrokenGenerator() public {
        address g = address(new RevertingURIGenerator());
        vm.prank(admin);
        core.setURIGenerator(g);
        vm.expectRevert(BioRigCoreV5.InvalidTree.selector);
        core.tokenURI(999);
    }

    /// RESIDUAL (documented, outside R1's scope): try/catch only catches a failure of the call
    /// itself. A generator that returns successfully with returndata that is not a valid ABI string
    /// makes the decode revert in tokenURI's own frame, which no catch clause covers.
    function test_R1_residual_malformedReturndata_stillReverts() public {
        address g = address(new MalformedURIGenerator());
        vm.prank(admin);
        core.setURIGenerator(g);
        vm.expectRevert();
        core.tokenURI(id);
    }

    // ---- R3: setURIGenerator input validation ----

    function test_R3_setURIGenerator_eoa_reverts() public {
        address eoa = makeAddr("eoa-generator");
        vm.prank(admin);
        vm.expectRevert(BioRigCoreV5.InvalidAddress.selector);
        core.setURIGenerator(eoa);
        assertEq(core.uriGenerator(), address(generator), "unchanged");
    }

    function test_R3_setURIGenerator_zero_succeeds() public {
        vm.expectEmit(true, true, false, false, address(core));
        emit URIGeneratorUpdated(address(generator), address(0));
        vm.prank(admin);
        core.setURIGenerator(address(0));
        assertEq(core.uriGenerator(), address(0));
        assertEq(core.tokenURI(id), "");
    }

    function test_R3_setURIGenerator_contract_succeeds() public {
        address gen2 = address(new URIGeneratorMock());
        vm.prank(admin);
        core.setURIGenerator(gen2);
        assertEq(core.uriGenerator(), gen2);
    }
}
