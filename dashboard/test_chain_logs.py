"""find_mint against an RPC that lies the way forno does: eth_getLogs answers [] for a range that holds logs, the
receipt of a mined tx comes back "not found", and the transport drops. A fake provider plays the RPC, so this runs
offline, and the retry delays are recorded instead of slept."""
import threading

import pytest
import requests
from eth_utils import keccak, to_checksum_address
from web3 import Web3
from web3.providers import BaseProvider

from dashboard import chain as chain_mod
from dashboard.config import Resolution, Settings

PROXY = "0x04db169ddf8abb80943161c01b2a71dc40384e64"
PLANTER = to_checksum_address("0x" + "5a" * 20)
TBA = to_checksum_address("0x" + "7b" * 20)
NULLIFIER = bytes(range(32))
TX = "0x" + "c4" * 32
DEPLOY, CHUNK, CHUNKS = 1_000, 100, 24
HEAD = DEPLOY + CHUNK * CHUNKS - 1
MINT_BLOCK = DEPLOY + 12 * CHUNK + 34  # in the 13th chunk, so a walk has to get past a dozen empty ones first
ASKS = 1 + len(chain_mod.EMPTY_CONFIRM_DELAYS)  # eth_getLogs calls a chunk costs when every answer is empty

TREE_MINTED = "0x" + keccak(text="TreeMinted(uint256,address,bytes32)").hex()
TRANSFER = "0x" + keccak(text="Transfer(address,address,uint256)").hex()
GROWTH = "0x" + keccak(text="GrowthUpdated(uint256,uint96,uint96)").hex()


def word(value) -> str:
    if isinstance(value, int):
        return "0x" + value.to_bytes(32, "big").hex()
    if isinstance(value, bytes):
        return "0x" + value.rjust(32, b"\0").hex()
    return "0x" + bytes.fromhex(value[2:]).rjust(32, b"\0").hex()


def log(block: int, topics: list[str], data: str = "0x", index: int = 0) -> dict:
    return {"address": PROXY, "topics": topics, "data": data, "blockNumber": hex(block), "transactionHash": TX,
            "transactionIndex": "0x0", "blockHash": "0x" + "ab" * 32, "logIndex": hex(index), "removed": False}


MINT_LOG = log(MINT_BLOCK, [TREE_MINTED, word(1), word(TBA), word(NULLIFIER)], index=1)
TRANSFER_LOG = log(MINT_BLOCK, [TRANSFER, word(0), word(PLANTER), word(1)], index=0)
GROWTH_LOGS = [log(b, [GROWTH, word(1)], "0x" + (24).to_bytes(32, "big").hex() + (300).to_bytes(32, "big").hex())
               for b in (DEPLOY + 5 * CHUNK + 1, HEAD - 3)]


class FakeForno(BaseProvider):
    """Answers eth_blockNumber, eth_getLogs and eth_getTransactionReceipt from the logs above.

    empty_mint_reads: the first n eth_getLogs calls whose range holds the mint answer [] anyway.
    receipt_misses:   the first n receipt calls answer null (web3 raises TransactionNotFound).
    log_errors:       the first n eth_getLogs calls raise a transport error."""

    def __init__(self, empty_mint_reads=0, receipt_misses=0, log_errors=0):
        super().__init__()
        self.empty_mint_reads, self.receipt_misses, self.log_errors = empty_mint_reads, receipt_misses, log_errors
        self.lock = threading.Lock()
        self.log_calls = self.mint_chunk_calls = self.receipt_calls = 0

    def make_request(self, method, params):
        with self.lock:
            return {"jsonrpc": "2.0", "id": 1, "result": self._answer(method, params)}

    def _answer(self, method, params):
        if method == "eth_blockNumber":
            return hex(HEAD)
        if method == "eth_getTransactionReceipt":
            self.receipt_calls += 1
            if self.receipt_calls <= self.receipt_misses:
                return None
            return {"transactionHash": TX, "blockNumber": hex(MINT_BLOCK), "blockHash": "0x" + "ab" * 32,
                    "transactionIndex": "0x0", "from": PLANTER, "to": PROXY, "status": "0x1", "gasUsed": "0x5208",
                    "cumulativeGasUsed": "0x5208", "contractAddress": None, "logsBloom": "0x" + "00" * 256,
                    "effectiveGasPrice": "0x1", "type": "0x2", "logs": [TRANSFER_LOG, MINT_LOG]}
        if method == "eth_getLogs":
            self.log_calls += 1
            if self.log_calls <= self.log_errors:
                raise requests.ConnectionError("connection reset by peer")
            f = params[0]
            lo, hi = int(f["fromBlock"], 16), int(f["toBlock"], 16)
            if lo <= MINT_BLOCK <= hi:
                self.mint_chunk_calls += 1
                if self.mint_chunk_calls <= self.empty_mint_reads:
                    return []
            want = f.get("topics") or []
            return [entry for entry in (MINT_LOG, *GROWTH_LOGS)
                    if lo <= int(entry["blockNumber"], 16) <= hi
                    and all(w is None or w.lower() == t for w, t in zip(want, entry["topics"]))]
        raise NotImplementedError(method)


