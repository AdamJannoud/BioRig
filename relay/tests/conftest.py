"""Shared fixtures. A FakeBroadcaster stands in for the chain: no test touches a network or holds a real key."""
from __future__ import annotations

import json
import math
import time
from dataclasses import dataclass, field

import h3
import pytest

from relay.broadcaster import BroadcastError, MintResult, Preflight, TransientChainError
from relay.config import load_config
from relay.service import Relay, Request
from relay.store import Store

# A syntactically valid secp256k1 scalar so the config loader accepts it. It is a key to nothing; with the fake
# broadcaster nothing is ever signed.
TEST_KEY = "0x" + "11" * 32
# The pilot's recorded coordinates (tools/demo_facts.json demo_h3): tests place synthetic fixes relative to them.
PILOT_LAT, PILOT_LNG = -1.2921, 36.8219
PLANTER_A = "0x" + "a1" * 20
PLANTER_B = "0x" + "b2" * 20


class Clock:
    def __init__(self, start: float = 1_800_000_000.0):
        self.now = start

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


@dataclass
class FakeBroadcaster:
    """The chain, in memory. `script` lists broadcast outcomes in order: "ok", "fail" (nothing sent), or "lost"
    (the mint lands on chain but the receipt never comes back)."""
    signer: str = "0x" + "5e" * 20
    rpc_chain: int = 42220
    verifier: bool = True
    script: list = field(default_factory=list)
    preflight_error: str | None = None
    unreachable: bool = False
    active: dict = field(default_factory=dict)  # nullifier bytes -> MintResult
    broadcasts: int = 0
    preflights: int = 0
    next_token: int = 2
    next_nonce: int = 0
    settled_below: int = 10**9

    def chain_id(self) -> int:
        return self.rpc_chain

    def signer_is_verifier(self) -> bool:
        if self.unreachable:
            raise TransientChainError("fake: unreachable")
        return self.verifier

    def is_nullifier_active(self, nullifier: bytes) -> bool:
        if self.unreachable:
            raise TransientChainError("fake: unreachable")
        return nullifier in self.active

    def find_mint(self, nullifier: bytes):
        return self.active.get(nullifier)

    def preflight(self, planter, nullifier, dbh, biomass) -> Preflight:
        self.preflights += 1
        if self.unreachable:
            raise TransientChainError("fake: unreachable")
        if nullifier in self.active:
            return Preflight(False, error="NullifierInUse()")
        if self.preflight_error:
            return Preflight(False, error=self.preflight_error)
        return Preflight(True, token_id=self.next_token, gas=270_000)

    def _mint(self, planter, nullifier, dbh, biomass) -> MintResult:
        res = MintResult(token_id=self.next_token, tx_hash="0x" + f"{self.next_token:064x}",
                         block=79_000_000 + self.next_token, tba="0x" + f"{self.next_token:040x}",
                         planter=planter, gas_used=270_077, fee_wei=54_015_697_000_000_000, dbh=dbh,
                         biomass=biomass)
        self.next_token += 1
        self.active[nullifier] = res
        return res

    def broadcast(self, planter, nullifier, dbh, biomass, *, nonce, on_sent):
        self.broadcasts += 1
        outcome = self.script.pop(0) if self.script else "ok"
        if outcome == "fail":
            raise BroadcastError("send_failed", "fake: the RPC dropped the send")
        use = nonce if nonce is not None else self.next_nonce
        self.next_nonce = max(self.next_nonce, use + 1)
        on_sent("0x" + "ee" * 32, use)
        res = self._mint(planter, nullifier, dbh, biomass)
        if outcome == "lost":
            raise BroadcastError("receipt_timeout", "fake: no receipt within the timeout")
        return res

    def nonce_settled(self, nonce: int) -> bool:
        return nonce < self.settled_below


def offset(lat: float, lng: float, north_m: float = 0.0, east_m: float = 0.0) -> tuple[float, float]:
    dlat = north_m / 111_320.0
    dlng = east_m / (111_320.0 * math.cos(math.radians(lat)))
    return lat + dlat, lng + dlng


def base_env(tmp_path, **overrides) -> dict:
    env = {"RELAY_VERIFIER_KEY": TEST_KEY, "RELAY_DB": str(tmp_path / "relay.db"), "RELAY_CHAIN_ID": "42220"}
    env.update({k: str(v) for k, v in overrides.items()})
    return env


@dataclass
class Rig:
    relay: Relay
    fake: FakeBroadcaster
    clock: Clock
    store: Store

    def call(self, method: str, path: str, body=None, token: str | None = None, ip: str = "203.0.113.7",
             headers: dict | None = None):
        h = {"content-type": "application/json"} if body is not None else {}
        if token:
            h["authorization"] = f"Bearer {token}"
        h.update(headers or {})
        raw = b"" if body is None else json.dumps(body).encode()
        return self.relay.handle(Request(method, path, h, raw, ip))

    def session(self, ip: str = "203.0.113.7") -> str:
        resp = self.call("POST", "/v1/sessions", ip=ip)
        assert resp.status == 201, resp.body
        return resp.body["session_token"]

    def body(self, lat: float, lng: float, planter: str = PLANTER_A, submission_id: str = "s-1", dbh_cm: int = 10,
             **extra) -> dict:
        return {"submission_id": submission_id, "planter_address": planter,
                "fix": {"lat": lat, "lng": lng, "accuracy_m": 8.0, "captured_at": int(self.clock()) - 30},
                "tree": {"species": "unspecified", "dbh_cm": dbh_cm}, **extra}

    def submit(self, lat, lng, token=None, ip="203.0.113.7", **kw):
        token = token or self.session(ip)
        return self.call("POST", "/v1/registrations", self.body(lat, lng, **kw), token=token, ip=ip)


@pytest.fixture
def make_rig(tmp_path):
    rigs = []

    def _make(fake: FakeBroadcaster | None = None, **env) -> Rig:
        config = load_config(base_env(tmp_path, **env))
        clock = Clock()
        store = Store(config.db_path, clock=clock)
        store.bind_chain(config.chain_id)
        fake = fake or FakeBroadcaster()
        rig = Rig(Relay(config, store, fake, clock=clock), fake, clock, store)
        rigs.append(rig)
        return rig

    yield _make
    for rig in rigs:
        rig.store.close()


@pytest.fixture
def rig(make_rig) -> Rig:
    return make_rig()


@pytest.fixture
def jitter_pair():
    """One tree reported twice: two fixes ~11 m apart that land in adjacent resolution-12 cells. Found by walking
    east from the pilot cell's centre to its boundary and stepping 5.5 m either side of it."""
    cell = h3.latlng_to_cell(PILOT_LAT, PILOT_LNG, 12)
    clat, clng = h3.cell_to_latlng(cell)
    step = 0.25
    x = 0.0
    while h3.latlng_to_cell(*offset(clat, clng, east_m=x), 12) == cell:
        x += step
    a = offset(clat, clng, east_m=x - 5.5)
    b = offset(clat, clng, east_m=x + 5.5)
    ca, cb = h3.latlng_to_cell(*a, 12), h3.latlng_to_cell(*b, 12)
    assert ca != cb and h3.grid_distance(ca, cb) == 1
    return a, b
