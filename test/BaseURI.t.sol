// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

import {BaseTest} from "./Base.t.sol";
import {BioRigCoreV5} from "../src/BioRigCoreV5.sol";
import {RevertingURIGenerator, GasBurningURIGenerator} from "./mocks/Misc.sol";

/// @notice I-6: the tokenURI fallback returns _baseURI() + tokenId once an admin sets a base URI.
/// The base URI starts unset (""), so until then the fallback is "" exactly as before.
contract BaseURITest is BaseTest {
    string internal constant BASE = "ipfs://bafybase/";
    string internal constant BASE2 = "https://meta.biorig.example/tree/";

    event BaseURIUpdated(string oldBaseURI, string newBaseURI);

    uint256 internal id1;
    uint256 internal id2;
    uint256 internal id3;

    function setUp() public override {
        super.setUp();
        id1 = _mint(planter, N1, 100, 200);
        id2 = _mint(alice, N2);
        id3 = _mint(bob, N3);
    }

    function _setBase(string memory b) internal {
        vm.prank(admin);
        core.setBaseURI(b);
    }

    function _dropGenerator() internal {
        vm.prank(admin);
        core.setURIGenerator(address(0));
    }

    /// Same helper as TokenURI.t.sol: plants a codeless generator in slot 5 (`uriGenerator`).
    function _plantGenerator(address g) internal {
        vm.store(address(core), bytes32(uint256(5)), bytes32(uint256(uint160(g))));
        assertEq(core.uriGenerator(), g, "slot 5 is uriGenerator");
    }

    // ---- default: unset ----

    function test_I6_unsetBaseURI_fallbackIsEmpty() public {
        assertEq(core.baseURI(), "");
        assertEq(vm.load(address(core), bytes32(uint256(8))), bytes32(0), "slot 8 zero after initialize");
        _dropGenerator();
        assertEq(core.tokenURI(id1), "");
        assertEq(core.tokenURI(id3), "");
    }

    // ---- setBaseURI ----

    function test_I6_setBaseURI_fallbackIsBasePlusTokenId() public {
        _setBase(BASE);
        _dropGenerator();
        assertEq(core.baseURI(), BASE);
        assertEq(core.tokenURI(id1), "ipfs://bafybase/1");
        assertEq(core.tokenURI(id2), "ipfs://bafybase/2");
        assertEq(core.tokenURI(id3), "ipfs://bafybase/3");
    }

    function test_I6_setBaseURI_multiDigitTokenId() public {
        for (uint256 i; i < 9; ++i) {
            _mint(planter, keccak256(abi.encode("plot-extra", i)));
        }
        _setBase(BASE);
        _dropGenerator();
        assertEq(core.tokenURI(12), "ipfs://bafybase/12");
    }

    function test_I6_setBaseURI_emitsOldAndNew() public {
        vm.expectEmit(false, false, false, true, address(core));
        emit BaseURIUpdated("", BASE);
        _setBase(BASE);

        vm.expectEmit(false, false, false, true, address(core));
        emit BaseURIUpdated(BASE, BASE2);
        _setBase(BASE2);
        assertEq(core.baseURI(), BASE2);

        _dropGenerator();
        assertEq(core.tokenURI(id2), "https://meta.biorig.example/tree/2");
    }

    function test_I6_setBaseURI_nonAdmin_reverts() public {
        vm.prank(stranger);
        vm.expectRevert(_unauthorized(stranger, DEFAULT_ADMIN_ROLE));
        core.setBaseURI(BASE);

        vm.prank(verifier);
        vm.expectRevert(_unauthorized(verifier, DEFAULT_ADMIN_ROLE));
        core.setBaseURI(BASE);

        assertEq(core.baseURI(), "", "unchanged");
    }

    function test_I6_setBaseURI_empty_restoresEmptyFallback() public {
        _setBase(BASE);
        _dropGenerator();
        assertEq(core.tokenURI(id1), "ipfs://bafybase/1");

        vm.expectEmit(false, false, false, true, address(core));
        emit BaseURIUpdated(BASE, "");
        _setBase("");
        assertEq(core.baseURI(), "");
        assertEq(vm.load(address(core), bytes32(uint256(8))), bytes32(0), "short-string slot cleared");
        assertEq(core.tokenURI(id1), "");
    }

    /// A value longer than 31 bytes is stored out of line (keccak256(8)); it reads back intact.
    function test_I6_setBaseURI_longValue() public {
        string memory longBase = "ipfs://bafybeigdyrzt5sfp7udm7hu76uh7y26nf3efuylqabf3oclgtqy55fbzdi/";
        _setBase(longBase);
        _dropGenerator();
        assertEq(core.tokenURI(id3), string.concat(longBase, "3"));
    }

    /// No validation of the string: a base without a trailing slash is concatenated as given.
    function test_I6_setBaseURI_noValidation() public {
        _setBase("ar://tree");
        _dropGenerator();
        assertEq(core.tokenURI(id2), "ar://tree2");
    }

    // ---- precedence and broken generators ----

    function test_I6_workingGenerator_winsOverBaseURI() public {
        _setBase(BASE);
        assertEq(core.tokenURI(id1), "tree:1:100:200:alive");
        assertEq(core.tokenURI(id2), "tree:2:10:20:alive");
        // ...and the base URI is what it wins over: without the generator the base path is used
        _dropGenerator();
        assertEq(core.tokenURI(id1), "ipfs://bafybase/1");
    }

    function test_I6_codelessGenerator_fallsBackToBaseURI() public {
        _setBase(BASE);
        _plantGenerator(makeAddr("codeless-generator"));
        assertEq(core.tokenURI(id1), "ipfs://bafybase/1");
        assertEq(core.tokenURI(id2), "ipfs://bafybase/2");
    }

    function test_I6_revertingGenerator_fallsBackToBaseURI() public {
        _setBase(BASE);
        address g = address(new RevertingURIGenerator());
        vm.prank(admin);
        core.setURIGenerator(g);
        assertEq(core.tokenURI(id1), "ipfs://bafybase/1");
        assertEq(core.tokenURI(id3), "ipfs://bafybase/3");
    }

    /// Same finite outer budget as test_R1_gasExhaustingGenerator_fallsBack.
    function test_I6_gasExhaustingGenerator_fallsBackToBaseURI() public {
        _setBase(BASE);
        address g = address(new GasBurningURIGenerator());
        vm.prank(admin);
        core.setURIGenerator(g);
        assertEq(core.tokenURI{gas: 5_000_000}(id2), "ipfs://bafybase/2");
    }

    function test_I6_unknownToken_stillReverts_withBaseURI() public {
        _setBase(BASE);
        vm.expectRevert(BioRigCoreV5.InvalidTree.selector);
        core.tokenURI(999);
        _dropGenerator();
        vm.expectRevert(BioRigCoreV5.InvalidTree.selector);
        core.tokenURI(999);
        // a known token under the same configuration does get the base path
        assertEq(core.tokenURI(id1), "ipfs://bafybase/1");
    }

    function test_I6_treeMintedAfterSetBaseURI_getsBaseURI() public {
        _setBase(BASE);
        _dropGenerator();
        uint256 id4 = _mint(planter, keccak256("plot-4"));
        assertEq(id4, 4);
        assertEq(core.tokenURI(id4), "ipfs://bafybase/4");
    }
}