@pytest.fixture
def slept(monkeypatch):
    delays = []
    monkeypatch.setattr(chain_mod, "_sleep", delays.append)
    return delays


def make_chain(provider: FakeForno) -> chain_mod.Chain:
    settings = Settings(rpc_url="http://127.0.0.1:9", chain_id=42220, explorer_url="https://celoscan.io",
                        proxy=Resolution(PROXY, "test", deploy_block=DEPLOY))
    chain = chain_mod.Chain(settings)
    chain.w3 = Web3(provider)
    chain.core = chain.w3.eth.contract(address=chain.proxy, abi=chain.core_abi)
    return chain


def assert_token_1(record):
    assert record == chain_mod.MintRecord(1, TX, MINT_BLOCK, PLANTER, NULLIFIER, TBA)


@pytest.mark.parametrize("k", [1, 3])
def test_spurious_empty_answers_on_the_mint_chunk_are_re_asked(slept, k):
    rpc = FakeForno(empty_mint_reads=k)
    assert_token_1(make_chain(rpc).find_mint(1, chunk=CHUNK))
    assert rpc.mint_chunk_calls == k + 1  # found inside the first walk's confirmations
    assert slept and set(slept) <= set(chain_mod.EMPTY_CONFIRM_DELAYS)  # backed off, never a bare re-ask


def test_a_walk_that_misses_the_mint_chunk_is_repeated(slept):
    rpc = FakeForno(empty_mint_reads=ASKS + 1)  # every confirmation of walk 1 lies, and the first ask of walk 2
    assert_token_1(make_chain(rpc).find_mint(1, chunk=CHUNK))
    assert rpc.mint_chunk_calls == ASKS + 2


def test_a_missed_receipt_still_resolves_the_planter(slept):
    rpc = FakeForno(receipt_misses=1)
    assert_token_1(make_chain(rpc).find_mint(1, chunk=CHUNK))
    assert rpc.receipt_calls == 2


def test_a_withheld_receipt_says_so(slept):
    rpc = FakeForno(receipt_misses=10**9)
    with pytest.raises(RuntimeError, match=f"did not return the receipt for tx {TX}.*returned that tx's log"):
        make_chain(rpc).find_mint(1, chunk=CHUNK)
    assert rpc.receipt_calls == ASKS


def test_an_absent_token_raises_lookup_error_within_the_retry_budget(slept):
    rpc = FakeForno()
    with pytest.raises(LookupError, match=f"no TreeMinted event for token 2 between blocks {DEPLOY} and {HEAD}"):
        make_chain(rpc).find_mint(2, chunk=CHUNK)
    assert rpc.log_calls == chain_mod.MINT_WALKS * CHUNKS * ASKS
    assert rpc.receipt_calls == 0


def test_transport_errors_are_retried(slept):
    rpc = FakeForno(log_errors=len(chain_mod.TRANSIENT_RETRY_DELAYS))
    assert_token_1(make_chain(rpc).find_mint(1, chunk=CHUNK))


def test_a_persistent_transport_error_is_raised_not_swallowed(slept):
    rpc = FakeForno(log_errors=10**9)
    with pytest.raises(requests.ConnectionError, match="connection reset"):
        make_chain(rpc).find_mint(1, chunk=CHUNK)
    with rpc.lock:
        assert 1 + len(chain_mod.TRANSIENT_RETRY_DELAYS) <= rpc.log_calls <= CHUNKS * (1 + len(chain_mod.TRANSIENT_RETRY_DELAYS))


def test_token_logs_collects_every_chunk_in_block_order(slept):
    chain = make_chain(FakeForno())
    growth = chain.token_logs(chain.core.events.GrowthUpdated(), 1, chunk=CHUNK)
    assert [int(g.blockNumber) for g in growth] == [int(g["blockNumber"], 16) for g in GROWTH_LOGS]
    assert [(g.args.newDBH, g.args.newBiomass) for g in growth] == [(24, 300)] * 2
