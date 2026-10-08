"""web3.py access to BioRigCoreV5 behind the ERC1967Proxy.

Pure helpers (no network) come first so they can be unit-tested: TBA derivation, stats formatting and
revert decoding. The Chain class below does the reads, the eth_call simulation and the signed broadcast.
The private key stays inside Chain; nothing here returns or logs it.
"""
from __future__ import annotations

import json
import time
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeout
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import requests
from eth_abi import encode as abi_encode
from eth_utils import keccak, to_checksum_address
from web3.exceptions import ContractLogicError, TransactionNotFound, Web3Exception
from web3.logs import DISCARD
from web3.providers.rpc.utils import ExceptionRetryConfiguration  # not re-exported by the package on web3 8

from .config import Settings

ABI_DIR = Path(__file__).resolve().parent / "abi"
ERC1967_IMPLEMENTATION_SLOT = 0x360894A13BA1A3210667C828492DB98DCA3E2076CC3735A920A3CA505D382BBC
ERC6551_ACCOUNT_INTERFACE_ID = bytes.fromhex("6faff5f1")
# ERC-1167 proxy pieces the canonical ERC-6551 registry wraps around the implementation address.
_ERC1167_HEADER = bytes.fromhex("3d60ad80600a3d3981f3363d3d373d3d3d363d73")
_ERC1167_FOOTER = bytes.fromhex("5af43d82803e903d91602b57fd5bf3")

# forno (Celo's public RPC) answers eth_getLogs with [] for a range that provably holds logs about a third of the
# time, and eth_getTransactionReceipt with "not found" for a mined tx the same way. So an empty answer is unproven:
# it is re-asked after each of these delays and only accepted when every answer was empty (~1% at a 1/3 rate).
EMPTY_CONFIRM_DELAYS = (0.25, 0.5, 1.0, 2.0)
# Delays between retries of a read that raised a transport or RPC error; after the last, the error is raised.
TRANSIENT_RETRY_DELAYS = (0.25, 0.5, 1.0)
# A whole walk can still miss the mint chunk, so a walk that finds nothing is repeated up to this many walks.
MINT_WALKS = 3
LOG_WORKERS = 8  # chunks read concurrently; each one may spend ~4 s confirming an empty answer
_TRANSIENT = (OSError, Web3Exception)  # requests' ConnectionError/Timeout are OSErrors
_sleep = time.sleep  # tests replace this to run the delays instantly

# web3's HTTPProvider default retries a failed call 5 times; at the old 30 s timeout one unreachable RPC call blocked
# for 152 s, which is what left a cold hosted dashboard blank. One attempt at 8 s keeps every call under ~10 s; the
# log reads that need resilience against a flaky RPC already retry in Chain._rpc.
RPC_TIMEOUT_S = 8
# errors is spelled out because web3 8 validates it as a sequence; this is the tuple the provider's own default uses.
RPC_RETRY = ExceptionRetryConfiguration(errors=(ConnectionError, requests.HTTPError, requests.Timeout),
                                        retries=1, backoff_factor=0.1)
# The whole startup probe (chain id, overview, verifier role) must answer inside this, or the dashboard says the
# chain is slow and offers a retry instead of hanging its first render.
PROBE_BUDGET_S = 20


def load_abi(name: str) -> list:
    return json.loads((ABI_DIR / f"{name}.json").read_text())


# --------------------------------------------------------------------------- pure helpers

def tba_salt(token_id: int, planter: str, spatial_nullifier: bytes) -> bytes:
    """The salt mintTree passes to createAccount: keccak256(abi.encodePacked(tokenId, planter, nullifier))."""
    if len(spatial_nullifier) != 32:
        raise ValueError("spatial_nullifier must be 32 bytes")
    return keccak(token_id.to_bytes(32, "big") + bytes.fromhex(planter[2:].lower()) + spatial_nullifier)


def compute_tba_address(registry: str, implementation: str, salt: bytes, chain_id: int,
                        token_contract: str, token_id: int) -> str:
    """Offline CREATE2 derivation, identical to ERC6551Registry.account()."""
    code = (_ERC1167_HEADER + bytes.fromhex(implementation[2:]) + _ERC1167_FOOTER
            + abi_encode(["bytes32", "uint256", "address", "uint256"], [salt, chain_id, token_contract, token_id]))
    digest = keccak(b"\xff" + bytes.fromhex(registry[2:]) + salt + keccak(code))
    return to_checksum_address(digest[12:])


