"""The operator view's live reads (getTreeStats, ownerOf, tokenURI) against an RPC whose transport drops. A fake
provider plays eth_call, so this runs offline, and the retry delays are recorded instead of slept. A revert is the
contract's answer, so it must come back at once rather than be retried like a fault."""
import threading

import pytest
import requests
from eth_abi import encode as abi_encode
from eth_utils import keccak, to_checksum_address
from web3 import Web3
from web3.exceptions import ContractLogicError
from web3.providers import BaseProvider

from dashboard import chain as chain_mod
from dashboard.config import Resolution, Settings

PROXY = "0x04db169ddf8abb80943161c01b2a71dc40384e64"
OWNER = to_checksum_address("0x" + "5a" * 20)
TBA = to_checksum_address("0x" + "7b" * 20)
NULLIFIER = bytes(range(32))
URI = "data:application/json;base64,eyJuYW1lIjoiVHJlZSAjMSJ9"
STATS = (24, 300, 1_700_000_000, TBA, True, NULLIFIER)


def selector(signature: str) -> str:
    return "0x" + keccak(text=signature)[:4].hex()


ANSWERS = {
    selector("getTreeStats(uint256)"): abi_encode(["(uint96,uint96,uint64,address,bool,bytes32)"], [STATS]),
    selector("ownerOf(uint256)"): abi_encode(["address"], [OWNER]),
    selector("tokenURI(uint256)"): abi_encode(["string"], [URI]),
}
# Error(string) "ERC721NonexistentToken", the way a node reports a revert: JSON-RPC error 3 carrying the revert data.
REVERT = {"code": 3, "message": "execution reverted",
          "data": selector("Error(string)") + abi_encode(["string"], ["ERC721NonexistentToken"]).hex()}

READS = [
    ("get_tree_stats", chain_mod.TreeStats.from_tuple(STATS)),
    ("owner_of", OWNER),
    ("token_uri", URI),
]


class FlakyRpc(BaseProvider):
    """Answers eth_call from ANSWERS, and eth_chainId, which web3 asks first. The first `errors` eth_calls raise a
    transport error; with revert, every eth_call answers with REVERT instead."""

    def __init__(self, errors=0, revert=False):
        super().__init__()
        self.errors, self.revert, self.calls = errors, revert, 0

    def make_request(self, method, params):
        if method == "eth_chainId":
            return {"jsonrpc": "2.0", "id": 1, "result": hex(42220)}
        assert method == "eth_call", method
        self.calls += 1
        if self.calls <= self.errors:
            raise requests.ConnectionError("connection reset by peer")
        if self.revert:
            return {"jsonrpc": "2.0", "id": 1, "error": REVERT}
        return {"jsonrpc": "2.0", "id": 1, "result": "0x" + ANSWERS[params[0]["data"][:10]].hex()}


@pytest.fixture
def slept(monkeypatch):
    """The delays this test's thread slept. Log-walk workers an earlier test left running sleep through the same
    module-level _sleep, so theirs are dropped rather than counted against these reads."""
    delays, me = [], threading.get_ident()
    monkeypatch.setattr(chain_mod, "_sleep", lambda d: delays.append(d) if threading.get_ident() == me else None)
    return delays


def make_chain(provider: FlakyRpc) -> chain_mod.Chain:
    settings = Settings(rpc_url="http://127.0.0.1:9", chain_id=42220, explorer_url="https://celoscan.io",
                        proxy=Resolution(PROXY, "test", deploy_block=0))
    chain = chain_mod.Chain(settings)
    chain.w3 = Web3(provider)
    chain.core = chain.w3.eth.contract(address=chain.proxy, abi=chain.core_abi)
    return chain


@pytest.mark.parametrize("read, want", READS)
def test_the_reads_answer_without_a_fault(slept, read, want):
    rpc = FlakyRpc()
    assert getattr(make_chain(rpc), read)(1) == want
    assert rpc.calls == 1 and slept == []


@pytest.mark.parametrize("read, want", READS)
def test_a_transport_fault_is_retried(slept, read, want):
    rpc = FlakyRpc(errors=1)
    assert getattr(make_chain(rpc), read)(1) == want
    assert rpc.calls == 2
    assert slept == list(chain_mod.TRANSIENT_RETRY_DELAYS[:1])


@pytest.mark.parametrize("read, want", READS)
def test_every_retry_but_the_last_can_fail(slept, read, want):
    retries = len(chain_mod.TRANSIENT_RETRY_DELAYS)
    rpc = FlakyRpc(errors=retries)
    assert getattr(make_chain(rpc), read)(1) == want
    assert rpc.calls == retries + 1
    assert slept == list(chain_mod.TRANSIENT_RETRY_DELAYS)


@pytest.mark.parametrize("read", [r for r, _ in READS])
def test_a_revert_is_raised_at_once(slept, read):
    rpc = FlakyRpc(revert=True)
    with pytest.raises(ContractLogicError):
        getattr(make_chain(rpc), read)(1)
    assert rpc.calls == 1 and slept == []


@pytest.mark.parametrize("read", [r for r, _ in READS])
def test_a_persistent_transport_fault_is_raised_not_swallowed(slept, read):
    rpc = FlakyRpc(errors=10**6)
    with pytest.raises(requests.ConnectionError):
        getattr(make_chain(rpc), read)(1)
    assert rpc.calls == len(chain_mod.TRANSIENT_RETRY_DELAYS) + 1
    assert slept == list(chain_mod.TRANSIENT_RETRY_DELAYS)
