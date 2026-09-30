// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

import {BaseTest} from "./Base.t.sol";
import {BioRigCoreV5} from "../src/BioRigCoreV5.sol";
import {RevertingURIGenerator} from "./mocks/Misc.sol";

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
    // FINDINGS L-1: documents behaviour. Availability-only, admin-caused, admin-recoverable.

    /// A codeless generator makes tokenURI revert for every token: the high-level call
    /// expects return data, so ABI-decoding the empty returndata reverts (with empty data).
    function test_H3_codelessGenerator_bricksTokenURI_untilReset() public {
        uint256 id2 = _mint(alice, N2);
        address eoa = makeAddr("not-a-contract");
        vm.prank(admin);
        core.setURIGenerator(eoa);

        vm.expectRevert(bytes(""));
        core.tokenURI(id);
        vm.expectRevert(bytes(""));
        core.tokenURI(id2);
        // no other path depends on the generator
        assertEq(core.getTreeStats(id).dbh, 100);
        vm.prank(planter);
        core.transferFrom(planter, bob, id);

        // same admin recovers immediately
        vm.prank(admin);
        core.setURIGenerator(address(generator));
        assertEq(core.tokenURI(id), "tree:1:100:200:alive");
    }

    function test_H3_revertingGenerator_bubblesRevert_untilReset() public {
        RevertingURIGenerator bad = new RevertingURIGenerator();
        vm.prank(admin);
        core.setURIGenerator(address(bad));
        vm.expectRevert(RevertingURIGenerator.GeneratorDown.selector);
        core.tokenURI(id);

        vm.prank(admin);
        core.setURIGenerator(address(0));
        assertEq(core.tokenURI(id), "");
    }
}
