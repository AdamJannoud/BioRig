"""Area 3: idempotency, the four states, retries, recovery without re-sending, the budget, DRY_RUN and the cap."""
from __future__ import annotations

import sqlite3

import pytest

from relay import plot_index as pi
from relay.broadcaster import ChainBroadcaster, DryRunRefusal, MintResult
from relay.config import load_config

from .conftest import PILOT_LAT, PILOT_LNG, PLANTER_A, PLANTER_B, FakeBroadcaster, base_env, offset

SPOT = offset(PILOT_LAT, PILOT_LNG, north_m=200)  # clear of the pilot tree


def submitted(rig, lat_lng=SPOT, **kw):
    resp = rig.submit(*lat_lng, **kw)
    assert resp.status == 202, resp.body
    return resp.body["job"]["job_id"]


def job(rig, job_id):
    return rig.store.get(job_id)


def test_the_same_payload_twice_is_one_row(rig):
    token = rig.session()
    body = rig.body(*SPOT)
    first = rig.call("POST", "/v1/registrations", body, token=token)
    again = rig.call("POST", "/v1/registrations", body, token=token)
    assert first.status == 202 and again.status == 200 and again.body["outcome"] == "replayed"
    assert again.body["job"]["job_id"] == first.body["job"]["job_id"]
    # a new submission_id for the same tree (a client that lost its retry state) is still the same row
    other = rig.call("POST", "/v1/registrations", rig.body(*SPOT, submission_id="s-2"), token=rig.session())
    assert other.status == 200 and other.body["job"]["nullifier"] == first.body["job"]["nullifier"]
    assert sum(rig.store.counts_by_state().values()) == 1


def test_a_reused_submission_id_naming_another_tree_is_refused(rig):
    token = rig.session()
    rig.call("POST", "/v1/registrations", rig.body(*SPOT), token=token)
    resp = rig.call("POST", "/v1/registrations", rig.body(*SPOT, dbh_cm=30), token=token)
    assert resp.status == 409 and resp.body["error"]["code"] == "submission_conflict"


def test_unique_nullifier_is_enforced_by_storage(rig):
    jid = submitted(rig)
    row = job(rig, jid)
    with pytest.raises(sqlite3.IntegrityError):
        rig.store.insert({"nullifier": row.nullifier, "cell": row.cell, "tree_ordinal": 99, "salt": "x",
                          "lat": 0.0, "lng": 0.0, "location_source": "fix", "dbh_cm": 10, "mint_biomass_kg": 20,
                          "planter_address": PLANTER_B, "state": "submitted"})


def test_happy_path_submitted_verified_minted(rig):
    jid = submitted(rig)
    rig.relay.machine.tick()
    assert job(rig, jid).state == "verified"
    rig.relay.machine.tick()
    row = job(rig, jid)
    assert row.state == "minted" and row.attempts == 1 and row.token_id == 2 and row.decided_by == "auto"
    view = rig.call("GET", f"/v1/registrations/{jid}").body["job"]
    assert view["mint"] == {"token_id": 2, "tba": row.tba, "tx_hash": row.tx_hash, "block": row.block}
    assert "lat" not in view  # coordinates stay out of the public view


def test_a_broadcast_failure_then_success(rig):
    rig.fake.script = ["fail", "ok"]
    jid = submitted(rig)
    m = rig.relay.machine
    m.tick()  # verified
    m.tick()  # attempt 1 fails
    row = job(rig, jid)
    assert (row.state, row.attempts, row.last_error_code) == ("verified", 1, "send_failed")
    assert row.next_attempt_at == rig.clock() + 2.0  # first backoff step
    rig.clock.advance(1.0)
    m.tick()
    assert job(rig, jid).attempts == 1  # not due yet
    rig.clock.advance(1.0)
    m.tick()
    row = job(rig, jid)
    assert row.state == "minted" and row.attempts == 2 and rig.fake.broadcasts == 2


def test_an_active_nullifier_with_no_receipt_is_recovered_never_resent(rig):
    rig.fake.script = ["lost"]  # the mint lands, the receipt never arrives
    jid = submitted(rig)
    m = rig.relay.machine
    m.tick()
    m.tick()
    row = job(rig, jid)
    assert row.state == "verified" and row.attempts == 1 and row.last_error_code == "receipt_timeout"
    assert row.tx_hash is not None  # recorded as soon as it was sent
    rig.clock.advance(2.0)
    m.tick()
    row = job(rig, jid)
    assert row.state == "minted" and row.token_id == 2
    assert rig.fake.broadcasts == 1  # recovered with find_mint, nothing re-sent
    assert row.attempts == 1


def test_retry_budget_spent_is_rejected_broadcast_unconfirmed(rig):
    rig.fake.script = ["fail"] * 10
    jid = submitted(rig)
    m = rig.relay.machine
    m.tick()
    for _ in range(10):
        m.tick()
        rig.clock.advance(60)
    row = job(rig, jid)
    assert row.state == "rejected" and row.last_error_code == "broadcast_unconfirmed"
    assert rig.fake.broadcasts == rig.relay.config.retry.max_attempts == 4


