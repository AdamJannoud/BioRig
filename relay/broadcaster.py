"""The chain, as the relay's state machine sees it: a protocol, and the web3 implementation of it.

The machine only ever talks to a Broadcaster, so tests drive every edge with a fake and nothing in the suite touches
a network or needs a key. ChainBroadcaster reuses dashboard.chain.Chain for the reads (is_nullifier_active, the
hardened log walk behind find_mint, getTreeStats) and holds the verifier key itself: the dashboard's Chain is built
here with no key at all, so the relay's signing does not depend on a signing path the dashboard is due to lose.
"""
from __future__ import annotations

import threading
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Protocol

from dashboard import chain as chain_mod
from dashboard.config import Settings

from .config import RelayConfig


class TransientChainError(RuntimeError):
    """The chain could not be asked (transport or RPC fault). Not a verdict: the job waits and is asked again."""


class BroadcastError(RuntimeError):
    """A broadcast that did not end in a confirmed receipt. `code` is stored as the job's last_error_code."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


class DryRunRefusal(RuntimeError):
    """DRY_RUN is on: everything up to and including the pre-flight runs, nothing is signed."""


@dataclass(frozen=True)
class Preflight:
    ok: bool
    token_id: int | None = None
    gas: int | None = None
    error: str | None = None


@dataclass(frozen=True)
class MintResult:
    token_id: int
    tx_hash: str
    block: int
    tba: str | None
    planter: str | None = None
    gas_used: int | None = None
    fee_wei: int | None = None
    dbh: int | None = None
    biomass: int | None = None


class Broadcaster(Protocol):
    signer: str

    def chain_id(self) -> int: ...

    def signer_is_verifier(self) -> bool: ...

    def is_nullifier_active(self, nullifier: bytes) -> bool: ...

    def find_mint(self, nullifier: bytes) -> MintResult | None:
        """The mint that activated `nullifier`, read back from the chain; None if no log can be found for it."""

    def preflight(self, planter: str, nullifier: bytes, dbh: int, biomass: int) -> Preflight:
        """eth_call (and estimateGas) of mintTree from the signer. A revert is Preflight(ok=False); a transport
        fault raises TransientChainError."""

    def broadcast(self, planter: str, nullifier: bytes, dbh: int, biomass: int, *, nonce: int | None,
                  on_sent: Callable[[str, int], None]) -> MintResult:
        """Sign and send mintTree, call on_sent(tx_hash, nonce) as soon as it is sent, wait for the receipt.
        Raises BroadcastError for anything short of a status-1 receipt and DryRunRefusal under DRY_RUN."""

    def nonce_settled(self, nonce: int) -> bool:
        """True once the signer's confirmed nonce has passed `nonce`: no transaction with it can still mine."""


def _transient(exc: BaseException) -> bool:
    return isinstance(exc, chain_mod._TRANSIENT)


