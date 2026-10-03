"""Limits keyed on the device: X-BioRig-Install-Id picks the per-caller counter, the address is the fallback, and a
whole-relay ceiling on session minting bounds what rotating the id can buy. Every caller here shares one address, as
every outside caller does behind the platform edge."""
from __future__ import annotations

import socket

import pytest

from .conftest import PILOT_LAT, PILOT_LNG, offset
from .test_edge import exchange, wire  # noqa: F401  (wire is a fixture)

EDGE_IP = "198.51.100.1"  # the one address the edge presents for everyone
A = "7f3c" + "0" * 24 + "4a01"
B = "b19e" + "1" * 24 + "77e2"


def spot(i: int):
    return offset(PILOT_LAT, PILOT_LNG, north_m=200 + 60 * i)


def session(rig, install_id: str | None = None, name: str = "x-biorig-install-id"):
    headers = {name: install_id} if install_id is not None else {}
    return rig.call("POST", "/v1/sessions", ip=EDGE_IP, headers=headers)


def limit(resp) -> str:
    assert resp.status == 429, resp.body
    assert resp.body["error"]["code"] == "rate_limited"
    return resp.body["error"]["limit"]


def test_one_device_exhausting_its_sessions_leaves_another_device_served(rig):
    for _ in range(4):
        assert session(rig, A).status == 201
    refused = session(rig, A)
    assert limit(refused) == "sessions_per_device_hour"
    assert refused.body["error"]["message"] == "limit sessions_per_device_hour reached"  # same wording template
    assert int(refused.headers["Retry-After"]) > 0
    assert session(rig, B).status == 201
    assert session(rig).status == 201  # and the address bucket was never touched


def test_rotating_ids_is_bounded_by_the_relay_wide_ceiling_exactly(rig):
    served = 0
    while True:
        resp = session(rig, f"{served:032x}")
        if resp.status != 201:
            break
        served += 1
        assert served <= 100, "no ceiling"
    assert served == 30 == rig.relay.limits.sessions_global_hour
    assert limit(resp) == "sessions_global_hour"
    assert limit(session(rig)) == "sessions_global_hour"  # the ceiling is the whole relay's, header or not
    rig.clock.advance(3601)
    assert session(rig, "f" * 32).status == 201


def test_the_ceiling_counts_address_keyed_sessions_too(make_rig):
    rig = make_rig(SESSIONS_GLOBAL_HOUR="5")
    for i in range(5):
        assert rig.call("POST", "/v1/sessions", ip=f"192.0.2.{i}").status == 201
    assert limit(rig.call("POST", "/v1/sessions", ip="192.0.2.99")) == "sessions_global_hour"


def test_a_device_refusal_does_not_spend_the_ceiling(make_rig):
    rig = make_rig(SESSIONS_GLOBAL_HOUR="6")
    for _ in range(4):
        assert session(rig, A).status == 201
    for _ in range(5):
        assert limit(session(rig, A)) == "sessions_per_device_hour"
    assert session(rig, B).status == 201 and session(rig, B).status == 201
    assert limit(session(rig, B)) == "sessions_global_hour"


@pytest.mark.parametrize("value", [None, "", "short", "g" * 32, A + "0", " "])
def test_no_or_malformed_id_is_served_and_counted_under_the_address(rig, value):
    for _ in range(4):
        assert session(rig, value).status == 201
    assert limit(session(rig, value)) == "sessions_per_ip_hour"
    assert session(rig, A).status == 201  # a device on the same address keeps its own allowance


def test_the_header_name_and_value_are_read_case_insensitively(rig):
    for _ in range(2):
        assert session(rig, A, name="x-biorig-install-id").status == 201
    for _ in range(2):
        assert session(rig, A.upper()).status == 201
    assert limit(session(rig, A)) == "sessions_per_device_hour"


def test_registrations_count_per_device_and_the_window_moves(rig):
    def submit(i: int, install_id: str, token: str):
        return rig.call("POST", "/v1/registrations",
                        rig.body(*spot(i), submission_id=f"d{i}", planter="0x" + f"{i + 1:02x}" * 20),
                        token=token, ip=EDGE_IP, headers={"x-biorig-install-id": install_id})

    tokens = [session(rig, A).body["session_token"] for _ in range(2)]
    for i in range(5):
        assert submit(i, A, tokens[i // 3]).status == 202
    assert limit(submit(5, A, tokens[1])) == "per_device_hour"
    assert submit(6, B, session(rig, B).body["session_token"]).status == 202  # another device, same address
    rig.clock.advance(3601)
    assert submit(7, A, session(rig, A).body["session_token"]).status == 202


def test_registrations_per_device_day(make_rig):
    rig = make_rig(LIMIT_PER_IP_HOUR="100", LIMIT_PER_IP_DAY="2")
    token = session(rig, A).body["session_token"]
    for i in range(2):
        assert rig.call("POST", "/v1/registrations", rig.body(*spot(i), submission_id=f"y{i}"), token=token,
                        ip=EDGE_IP, headers={"x-biorig-install-id": A}).status == 202
    resp = rig.call("POST", "/v1/registrations", rig.body(*spot(2), submission_id="y2"), token=token, ip=EDGE_IP,
                    headers={"x-biorig-install-id": A})
    assert limit(resp) == "per_device_day"


def test_session_and_planter_limits_stay_keyed_as_they_were(rig):
    """per_session counts the token and per_planter_day the wallet: a fresh install id buys neither."""
    token = session(rig, A).body["session_token"]
    for i in range(3):
        resp = rig.call("POST", "/v1/registrations", rig.body(*spot(i), submission_id=f"k{i}"), token=token,
                        ip=EDGE_IP, headers={"x-biorig-install-id": f"{i:032x}"})
        assert resp.status == 202, resp.body
    resp = rig.call("POST", "/v1/registrations", rig.body(*spot(3), submission_id="k3"), token=token, ip=EDGE_IP,
                    headers={"x-biorig-install-id": "e" * 32})
    assert limit(resp) == "per_session"


def test_plot_reads_count_per_device(make_rig):
    rig = make_rig(PLOT_READS_PER_IP_HOUR="2")
    import h3
    cell = h3.latlng_to_cell(PILOT_LAT, PILOT_LNG, 12)

    def read(install_id=None):
        headers = {"x-biorig-install-id": install_id} if install_id else {}
        return rig.call("GET", f"/v1/plots/{cell}", ip=EDGE_IP, headers=headers)

    assert read(A).status == 200 and read(A).status == 200
    assert limit(read(A)) == "plot_reads_per_device_hour"
    assert read(B).status == 200
    assert read().status == 200 and read().status == 200
    assert limit(read()) == "plot_reads_per_ip_hour"


def test_the_header_survives_the_real_handler_in_any_letter_case(rig, wire):  # noqa: F811
    """Over a loopback socket, the way the edge hands it upstream: the name's case normalised, the value kept."""
    def post(sock: socket.socket, name: str):
        raw = f"POST /v1/sessions HTTP/1.1\r\nHost: relay\r\n{name}: {A}\r\nContent-Length: 0\r\n\r\n".encode()
        return exchange(sock, raw)

    sock = wire()
    for name in ("X-BioRig-Install-Id", "x-biorig-install-id", "X-Biorig-Install-Id", "X-BIORIG-INSTALL-ID"):
        status, _, body = post(sock, name)
        assert status == 201, body
    status, headers, body = post(sock, "X-Biorig-Install-Id")
    assert status == 429 and body["error"]["limit"] == "sessions_per_device_hour"
    assert "x-frame-options" not in headers