def test_budget_spent_waits_while_a_send_could_still_mine(rig):
    rig.fake.script = ["fail"] * 10
    jid = submitted(rig)
    m = rig.relay.machine
    m.tick()
    for _ in range(4):
        m.tick()
        rig.clock.advance(60)
    rig.store.update(jid, nonce=7)
    rig.fake.settled_below = 7  # nonce 7 still pending
    m.tick()
    assert job(rig, jid).state == "verified" and job(rig, jid).last_error_code == "tx_pending"
    rig.fake.settled_below = 8
    rig.clock.advance(60)
    m.tick()
    assert job(rig, jid).state == "rejected"


def test_a_preflight_revert_is_rejected_without_broadcasting(rig):
    rig.fake.preflight_error = "InvalidTBA()"
    jid = submitted(rig)
    rig.relay.machine.tick()
    row = job(rig, jid)
    assert row.state == "rejected" and row.last_error_code == "preflight_revert" and row.last_error == "InvalidTBA()"
    assert rig.fake.broadcasts == 0


def test_dry_run_signs_nothing(make_rig):
    rig = make_rig(DRY_RUN="1")
    jid = submitted(rig)
    m = rig.relay.machine
    for _ in range(5):
        m.tick()
        rig.clock.advance(600)
    row = job(rig, jid)
    assert row.state == "verified" and row.last_error_code == "dry_run" and row.attempts == 0
    assert rig.fake.preflights >= 1 and rig.fake.broadcasts == 0
    assert rig.call("GET", "/healthz").body["dry_run"] is True


def test_dry_run_chain_broadcaster_refuses_before_any_network_call(tmp_path):
    config = load_config(base_env(tmp_path, DRY_RUN="1", RELAY_RPC_URL="http://127.0.0.1:9/never"))
    b = ChainBroadcaster(config)
    with pytest.raises(DryRunRefusal):
        b.broadcast(PLANTER_A, b"\x01" * 32, 10, 20, nonce=None, on_sent=lambda *a: pytest.fail("sent"))


def test_the_daily_cap_defers_rather_than_overspends(make_rig):
    rig = make_rig(LIMIT_GLOBAL_PER_DAY="1")
    j1 = submitted(rig)
    j2 = submitted(rig, offset(PILOT_LAT, PILOT_LNG, north_m=400), planter=PLANTER_B, ip="198.51.100.9")
    m = rig.relay.machine
    m.tick()
    m.tick()
    states = sorted([job(rig, j1).state, job(rig, j2).state])
    assert states == ["minted", "verified"] and rig.fake.broadcasts == 1
    waiting = job(rig, j1) if job(rig, j1).state == "verified" else job(rig, j2)
    assert waiting.last_error_code == "daily_cap"
    # and intake refuses with 429 while the cap is reached
    resp = rig.submit(*offset(PILOT_LAT, PILOT_LNG, north_m=600), ip="192.0.2.1", planter="0x" + "c3" * 20)
    assert resp.status == 429 and resp.body["error"]["limit"] == "global_per_day" and "Retry-After" in resp.headers


def test_paused_worker_takes_no_work(make_rig):
    rig = make_rig(PAUSED="1")
    jid = submitted(rig)
    assert rig.relay.machine.tick() == 0 and job(rig, jid).state == "submitted"


def test_intake_recovers_an_active_nullifier_with_no_local_row(rig):
    """The chain says the allocated nullifier is active and the store has no row for it: recover with find_mint and
    return that state instead of creating a second registration."""
    lat, lng = SPOT
    cell = rig.relay.index.cell(lat, lng)
    n0 = bytes.fromhex(pi.nullifier_for(cell, 0)[2:])
    rig.fake.active[n0] = MintResult(token_id=9, tx_hash="0x" + "99" * 32, block=79_100_000, tba="0x" + "09" * 20,
                                     planter="0x" + "a1" * 20, dbh=12, biomass=30)
    resp = rig.submit(lat, lng, planter=PLANTER_A)
    assert resp.status == 200 and resp.body["outcome"] == "recovered"
    view = resp.body["job"]
    assert view["state"] == "minted" and view["mint"]["token_id"] == 9 and view["tree_ordinal"] == 0
    assert rig.fake.broadcasts == 0 and sum(rig.store.counts_by_state().values()) == 1
    # another planter at the same spot is refused against the recovered tree
    other = rig.submit(lat, lng, planter=PLANTER_B, ip="198.51.100.9")
    assert other.status == 409 and other.body["error"]["existing"]["token_id"] == 9


def test_frozen_payload_and_terminal_states_are_enforced_by_storage(rig):
    jid = submitted(rig)
    rig.relay.machine.tick()  # verified
    with pytest.raises(sqlite3.IntegrityError, match="payload frozen"):
        rig.store.update(jid, dbh_cm=99)
    rig.relay.machine.tick()  # minted
    with pytest.raises(sqlite3.IntegrityError, match="terminal"):
        rig.store.update(jid, state="verified")