@dataclass(frozen=True)
class TreeStats:
    dbh: int
    biomass: int
    last_updated: int
    tba_address: str
    is_alive: bool
    spatial_nullifier: bytes

    @classmethod
    def from_tuple(cls, raw) -> "TreeStats":
        dbh, biomass, last_updated, tba, alive, nullifier = raw
        return cls(int(dbh), int(biomass), int(last_updated), to_checksum_address(tba), bool(alive), bytes(nullifier))


def short_hex(value: str, head: int = 8, tail: int = 4) -> str:
    return value if len(value) <= 2 + head + tail else f"{value[:2 + head]}…{value[-tail:]}"


def format_timestamp(ts: int) -> str:
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def format_tree_stats(stats: TreeStats, nullifier_active: bool | None = None) -> list[tuple[str, str]]:
    """Rows for the 'Live state' panel, in the order of the TreeStats struct."""
    rows = [
        ("dbh", f"{stats.dbh:,} cm"),
        ("biomass", f"{stats.biomass:,} kg"),
        ("lastUpdated", f"{stats.last_updated:,}  ({format_timestamp(stats.last_updated)})"),
        ("tbaAddress", stats.tba_address),
        ("isAlive", "true" if stats.is_alive else "false"),
        ("spatialNullifier", "0x" + stats.spatial_nullifier.hex()),
    ]
    if nullifier_active is not None:
        rows.append(("nullifierActive", "true" if nullifier_active else "false"))
    return rows


def error_selectors(abi: list) -> dict[str, str]:
    """Map 4-byte selector hex -> error signature for every custom error in the ABI."""
    out = {}
    for item in abi:
        if item.get("type") == "error":
            sig = f"{item['name']}({','.join(i['type'] for i in item.get('inputs', []))})"
            out["0x" + keccak(text=sig)[:4].hex()] = sig
    return out


def decode_revert(data: str | bytes | None, selectors: dict[str, str]) -> str:
    if data is None:
        return "reverted without data"
    if isinstance(data, (bytes, bytearray)):
        data = "0x" + bytes(data).hex()
    data = data.lower()
    if len(data) < 10:
        return f"reverted ({data or 'empty'})"
    return selectors.get(data[:10], f"unknown error {data[:10]}")


# --------------------------------------------------------------------------- network

@dataclass(frozen=True)
class MintRecord:
    token_id: int
    tx_hash: str
    block_number: int
    planter: str
    spatial_nullifier: bytes
    tba_event: str


@dataclass(frozen=True)
class TbaCheck:
    derived_offline: str
    registry_account: str
    stored: str
    bound_token: tuple[int, str, int]
    supports_6551: bool

    @property
    def ok(self) -> bool:
        return self.derived_offline == self.registry_account == self.stored


@dataclass(frozen=True)
class Probe:
    """What the dashboard reads once before it renders a view."""
    rpc_chain: int
    overview: dict
    is_verifier: bool


class ProbeTimeout(TimeoutError):
    """The startup probe did not finish inside its wall-clock budget."""


@dataclass(frozen=True)
class Simulation:
    ok: bool
    token_id: int | None
    gas: int | None
    error: str | None
    sender: str
    calldata: str


