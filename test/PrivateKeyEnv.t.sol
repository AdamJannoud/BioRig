// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

import {Test} from "forge-std/Test.sol";
import {PrivateKeyEnv} from "../script/PrivateKeyEnv.sol";

/// @dev Exposes the inherited helper. Deliberately not the test contract itself: forge-std's Script and Test bases both
/// declare `vm`, so a contract inheriting both would not compile.
contract PrivateKeyEnvHarness is PrivateKeyEnv {
    function deployerKey() external view returns (uint256) {
        return _deployerKey();
    }

    function parseDeployerKey(string memory raw) external view returns (uint256) {
        return _parseDeployerKey(raw);
    }
}

/// @notice The two forms the repository documents for the deployer key, proven at the point the value is consumed.
contract PrivateKeyEnvTest is Test {
    uint256 internal constant KEY = 0x59c6995e998f97a5a0044966f0945389dc9e86dae88c7a8412f4603b6b78690d;
    string internal constant KEY_BARE = "59c6995e998f97a5a0044966f0945389dc9e86dae88c7a8412f4603b6b78690d";

    PrivateKeyEnvHarness internal harness = new PrivateKeyEnvHarness();

    /// The trap this contract exists for: the same value in the form the workspace secret stores it.
    function test_bareHexIsAcceptedAndMatchesThePrefixedForm() public view {
        assertEq(harness.parseDeployerKey(KEY_BARE), KEY);
        assertEq(harness.parseDeployerKey(string.concat("0x", KEY_BARE)), KEY);
    }

    function test_environmentReadAcceptsEitherForm() public {
        vm.setEnv("PRIVATE_KEY", KEY_BARE);
        uint256 bare = harness.deployerKey();
        vm.setEnv("PRIVATE_KEY", string.concat("0x", KEY_BARE));
        uint256 prefixed = harness.deployerKey();
        assertEq(bare, KEY);
        assertEq(prefixed, KEY);
        assertEq(vm.addr(bare), vm.addr(prefixed));
    }

    function test_uppercasePrefixAndDigitsAreAccepted() public {
        vm.setEnv("PRIVATE_KEY", "0X59C6995E998F97A5A0044966F0945389DC9E86DAE88C7A8412F4603B6B78690D");
        assertEq(harness.deployerKey(), KEY);
    }

    /// A gate step mis-read this abort as one of its own guard refusals on 2 October 2026, so the message matters.
    function test_shortValueRevertsNamingBothAcceptedForms() public {
        vm.expectRevert("PRIVATE_KEY: expected 0x plus 64 hex digits, or the 64 digits bare");
        harness.parseDeployerKey("59c6995e998f97a5a0044966f0945389dc9e86dae88c7a8412f4603b6b78690");
    }

    function test_66CharacterValueWithoutThePrefixReverts() public {
        vm.expectRevert("PRIVATE_KEY: a 66-character value must start with 0x");
        harness.parseDeployerKey("XX59c6995e998f97a5a0044966f0945389dc9e86dae88c7a8412f4603b6b78690d");
    }

    function test_nonHexDigitReverts() public {
        vm.expectRevert();
        harness.parseDeployerKey("59c6995e998f97a5a0044966f0945389dc9e86dae88c7a8412f4603b6b78690z");
    }
}
