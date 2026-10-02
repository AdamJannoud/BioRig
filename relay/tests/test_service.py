"""Areas 2 + 3 over the HTTP surface: sessions, limits, plots, health, admin, and the contract document."""
from __future__ import annotations

import json
import re
import threading
import urllib.error
import urllib.request
from pathlib import Path

import pytest

from relay.service import ROUTES, make_server

from .conftest import PILOT_LAT, PILOT_LNG, PLANTER_A, offset

DOC = Path(__file__).resolve().parents[2] / "docs" / "relay-api.md"
ADMIN = "a" * 40


def spot(i: int):
    return offset(PILOT_LAT, PILOT_LNG, north_m=200 + 60 * i)


def test_registration_requires_a_session_token(rig):
    resp = rig.call("POST", "/v1/registrations", rig.body(*spot(0)))
    assert resp.status == 401 and resp.body["error"]["code"] == "session_required"
    resp = rig.call("POST", "/v1/registrations", rig.body(*spot(0)), token="made-up")
    assert resp.status == 401 and resp.body["error"]["code"] == "session_invalid"


def test_session_bootstrap_and_expiry(rig):
    resp = rig.call("POST", "/v1/sessions")
    assert resp.status == 201
    assert resp.body["expires_at"] - resp.body["created_at"] == 86_400 and resp.body["registrations_allowed"] == 3
    token = resp.body["session_token"]
    assert token not in json.dumps([dict(r) for r in rig.store._all("SELECT * FROM sessions")])  # hash only
    rig.clock.advance(86_401)
    resp = rig.call("POST", "/v1/registrations", rig.body(*spot(0)), token=token)
    assert resp.status == 401 and resp.body["error"]["code"] == "session_expired"


def test_session_creation_is_limited_per_ip(rig):
    for _ in range(4):
        rig.session(ip="192.0.2.50")
    resp = rig.call("POST", "/v1/sessions", ip="192.0.2.50")
    assert resp.status == 429 and resp.body["error"]["limit"] == "sessions_per_ip_hour"
    assert int(resp.headers["Retry-After"]) > 0


def test_per_session_limit_is_three(rig):
    token = rig.session()
    for i in range(3):
        resp = rig.call("POST", "/v1/registrations", rig.body(*spot(i), submission_id=f"s{i}"), token=token)
        assert resp.status == 202, resp.body
    resp = rig.call("POST", "/v1/registrations", rig.body(*spot(3), submission_id="s3"), token=token)
    assert resp.status == 429 and resp.body["error"]["limit"] == "per_session"


def test_per_planter_daily_limit(make_rig):
    rig = make_rig(LIMIT_PER_PLANTER_DAY="2")
    for i in range(2):
        assert rig.submit(*spot(i), ip=f"192.0.2.{i}").status == 202
    resp = rig.submit(*spot(2), ip="192.0.2.9")
    assert resp.status == 429 and resp.body["error"]["limit"] == "per_planter_day"