class Chain:
    def __init__(self, settings: Settings):
        from web3 import Web3

        self.settings = settings
        self.w3 = Web3(Web3.HTTPProvider(settings.rpc_url, request_kwargs={"timeout": RPC_TIMEOUT_S},
                                         exception_retry_configuration=RPC_RETRY))
        self.core_abi = load_abi("BioRigCoreV5")
        self.selectors = error_selectors(self.core_abi)
        self.proxy = to_checksum_address(settings.proxy.address)
        self.core = self.w3.eth.contract(address=self.proxy, abi=self.core_abi)
        self._account = None
        if settings.private_key:
            from eth_account import Account
            self._account = Account.from_key(settings.private_key)

    # ---- identity
    @property
    def signer(self) -> str | None:
        return self._account.address if self._account else None

    def rpc_chain_id(self) -> int:
        return int(self.w3.eth.chain_id)

    def assert_chain(self) -> int:
        cid = self.rpc_chain_id()
        if cid != self.settings.chain_id:
            raise RuntimeError(f"RPC reports chain {cid}, settings expect {self.settings.chain_id}")
        return cid

    def signer_is_verifier(self) -> bool:
        if not self.signer:
            return False
        role = self.core.functions.VERIFIER_ROLE().call()
        return bool(self.core.functions.hasRole(role, self.signer).call())

    def overview(self) -> dict:
        f = self.core.functions
        return {
            "name": f.name().call(),
            "symbol": f.symbol().call(),
            "paused": f.paused().call(),
            "registry": f.erc6551Registry().call(),
            "implementation": f.erc6551Implementation().call(),
            "boundChainId": int(f.chainId().call()),
            "bufferPool": f.bufferPool().call(),
            "block": int(self.w3.eth.block_number),
        }

    def probe(self, budget_s: float = PROBE_BUDGET_S) -> Probe:
        """assert_chain, overview and signer_is_verifier, finished inside budget_s of wall clock or ProbeTimeout.

        Each call is bounded by RPC_TIMEOUT_S, but overview alone is eight sequential round trips, so a slow RPC
        could still add up. The reads run on a worker thread the caller stops waiting for at the deadline; the
        thread itself ends at its next call's timeout and its result is dropped."""
        pool = ThreadPoolExecutor(max_workers=1)
        future = pool.submit(lambda: Probe(self.assert_chain(), self.overview(), self.signer_is_verifier()))
        try:
            return future.result(timeout=budget_s)
        except FutureTimeout:
            if future.done():  # the reads themselves raised a TimeoutError (the builtin one, on 3.11): pass it on
                raise
            raise ProbeTimeout(f"no answer from {self.settings.rpc_url} within {budget_s:g} s") from None
        finally:
            pool.shutdown(wait=False, cancel_futures=True)

    def core_implementation(self) -> str:
        """BioRigCoreV5 implementation behind the proxy, read from the ERC-1967 implementation slot."""
        word = self.w3.eth.get_storage_at(self.proxy, ERC1967_IMPLEMENTATION_SLOT)
        return to_checksum_address(bytes(word)[-20:])

    # ---- reads
    def _view(self, call):
        """A view call(), retried after each TRANSIENT_RETRY_DELAYS on a transport or RPC error; the last error is
        raised. A revert is the contract's answer, not a fault, so ContractLogicError is raised at once. Unlike _rpc
        this cannot share _TRANSIENT as is: Web3Exception covers reverts, which must never be retried."""
        for delay in (*TRANSIENT_RETRY_DELAYS, None):
            try:
                return call()
            except ContractLogicError:
                raise
            except _TRANSIENT:
                if delay is None:
                    raise
                _sleep(delay)

    def get_tree_stats(self, token_id: int) -> TreeStats:
        return TreeStats.from_tuple(self._view(self.core.functions.getTreeStats(token_id).call))

    def gas_price_wei(self) -> int:
        return int(self.w3.eth.gas_price)

    def is_nullifier_active(self, nullifier: bytes) -> bool:
        return bool(self.core.functions.isNullifierActive(nullifier).call())

    def owner_of(self, token_id: int) -> str:
        return self._view(self.core.functions.ownerOf(token_id).call)

    def token_uri(self, token_id: int) -> str:
        return self._view(self.core.functions.tokenURI(token_id).call)

    # ---- log reads that survive an RPC answering empty for a range that holds logs
    def _rpc(self, call):
        """call(), retried after each TRANSIENT_RETRY_DELAYS on a transport or RPC error; the last error is raised."""
        for delay in (*TRANSIENT_RETRY_DELAYS, None):
            try:
                return call()
            except TransactionNotFound:
                raise  # an answer, not a transport fault: get_receipt confirms it
            except _TRANSIENT:
                if delay is None:
                    raise
                _sleep(delay)

    def _get_logs_confirmed(self, event, lo: int, hi: int, token_id: int) -> list:
        """event's logs for token_id in [lo, hi]. A non-empty answer is returned at once; an empty one is re-asked
        after each EMPTY_CONFIRM_DELAYS and accepted only when every answer was empty."""
        for delay in (*EMPTY_CONFIRM_DELAYS, None):
            logs = self._rpc(lambda: event.get_logs(
                from_block=lo, to_block=hi, argument_filters={"tokenId": token_id}))
            if logs or delay is None:
                return list(logs)
            _sleep(delay)

    def _log_ranges(self, chunk: int) -> tuple[int, int, list[tuple[int, int]]]:
        start = self.settings.proxy.deploy_block or 0
        head = int(self._rpc(lambda: self.w3.eth.block_number))
        return start, head, [(lo, min(lo + chunk - 1, head)) for lo in range(start, head + 1, chunk)]

    def _walk(self, event, token_id: int, ranges: list[tuple[int, int]], first_only: bool) -> list:
        """Confirmed reads of every range, LOG_WORKERS at a time, consumed in block order. With first_only the
        lowest range holding logs wins and the reads still queued are cancelled. A read error is raised."""
        pool = ThreadPoolExecutor(max_workers=LOG_WORKERS)
        futures = [pool.submit(self._get_logs_confirmed, event, lo, hi, token_id) for lo, hi in ranges]
        out = []
        try:
            for fut in futures:
                logs = fut.result()
                out.extend(logs)
                if logs and first_only:
                    break
        finally:
            pool.shutdown(wait=False, cancel_futures=True)
        return out

    def token_logs(self, event, token_id: int, chunk: int = 5_000) -> list:
        """Every log of event for token_id since the proxy's deploy block, in block order, read in chunks."""
        return self._walk(event, token_id, self._log_ranges(chunk)[2], first_only=False)

    def get_receipt(self, tx_hash):
        """The receipt of a tx a log already named. 'Not found' is re-asked like an empty log answer, since forno
        returns it for mined txs too; if it persists the error says the RPC withheld a receipt it should have."""
        for delay in (*EMPTY_CONFIRM_DELAYS, None):
            try:
                receipt = self._rpc(lambda: self.w3.eth.get_transaction_receipt(tx_hash))
                if receipt is not None:
                    return receipt
            except TransactionNotFound:
                pass
            if delay is None:
                h = tx_hash if isinstance(tx_hash, str) else "0x" + bytes(tx_hash).hex()
                raise RuntimeError(f"the RPC did not return the receipt for tx {h} after "
                                   f"{len(EMPTY_CONFIRM_DELAYS) + 1} asks, though it returned that tx's log")
            _sleep(delay)

    def find_mint(self, token_id: int, chunk: int = 5_000) -> MintRecord:
        """Locate the TreeMinted event for token_id and read the planter from the mint's Transfer log.

        Chunked at 5,000 blocks: Celo mainnet's forno rejects a wider eth_getLogs ("max block range 5000"). Every
        chunk read is confirmed (see _get_logs_confirmed), and a walk that finds nothing is repeated up to MINT_WALKS
        times before the token is declared absent."""
        event = self.core.events.TreeMinted()
        for _ in range(MINT_WALKS):
            start, head, ranges = self._log_ranges(chunk)
            logs = self._walk(event, token_id, ranges, first_only=True)
            if logs:
                break
        else:
            raise LookupError(f"no TreeMinted event for token {token_id} between blocks {start} and {head}")
        log = logs[0]
        receipt = self.get_receipt(log.transactionHash)
        planter = None
        for t in self.core.events.Transfer().process_receipt(receipt, errors=DISCARD):
            if int(t.args.tokenId) == token_id and int(t.args["from"], 16) == 0:
                planter = t.args.to
        if planter is None:
            raise RuntimeError(f"mint tx for token {token_id} has no Transfer from 0x0")
        return MintRecord(token_id, "0x" + log.transactionHash.hex().removeprefix("0x"),
                          int(log.blockNumber), planter, bytes(log.args.spatialNullifier), log.args.tba)

    def check_tba(self, token_id: int, record: MintRecord | None = None) -> TbaCheck:
        """Derive the TBA from (registry, implementation, chainId, proxy, tokenId, salt) three ways."""
        ov = self.overview()
        record = record or self.find_mint(token_id)
        salt = tba_salt(token_id, record.planter, record.spatial_nullifier)
        offline = compute_tba_address(ov["registry"], ov["implementation"], salt, ov["boundChainId"],
                                      self.proxy, token_id)
        registry = self.w3.eth.contract(address=ov["registry"], abi=load_abi("ERC6551Registry"))
        on_registry = registry.functions.account(ov["implementation"], salt, ov["boundChainId"],
                                                 self.proxy, token_id).call()
        stored = self.get_tree_stats(token_id).tba_address
        account = self.w3.eth.contract(address=to_checksum_address(stored), abi=load_abi("ERC6551Account"))
        bound = account.functions.token().call()
        supports = account.functions.supportsInterface(ERC6551_ACCOUNT_INTERFACE_ID).call()
        return TbaCheck(offline, to_checksum_address(on_registry), stored,
                        (int(bound[0]), to_checksum_address(bound[1]), int(bound[2])), bool(supports))

    # ---- mint
    def _mint_fn(self, planter: str, nullifier: bytes, dbh: int, biomass: int):
        for name, v in (("initialDBH", dbh), ("initialBiomass", biomass)):
            if not 0 <= v < 2**96:
                raise ValueError(f"{name} {v} does not fit uint96")
        return self.core.functions.mintTree(to_checksum_address(planter), nullifier, dbh, biomass)

    def simulate_mint(self, planter: str, nullifier: bytes, dbh: int, biomass: int) -> Simulation:
        """eth_call + eth_estimateGas from the signer against the latest block. Never broadcasts."""
        from web3.exceptions import ContractCustomError, ContractLogicError

        if not self.signer:
            raise RuntimeError("PRIVATE_KEY is not configured; cannot simulate from the verifier account")
        fn = self._mint_fn(planter, nullifier, dbh, biomass)
        calldata = fn._encode_transaction_data()
        try:
            token_id = int(fn.call({"from": self.signer}, block_identifier="latest"))
            gas = int(fn.estimate_gas({"from": self.signer}))
            return Simulation(True, token_id, gas, None, self.signer, calldata)
        except ContractCustomError as exc:
            return Simulation(False, None, None, decode_revert(exc.data, self.selectors), self.signer, calldata)
        except ContractLogicError as exc:
            data = exc.data if isinstance(exc.data, (str, bytes)) else None
            msg = decode_revert(data, self.selectors) if data else str(exc)
            return Simulation(False, None, None, msg, self.signer, calldata)

    def send_mint(self, planter: str, nullifier: bytes, dbh: int, biomass: int, *, confirmed: bool) -> dict:
        """Sign and broadcast mintTree from the server-side key. Refuses unless explicitly confirmed and
        a fresh simulation succeeds."""
        if not confirmed:
            raise PermissionError("broadcast requires explicit confirmation")
        sim = self.simulate_mint(planter, nullifier, dbh, biomass)
        if not sim.ok:
            raise RuntimeError(f"simulation failed, not broadcasting: {sim.error}")
        fn = self._mint_fn(planter, nullifier, dbh, biomass)
        tx = fn.build_transaction({
            "from": self.signer,
            "nonce": self.w3.eth.get_transaction_count(self.signer, "pending"),
            "chainId": self.settings.chain_id,
            "gas": int(sim.gas * 1.25),
        })
        signed = self._account.sign_transaction(tx)
        tx_hash = self.w3.eth.send_raw_transaction(signed.raw_transaction)
        receipt = self.w3.eth.wait_for_transaction_receipt(tx_hash, timeout=180)
        if receipt.status != 1:
            raise RuntimeError(f"mintTree tx {tx_hash.hex()} reverted on chain")
        minted = self.core.events.TreeMinted().process_receipt(receipt, errors=DISCARD)
        return {
            "tx_hash": "0x" + tx_hash.hex().removeprefix("0x"),
            "block": int(receipt.blockNumber),
            "gas_used": int(receipt.gasUsed),
            "token_id": int(minted[0].args.tokenId) if minted else sim.token_id,
            "tba": minted[0].args.tba if minted else None,
        }