class ChainBroadcaster:
    LOG_CHUNK = 5_000  # forno's eth_getLogs block-range cap

    def __init__(self, config: RelayConfig):
        from eth_account import Account

        settings = Settings(rpc_url=config.rpc_url, chain_id=config.chain_id,
                            explorer_url=config.chain.explorer_url, proxy=config.proxy, private_key=None,
                            allow_mint=False, chain=config.chain)
        self.chain = chain_mod.Chain(settings)
        self.w3 = self.chain.w3
        self._account = Account.from_key(config.verifier_key)
        self.signer = self._account.address
        self.dry_run = config.dry_run
        self.max_fee_wei = int(config.max_fee_gwei * 10**9)
        self._send_lock = threading.Lock()  # one in-flight broadcast, so two jobs never race for a nonce

    def __repr__(self) -> str:
        return f"ChainBroadcaster(signer={self.signer}, chain_id={self.chain.settings.chain_id}, dry_run={self.dry_run})"

    # ---- identity
    def chain_id(self) -> int:
        try:
            return self.chain.rpc_chain_id()
        except Exception as exc:
            if _transient(exc):
                raise TransientChainError(f"chain id unreadable: {exc.__class__.__name__}") from exc
            raise

    def signer_is_verifier(self) -> bool:
        f = self.chain.core.functions
        try:
            return bool(f.hasRole(f.VERIFIER_ROLE().call(), self.signer).call())
        except Exception as exc:
            if _transient(exc):
                raise TransientChainError(f"hasRole unreadable: {exc.__class__.__name__}") from exc
            raise

    # ---- reads
    def is_nullifier_active(self, nullifier: bytes) -> bool:
        try:
            return self.chain.is_nullifier_active(nullifier)
        except Exception as exc:
            if _transient(exc):
                raise TransientChainError(f"isNullifierActive unreadable: {exc.__class__.__name__}") from exc
            raise

    def _logs_for(self, event, nullifier: bytes, lo: int, hi: int) -> list:
        """TreeMinted logs for `nullifier` in [lo, hi], an empty answer re-asked like Chain._get_logs_confirmed."""
        for delay in (*chain_mod.EMPTY_CONFIRM_DELAYS, None):
            logs = self.chain._rpc(lambda: event.get_logs(
                from_block=lo, to_block=hi, argument_filters={"spatialNullifier": nullifier}))
            if logs or delay is None:
                return list(logs)
            chain_mod._sleep(delay)

    def find_mint(self, nullifier: bytes) -> MintResult | None:
        """TreeMinted indexes spatialNullifier, so the token id comes from a filtered log walk; the record (tx,
        block, planter, TBA) then comes from Chain.find_mint, which is already hardened against forno answering
        empty for ranges that hold logs."""
        event = self.chain.core.events.TreeMinted()
        try:
            found = None
            for _ in range(chain_mod.MINT_WALKS):
                ranges = self.chain._log_ranges(self.LOG_CHUNK)[2]
                pool = ThreadPoolExecutor(max_workers=chain_mod.LOG_WORKERS)
                try:
                    futures = [pool.submit(self._logs_for, event, nullifier, lo, hi) for lo, hi in ranges]
                    for fut in futures:
                        logs = fut.result()
                        if logs:
                            found = logs[0]
                            break
                finally:
                    pool.shutdown(wait=False, cancel_futures=True)
                if found is not None:
                    break
            if found is None:
                return None
            token_id = int(found.args.tokenId)
            record = self.chain.find_mint(token_id, chunk=self.LOG_CHUNK)
            stats = self.chain.get_tree_stats(token_id)
        except Exception as exc:
            if _transient(exc):
                raise TransientChainError(f"mint record unreadable: {exc.__class__.__name__}") from exc
            raise
        return MintResult(token_id=token_id, tx_hash=record.tx_hash, block=record.block_number,
                          tba=record.tba_event, planter=record.planter, dbh=stats.dbh, biomass=stats.biomass)

    # ---- pre-flight and broadcast
    def _mint_fn(self, planter: str, nullifier: bytes, dbh: int, biomass: int):
        from eth_utils import to_checksum_address

        for name, v in (("initialDBH", dbh), ("initialBiomass", biomass)):
            if not 0 <= v < 2**96:
                raise ValueError(f"{name} {v} does not fit uint96")
        return self.chain.core.functions.mintTree(to_checksum_address(planter), nullifier, dbh, biomass)

    def preflight(self, planter: str, nullifier: bytes, dbh: int, biomass: int) -> Preflight:
        from web3.exceptions import ContractCustomError, ContractLogicError

        fn = self._mint_fn(planter, nullifier, dbh, biomass)
        try:
            token_id = int(fn.call({"from": self.signer}, block_identifier="latest"))
            gas = int(fn.estimate_gas({"from": self.signer}))
            return Preflight(True, token_id, gas)
        except ContractCustomError as exc:
            return Preflight(False, error=chain_mod.decode_revert(exc.data, self.chain.selectors))
        except ContractLogicError as exc:
            data = exc.data if isinstance(exc.data, (str, bytes)) else None
            return Preflight(False, error=chain_mod.decode_revert(data, self.chain.selectors) if data else str(exc))
        except Exception as exc:
            if _transient(exc):
                raise TransientChainError(f"pre-flight unreadable: {exc.__class__.__name__}") from exc
            raise

    def nonce_settled(self, nonce: int) -> bool:
        try:
            return int(self.w3.eth.get_transaction_count(self.signer, "latest")) > nonce
        except Exception as exc:
            if _transient(exc):
                raise TransientChainError(f"nonce unreadable: {exc.__class__.__name__}") from exc
            raise

    def _fees(self, replacing: bool) -> tuple[int, int]:
        base = int(self.w3.eth.get_block("latest").get("baseFeePerGas") or self.w3.eth.gas_price)
        tip = int(self.w3.eth.max_priority_fee)
        if replacing:  # a replacement must outbid the first send by at least 10%, so ask for the cap
            tip = min(self.max_fee_wei, tip * 2)
            return self.max_fee_wei, tip
        max_fee = 2 * base + tip
        if base + tip > self.max_fee_wei:
            raise BroadcastError("fee_above_cap", f"base fee {base} wei plus tip exceeds MAX_FEE_GWEI")
        return min(max_fee, self.max_fee_wei), min(tip, self.max_fee_wei)

    def broadcast(self, planter: str, nullifier: bytes, dbh: int, biomass: int, *, nonce: int | None,
                  on_sent: Callable[[str, int], None]) -> MintResult:
        if self.dry_run:
            raise DryRunRefusal("DRY_RUN is on: nothing is signed")
        from web3.exceptions import TimeExhausted
        from web3.logs import DISCARD

        with self._send_lock:
            try:
                pre = self.preflight(planter, nullifier, dbh, biomass)
                if not pre.ok:
                    raise BroadcastError("preflight_revert", pre.error or "reverted")
                confirmed = int(self.w3.eth.get_transaction_count(self.signer, "latest"))
                # Explicit nonce: a retry reuses its own nonce while that nonce is unconsumed, so at most one of a
                # job's broadcasts can ever mine; a consumed nonce means take the next pending one.
                replacing = nonce is not None and nonce >= confirmed
                use = nonce if replacing else int(self.w3.eth.get_transaction_count(self.signer, "pending"))
                max_fee, tip = self._fees(replacing)
                tx = self._mint_fn(planter, nullifier, dbh, biomass).build_transaction({
                    "from": self.signer, "nonce": use, "chainId": self.chain.settings.chain_id,
                    "gas": int(pre.gas * 1.25), "maxFeePerGas": max_fee, "maxPriorityFeePerGas": tip})
                signed = self._account.sign_transaction(tx)
                tx_hash = self.w3.eth.send_raw_transaction(signed.raw_transaction)
            except (BroadcastError, TransientChainError):
                raise
            except Exception as exc:
                raise BroadcastError("send_failed", f"{exc.__class__.__name__}: {exc}") from exc
            hexhash = "0x" + bytes(tx_hash).hex()
            on_sent(hexhash, use)
            try:
                receipt = self.w3.eth.wait_for_transaction_receipt(tx_hash, timeout=120)
            except TimeExhausted as exc:
                raise BroadcastError("receipt_timeout", f"no receipt for {hexhash} within 120 s") from exc
            except Exception as exc:
                raise BroadcastError("receipt_unreadable", f"{exc.__class__.__name__}: {exc}") from exc
        if receipt.status != 1:
            raise BroadcastError("reverted_on_chain", f"{hexhash} reverted on chain")
        minted = self.chain.core.events.TreeMinted().process_receipt(receipt, errors=DISCARD)
        if not minted:
            raise BroadcastError("no_mint_event", f"{hexhash} has no TreeMinted event")
        price = int(receipt.get("effectiveGasPrice") or 0)
        return MintResult(token_id=int(minted[0].args.tokenId), tx_hash=hexhash, block=int(receipt.blockNumber),
                          tba=minted[0].args.tba, planter=planter, gas_used=int(receipt.gasUsed),
                          fee_wei=int(receipt.gasUsed) * price)
