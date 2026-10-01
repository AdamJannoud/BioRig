"""Pure helpers in dashboard.chain: stats formatting, revert decoding, and the TBA derivation checked per chain.

Celo Sepolia's expectation is the real token #1, read from chain once and pinned. Celo mainnet has no deployment,
so its expectation is counterfactual: the address the canonical registry on Celo mainnet returns from
account(ACCOUNT_IMPL, salt, 42220, PROXY, 1) for token #1's salt, read once over https://forno.celo.org and pinned.
Neither number comes from the derivation under test."""
import pytest

from dashboard.chain import (TreeStats, compute_tba_address, decode_revert, error_selectors, format_tree_stats,
                             load_abi, short_hex, tba_salt)
from dashboard.config import chain_config

PROXY = "0x21ab8B36177F65ce69e04e281E4aFf3Db6b5f7E6"
ACCOUNT_IMPL = "0x3d8a53dB1bBcab6D47097B25080527e5560C5165"
PLANTER = "0xb5aB2054b43040593805Cf662A938eFE924F2778"
NULLIFIER_1 = bytes.fromhex("f8fa2658012341dda81dbb7d27a6bb0accd68b63e618001d8ccbed1375dbf667")
TBA_1 = "0x61bd8BEcE5a38209Fc10d4DA3f837EE83a10124a"  # live token #1 on Celo Sepolia
TBA_BY_CHAIN = {11142220: TBA_1, 42220: "0xF95397a38B1b92F28A6E2e80f3C75559551CAF7D"}


@pytest.fixture
def registry(chain_id):
    """The registry the chain config wires into initialize, checksummed as the derivation returns addresses."""
    from web3 import Web3

    return Web3.to_checksum_address(chain_config(chain_id).erc6551_registry)


def test_tba_derivation_matches_the_registry_on_each_chain(chain_id, registry):
    salt = tba_salt(1, PLANTER, NULLIFIER_1)
    assert registry == "0x000000006551c19487814612e58FE06813775758"
    assert compute_tba_address(registry, ACCOUNT_IMPL, salt, chain_id, PROXY, 1) == TBA_BY_CHAIN[chain_id]


def test_tba_depends_on_every_input(chain_id, registry):
    want = TBA_BY_CHAIN[chain_id]
    other_chain = next(c for c in TBA_BY_CHAIN if c != chain_id)
    salt = tba_salt(1, PLANTER, NULLIFIER_1)
    assert compute_tba_address(registry, ACCOUNT_IMPL, salt, chain_id, PROXY, 2) != want
    assert compute_tba_address(registry, ACCOUNT_IMPL, salt, other_chain, PROXY, 1) == TBA_BY_CHAIN[other_chain]
    assert compute_tba_address(registry, ACCOUNT_IMPL, tba_salt(2, PLANTER, NULLIFIER_1), chain_id, PROXY, 1) != want
    assert compute_tba_address("0x" + "11" * 20, ACCOUNT_IMPL, salt, chain_id, PROXY, 1) != want


def test_format_tree_stats_rows():
    s = TreeStats.from_tuple((24, 1312, 1790796368, TBA_1.lower(), True, NULLIFIER_1))
    rows = dict(format_tree_stats(s, nullifier_active=True))
    assert rows["dbh"] == "24 cm"
    assert rows["biomass"] == "1,312 kg"
    assert rows["lastUpdated"] == "1,790,796,368  (2026-09-30 19:26:08 UTC)"
    assert rows["tbaAddress"] == TBA_1  # checksummed
    assert rows["isAlive"] == "true"
    assert rows["spatialNullifier"] == "0x" + NULLIFIER_1.hex()
    assert rows["nullifierActive"] == "true"
    assert [k for k, _ in format_tree_stats(s)] == ["dbh", "biomass", "lastUpdated", "tbaAddress", "isAlive",
                                                    "spatialNullifier"]


def test_dead_tree_formatting():
    s = TreeStats.from_tuple((1, 2, 0, TBA_1, False, NULLIFIER_1))
    assert dict(format_tree_stats(s, False))["isAlive"] == "false"
    assert dict(format_tree_stats(s, False))["nullifierActive"] == "false"


def test_decode_revert_known_errors():
    sel = error_selectors(load_abi("BioRigCoreV5"))
    assert decode_revert("0xf0352c1b", sel) == "InvalidTree()"  # what getTreeStats(2) returns live today
    assert decode_revert(bytes.fromhex("f0352c1b"), sel) == "InvalidTree()"
    assert "NullifierInUse()" in sel.values() and "InvalidNullifier()" in sel.values()
    assert "AccessControlUnauthorizedAccount(address,bytes32)" in sel.values()
    assert decode_revert(None, sel) == "reverted without data"
    assert decode_revert("0xdeadbeef", sel) == "unknown error 0xdeadbeef"


def test_short_hex():
    assert short_hex(PROXY) == "0x21ab8B36…f7E6"
    assert short_hex("0x1234") == "0x1234"
