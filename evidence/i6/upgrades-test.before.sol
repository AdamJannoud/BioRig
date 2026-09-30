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
        vm.startPrank(admin);
        core.setURIGenerator(address(gen2));
        core.setBufferPool(bob);
        core.pause();
        vm.stopPrank();

        BioRigCoreV5.TreeStats memory sa = core.getTreeStats(a);
        BioRigCoreV5.TreeStats memory sb = core.getTreeStats(b);

        // raw slots before upgrade
        bytes32[8] memory before;
        for (uint256 i; i < 8; ++i) {
            before[i] = vm.load(address(core), bytes32(i));
        }

        // --- upgrade ---
        BioRigCoreV6 v6impl = new BioRigCoreV6();
        vm.prank(admin);
        core.upgradeToAndCall(address(v6impl), abi.encodeCall(BioRigCoreV6.initializeV6, (0xC0FFEE)));
        BioRigCoreV6 v6 = BioRigCoreV6(address(core));

        // --- raw slots unchanged, appended var is in slot 8 ---
        for (uint256 i; i < 8; ++i) {
            assertEq(vm.load(address(core), bytes32(i)), before[i], "V5 slot moved");
        }
        assertEq(uint256(vm.load(address(core), bytes32(uint256(8)))), 0xC0FFEE);
        assertEq(v6.v6Marker(), 0xC0FFEE);

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
    }
