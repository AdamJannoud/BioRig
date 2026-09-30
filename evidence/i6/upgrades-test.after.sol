    /// Storage-layout preservation: write every kind of V5 state, upgrade, read it all back through V6.
    function test_upgrade_v6ReadsV5State_layoutPreserved() public {
        // --- V5 writes ---
        uint256 a = _mint(planter, N1, 10, 20);
        vm.warp(block.timestamp + 100);
        uint256 b = _mint(alice, N2, 30, 40);
        vm.prank(verifier);
        core.updateTreeGrowth(a, 15, 25);
        vm.prank(verifier);
        core.reportMortality(b);
        vm.prank(planter);
        core.approve(bob, a);
        URIGeneratorMock gen2 = new URIGeneratorMock();
        // short (< 32 bytes) so the whole string is stored inline in V5's slot 8
        string memory base = "ipfs://bafyI6layout/";
        vm.startPrank(admin);
        core.setURIGenerator(address(gen2));
        core.setBufferPool(bob);
        core.setBaseURI(base);
        core.pause();
        vm.stopPrank();

        BioRigCoreV5.TreeStats memory sa = core.getTreeStats(a);
        BioRigCoreV5.TreeStats memory sb = core.getTreeStats(b);

        // raw slots before upgrade: all of V5's own sequential slots, 0-7 plus _baseTokenURI at 8
        bytes32[9] memory before;
        for (uint256 i; i < 9; ++i) {
            before[i] = vm.load(address(core), bytes32(i));
        }
        assertTrue(before[8] != bytes32(0), "slot 8 must hold the base URI at snapshot time");

        // --- upgrade ---
        BioRigCoreV6 v6impl = new BioRigCoreV6();
        vm.prank(admin);
        core.upgradeToAndCall(address(v6impl), abi.encodeCall(BioRigCoreV6.initializeV6, (0xC0FFEE)));
        BioRigCoreV6 v6 = BioRigCoreV6(address(core));

        // --- raw slots unchanged, appended var is in slot 9 (V5 now ends at slot 8) ---
        for (uint256 i; i < 9; ++i) {
            assertEq(vm.load(address(core), bytes32(i)), before[i], "V5 slot moved");
        }
        assertEq(uint256(vm.load(address(core), bytes32(uint256(9)))), 0xC0FFEE);
        assertEq(v6.v6Marker(), 0xC0FFEE);
        // non-collision: initializeV6 wrote the marker into none of V5's own slots, and no V5 slot
        // held it before either (so the post-upgrade check can't be satisfied by coincidence)
        for (uint256 i; i < 9; ++i) {
            assertTrue(before[i] != bytes32(uint256(0xC0FFEE)), "marker value already in a V5 slot");
            assertTrue(vm.load(address(core), bytes32(i)) != bytes32(uint256(0xC0FFEE)), "V6 marker collided with a V5 slot");
        }
        assertEq(v6.baseURI(), base);

        // --- V6 reads V5 state ---
        assertEq(v6.nextTokenIdV6(), 3);
        assertEq(v6.erc6551Registry(), address(registry));
        assertEq(v6.erc6551Implementation(), accountImpl);
        assertEq(v6.chainId(), block.chainid);
        assertEq(v6.bufferPool(), bob);
        assertEq(v6.uriGenerator(), address(gen2));
        assertTrue(v6.paused());
        assertTrue(v6.hasRole(VERIFIER_ROLE, verifier));
        assertTrue(v6.hasRole(DEFAULT_ADMIN_ROLE, admin));
        assertEq(v6.name(), "BioRig Tree");
        assertEq(v6.ownerOf(a), planter);
        assertEq(v6.ownerOf(b), alice);
        assertEq(v6.getApproved(a), bob);
        assertEq(v6.balanceOf(planter), 1);
        assertTrue(v6.isNullifierActive(N1));
        assertFalse(v6.isNullifierActive(N2));

        BioRigCoreV5.TreeStats memory va = v6.getTreeStats(a);
        BioRigCoreV5.TreeStats memory vb = v6.getTreeStats(b);
        assertEq(keccak256(abi.encode(va)), keccak256(abi.encode(sa)));
        assertEq(keccak256(abi.encode(vb)), keccak256(abi.encode(sb)));
        assertEq(va.dbh, 15);
        assertFalse(vb.isAlive);

        // --- V6 continues where V5 stopped ---
        vm.prank(admin);
        v6.unpause();
        vm.prank(verifier);
        assertEq(v6.mintTree(planter, N3, 1, 1), 3);
        vm.prank(verifier);
        vm.expectRevert(BioRigCoreV5.NullifierInUse.selector);
        v6.mintTree(planter, N1, 1, 1);
        assertEq(v6.tokenURI(a), "tree:1:15:25:alive");
        // with the generator cleared, V6 resolves the fallback from V5's preserved base URI
        vm.prank(admin);
        v6.setURIGenerator(address(0));
        assertEq(v6.tokenURI(a), string.concat(base, vm.toString(a)));
        assertEq(v6.tokenURI(a), "ipfs://bafyI6layout/1");
    }