def test_sixth_request_in_an_hour_from_one_ip_gets_429_with_retry_after_over_http(rig):
    """Through a real ThreadingHTTPServer on loopback: five registrations from one IP pass, the sixth is refused."""
    server = make_server(rig.relay, "127.0.0.1", 0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_address[1]}"

    def post(path, body=None, token=None):
        data = json.dumps(body).encode() if body is not None else b""
        req = urllib.request.Request(base + path, data=data, method="POST")
        if body is not None:
            req.add_header("Content-Type", "application/json")
        if token:
            req.add_header("Authorization", f"Bearer {token}")
        try:
            with urllib.request.urlopen(req, timeout=5) as r:
                return r.status, dict(r.headers), json.loads(r.read())
        except urllib.error.HTTPError as e:
            return e.code, dict(e.headers), json.loads(e.read())

    try:
        tokens = [post("/v1/sessions")[2]["session_token"] for _ in range(2)]
        statuses = []
        for i in range(6):
            status, headers, body = post("/v1/registrations",
                                         rig.body(*spot(i), submission_id=f"r{i}", planter="0x" + f"{i + 1:02x}" * 20),
                                         token=tokens[i // 3])
            statuses.append(status)
        assert statuses == [202] * 5 + [429]
        assert body["error"]["code"] == "rate_limited" and body["error"]["limit"] == "per_ip_hour"
        assert 0 < int(headers["Retry-After"]) <= 3600
        assert not any(k.lower() == "x-frame-options" for k in headers)
        assert "frame-ancestors" not in json.dumps(headers).lower()
    finally:
        server.shutdown()
        server.server_close()
    assert sum(rig.store.counts_by_state().values()) == 5  # the refusal created no row


def test_ip_limit_window_moves(rig):
    tokens = [rig.session(), rig.session()]
    for i in range(5):
        assert rig.submit(*spot(i), token=tokens[i // 3], submission_id=f"w{i}",
                          planter="0x" + f"{i + 1:02x}" * 20).status == 202
    assert rig.submit(*spot(5), token=tokens[1], submission_id="w5", planter="0x" + "77" * 20).status == 429
    rig.clock.advance(3601)
    assert rig.submit(*spot(6), planter="0x" + "88" * 20).status == 202


def test_get_job_and_unknown_routes(rig):
    resp = rig.submit(*spot(0))
    jid = resp.body["job"]["job_id"]
    got = rig.call("GET", f"/v1/registrations/{jid}")
    assert got.status == 200 and got.body["job"]["state"] == "submitted"
    assert rig.call("GET", "/v1/registrations/" + "0" * 32).status == 404
    assert rig.call("GET", "/v1/nothing").status == 404
    resp = rig.call("DELETE", "/v1/registrations")
    assert resp.status == 405 and resp.headers["Allow"] == "POST"


def test_wrong_content_type_and_bad_json(rig):
    token = rig.session()
    from relay.service import Request
    resp = rig.relay.handle(Request("POST", "/v1/registrations", {"authorization": f"Bearer {token}",
                                                                   "content-type": "text/plain"}, b"{}"))
    assert resp.status == 415
    resp = rig.relay.handle(Request("POST", "/v1/registrations", {"authorization": f"Bearer {token}",
                                                                   "content-type": "application/json"}, b"{nope"))
    assert resp.status == 400 and resp.body["error"]["code"] == "invalid_json"


def test_plots_endpoint(rig):
    resp = rig.call("GET", "/v1/plots/not-a-cell")
    assert resp.status == 404  # does not match the route's cell pattern
    resp = rig.call("GET", "/v1/plots/" + "8" * 15)
    assert resp.status == 400 and resp.body["error"]["code"] == "invalid_cell"
    resp = rig.call("GET", "/v1/plots/8c7a6e42ca207ff")
    assert resp.status == 200 and resp.body["active"] == 0 and resp.body["max_trees_per_cell"] == 4


def test_health_payload(rig):
    rig.submit(*spot(0))
    body = rig.call("GET", "/healthz").body
    assert body["status"] == "ok" and body["chain_id"] == 42220 and body["signer_is_verifier"] is True
    assert body["queue"] == {"submitted": 1, "verified": 0, "minted": 0, "rejected": 0}
    assert body["global_per_day"] == 200 and body["mints_24h"] == 0 and body["paused"] is False
    rig.relay.machine.tick()
    rig.clock.advance(301)
    body = rig.call("GET", "/healthz").body
    assert body["stuck"] == 1 and body["status"] == "degraded" and body["oldest_verified_age_s"] == 301
    rig.fake.verifier = False
    rig.clock.advance(61)
    resp = rig.call("GET", "/healthz")
    assert resp.status == 503 and resp.body["signer_is_verifier"] is False


def test_admin_disabled_without_a_token(rig):
    assert rig.call("POST", "/v1/admin/pause").status == 404


def test_admin_surface(make_rig):
    rig = make_rig(RELAY_ADMIN_TOKEN=ADMIN)
    assert rig.call("POST", "/v1/admin/pause", token="wrong").status == 401
    assert rig.call("POST", "/v1/admin/pause", token=rig.session()).status == 401  # a session is not an admin
    jid = rig.submit(*spot(0)).body["job"]["job_id"]
    assert rig.call("POST", "/v1/admin/pause", token=ADMIN).body == {"paused": True}
    assert rig.relay.machine.tick() == 0
    assert rig.call("GET", "/healthz").body["paused"] is True
    rig.call("POST", "/v1/admin/resume", token=ADMIN)
    rig.relay.machine.tick()
    listed = rig.call("GET", "/v1/admin/jobs?state=verified", token=ADMIN).body["jobs"]
    assert [j["job_id"] for j in listed] == [jid] and "lat" in listed[0]
    resp = rig.call("POST", f"/v1/admin/jobs/{jid}/reject", {"reason": "duplicate photo"}, token=ADMIN)
    assert resp.status == 200 and resp.body["job"]["state"] == "rejected"
    assert resp.body["job"]["decided_by"] == "admin"
    again = rig.call("POST", f"/v1/admin/jobs/{jid}/reject", {"reason": "x"}, token=ADMIN)
    assert again.status == 409


def test_admin_cannot_reject_a_job_that_was_broadcast(make_rig):
    rig = make_rig(RELAY_ADMIN_TOKEN=ADMIN)
    rig.fake.script = ["fail"]
    jid = rig.submit(*spot(0)).body["job"]["job_id"]
    rig.relay.machine.tick()
    rig.relay.machine.tick()
    resp = rig.call("POST", f"/v1/admin/jobs/{jid}/reject", {"reason": "x"}, token=ADMIN)
    assert resp.status == 409 and resp.body["error"]["code"] == "broadcast_in_history"
    resp = rig.call("POST", f"/v1/admin/jobs/{jid}/retry", token=ADMIN)
    assert resp.status == 200
    rig.relay.machine.tick()
    assert rig.store.get(jid).state == "minted"


def test_the_contract_document_matches_the_route_table():
    text = DOC.read_text()
    documented = set(re.findall(r"^### (GET|POST) (/\S+)$", text, flags=re.M))
    assert documented == {(r.method, r.template) for r in ROUTES}
    # every error code the service can raise is documented
    src = "".join(p.read_text() for p in (Path(__file__).resolve().parents[1]).glob("*.py"))
    codes = set(re.findall(r'Refusal\(\d{3}, "([a-z_]+)"', src)) | set(re.findall(r'code="([a-z_]+)"', src))
    codes |= {"invalid_field", "body_too_large", "not_found", "method_not_allowed", "internal"}
    missing = sorted(c for c in codes if f"`{c}`" not in text)
    assert not missing, f"undocumented error codes: {missing}"
