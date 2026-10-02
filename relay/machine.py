"""Area 3: the four states and the worker that walks them.

    submitted --(nullifier inactive, pre-flight ok)--> verified --(broadcast, receipt status 1)--> minted
        |                                                 |  ^
        |                                                 |  '-- retry: attempts+1, backoff 2s/10s/45s,
        |                                                 |      is_nullifier_active re-checked first
        '--(pre-flight revert)--> rejected <--(retry budget spent: broadcast_unconfirmed; pre-flight revert)

There is no minting state: the attempt counter on verified carries the same fact and survives a crash. The rule that
makes a retry safe: before anything in verified is broadcast, ask is_nullifier_active. If it is active the mint
already happened and only the receipt was lost, so find_mint recovers it and the job moves to minted without
signing anything. One worker, one in-flight broadcast, an explicit nonce per job.
"""
from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable

from .broadcaster import Broadcaster, BroadcastError, DryRunRefusal, MintResult, TransientChainError
from .config import Limits, Retry
from .store import Registration, StateConflict, Store

log = logging.getLogger("relay.machine")
DAY_S = 86_400


class Machine:
    def __init__(self, store: Store, broadcaster: Broadcaster, *, retry: Retry = Retry(), limits: Limits = Limits(),
                 dry_run: bool = False, paused: bool = False, clock: Callable[[], float] = time.time):
        self.store = store
        self.broadcaster = broadcaster
        self.retry = retry
        self.limits = limits
        self.dry_run = dry_run
        self.paused_by_env = paused
        self.clock = clock

    # ---- pause: PAUSED in the environment, or the operator's runtime flag in the store
    @property
    def paused(self) -> bool:
        return self.paused_by_env or self.store.meta("paused") == "1"

    def set_paused(self, value: bool) -> None:
        self.store.set_meta("paused", "1" if value else "0")

    # ---- the loop
    def tick(self) -> int:
        """Process every job that is due, one at a time. Returns how many were processed."""
        if self.paused:
            return 0
        done = 0
        for job in self.store.due(self.clock()):
            if self.paused:
                break
            try:
                self.step(job)
            except StateConflict as exc:  # an operator moved it meanwhile; its new state stands
                log.info("job %s moved under the worker: %s", job.id, exc)
            done += 1
        return done

    def step(self, job: Registration) -> Registration:
        if job.state == "submitted":
            return self._verify(job)
        if job.state == "verified":
            return self._send(job)
        return job

    # ---- edges
    def _defer(self, job: Registration, code: str, delay: float, message: str | None = None) -> Registration:
        return self.store.update(job.id, expect_state=job.state, next_attempt_at=self.clock() + delay,
                                 last_error_code=code, last_error=message)

    def _reject(self, job: Registration, code: str, message: str | None) -> Registration:
        log.warning("job %s rejected: %s %s", job.id, code, message or "")
        return self.store.update(job.id, expect_state=job.state, state="rejected", next_attempt_at=None,
                                 last_error_code=code, last_error=message, decided_by="auto")

    def _minted(self, job: Registration, res: MintResult, note: str | None = None) -> Registration:
        return self.store.update(
            job.id, expect_state=job.state, state="minted", token_id=res.token_id, tba=res.tba, tx_hash=res.tx_hash,
            block=res.block, gas_used=res.gas_used, fee_wei=None if res.fee_wei is None else str(res.fee_wei),
            minted_at=self.clock(), next_attempt_at=None, last_error_code=None, last_error=note, decided_by="auto")

    def _recover(self, job: Registration) -> Registration:
        """The nullifier is active on chain: read the mint back instead of sending anything."""
        res = self.broadcaster.find_mint(job.nullifier_bytes)
        if res is None:
            return self._defer(job, "receipt_unrecovered", self.retry.backoff_s[-1],
                               "nullifier active on chain but its TreeMinted log was not found yet")
        if res.planter and res.planter.lower() != job.planter_address.lower():
            return self._reject(job, "nullifier_taken", f"token {res.token_id} holds this nullifier for "
                                                        f"another planter")
        return self._minted(job, res, "receipt recovered from the chain; nothing was re-sent")

    def _verify(self, job: Registration) -> Registration:
        try:
            if self.broadcaster.is_nullifier_active(job.nullifier_bytes):
                return self._recover(job)
            pre = self.broadcaster.preflight(job.planter_address, job.nullifier_bytes, job.dbh_cm,
                                             job.mint_biomass_kg)
        except TransientChainError as exc:
            return self._defer(job, "chain_unavailable", self.retry.backoff_s[0], str(exc))
        if not pre.ok:
            return self._reject(job, "preflight_revert", pre.error)
        return self.store.update(job.id, expect_state="submitted", state="verified", verified_at=self.clock(),
                                 next_attempt_at=None, last_error_code=None, last_error=None, decided_by="auto")

    def _send(self, job: Registration) -> Registration:
        now = self.clock()
        try:
            if job.attempts >= self.retry.max_attempts:
                # Budget spent. Terminal only once no earlier send can still mine and the chain confirms no mint.
                if job.nonce is not None and not self.broadcaster.nonce_settled(job.nonce):
                    return self._defer(job, "tx_pending", self.retry.backoff_s[-1],
                                       f"nonce {job.nonce} not yet settled")
                if self.broadcaster.is_nullifier_active(job.nullifier_bytes):
                    return self._recover(job)
                return self._reject(job, "broadcast_unconfirmed",
                                    f"{job.attempts} broadcast attempts without a confirmed receipt")
            if self.broadcaster.is_nullifier_active(job.nullifier_bytes):
                return self._recover(job)
        except TransientChainError as exc:
            return self._defer(job, "chain_unavailable", self.retry.backoff_s[0], str(exc))

        if self.dry_run:
            return self._defer(job, "dry_run", self.retry.daily_cap_defer_s, "DRY_RUN: pre-flight passed, not signed")
        if self.store.minted_since(now - DAY_S) >= self.limits.global_per_day:
            oldest = self.store.oldest_mint_since(now - DAY_S) or now
            return self._defer(job, "daily_cap", max(1.0, oldest + DAY_S - now),
                               f"{self.limits.global_per_day} mints in the last 24 h")

        # The attempt is counted before anything is signed, so a crash mid-send still leaves the fact on the row.
        job = self.store.update(job.id, expect_state="verified", attempts=job.attempts + 1)
        try:
            res = self.broadcaster.broadcast(
                job.planter_address, job.nullifier_bytes, job.dbh_cm, job.mint_biomass_kg, nonce=job.nonce,
                on_sent=lambda tx_hash, nonce: self.store.update(job.id, tx_hash=tx_hash, nonce=nonce))
        except DryRunRefusal as exc:
            self.store.update(job.id, attempts=job.attempts - 1)
            return self._defer(self.store.get(job.id), "dry_run", self.retry.daily_cap_defer_s, str(exc))
        except BroadcastError as exc:
            if exc.code == "preflight_revert":
                return self._reject(job, "preflight_revert", str(exc))
            delay = self.retry.backoff_s[min(job.attempts, len(self.retry.backoff_s)) - 1]
            log.warning("job %s attempt %d failed: %s", job.id, job.attempts, exc.code)
            return self._defer(job, exc.code, delay, str(exc))
        except TransientChainError as exc:
            delay = self.retry.backoff_s[min(job.attempts, len(self.retry.backoff_s)) - 1]
            return self._defer(job, "chain_unavailable", delay, str(exc))
        return self._minted(self.store.get(job.id), res)


class Worker(threading.Thread):
    """The single worker: one tick at a time, so there is only ever one broadcast in flight."""

    def __init__(self, machine: Machine, poll_s: float = 1.0):
        super().__init__(name="relay-worker", daemon=True)
        self.machine = machine
        self.poll_s = poll_s
        self.stop_event = threading.Event()
        self.last_tick_at: float | None = None

    def run(self) -> None:
        while not self.stop_event.is_set():
            try:
                self.machine.tick()
            except Exception:  # a bad tick must not kill the only worker; the job stays due and is retried
                log.exception("worker tick failed")
            self.last_tick_at = self.machine.clock()
            self.stop_event.wait(self.poll_s)

    def stop(self) -> None:
        self.stop_event.set()
