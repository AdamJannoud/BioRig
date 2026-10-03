"""Behind the public edge: Authorization arrives renamed, and every request body arrives chunked with no Content-Length."""
from __future__ import annotations

import http.client
import json
import socket
import threading

import pytest

from relay.service import MAX_BODY_BYTES, Request, make_server

from .conftest import PILOT_LAT, PILOT_LNG, offset

EDGE_AUTH = "x-sandbox-forwarded-authorization"


def spot(i: int):
    return offset(PILOT_LAT, PILOT_LNG, north_m=200 + 60 * i)


def register(rig, headers: dict):
    body = json.dumps(rig.body(*spot(0))).encode()
    return rig.relay.handle(Request("POST", "/v1/registrations", {"content-type": "application/json", **headers},
                                    body, "203.0.113.7"))


def test_the_platform_header_authenticates(rig):
    resp = register(rig, {EDGE_AUTH: f"Bearer {rig.session()}"})
    assert resp.status == 202, resp.body


def test_the_standard_header_still_authenticates(rig):
    resp = register(rig, {"authorization": f"Bearer {rig.session()}"})
    assert resp.status == 202, resp.body


def test_no_credential_under_either_name_is_refused(rig):
    resp = register(rig, {})
    assert resp.status == 401 and resp.body["error"]["code"] == "session_required"


def test_an_invalid_token_under_the_platform_header_is_refused(rig):
    resp = register(rig, {EDGE_AUTH: "Bearer made-up"})
    assert resp.status == 401 and resp.body["error"]["code"] == "session_invalid"


def test_admin_routes_read_the_platform_header(make_rig):
    rig = make_rig(RELAY_ADMIN_TOKEN="a" * 40)
    resp = rig.relay.handle(Request("POST", "/v1/admin/pause", {EDGE_AUTH: "Bearer " + "a" * 40}))
    assert resp.status == 200 and resp.body == {"paused": True}
    resp = rig.relay.handle(Request("POST", "/v1/admin/pause", {EDGE_AUTH: "Bearer wrong"}))
    assert resp.status == 401 and resp.body["error"]["code"] == "admin_required"


# ---------------------------------------------------------------------- the real handler on a loopback socket
@pytest.fixture
def wire(rig):
    server = make_server(rig.relay, "127.0.0.1", 0)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    conns = []

    def connect() -> socket.socket:
        sock = socket.create_connection(server.server_address, timeout=5)
        conns.append(sock)
        return sock

    yield connect
    for sock in conns:
        sock.close()
    server.shutdown()
    server.server_close()


def head(path: str, token: str | None = None, auth: str = "authorization", **extra: str) -> bytes:
    lines = [f"POST {path} HTTP/1.1", "Host: relay", "Content-Type: application/json"]
    if token:
        lines.append(f"{auth.title()}: Bearer {token}")
    lines += [f"{k.replace('_', '-')}: {v}" for k, v in extra.items()]
    return ("\r\n".join(lines) + "\r\n\r\n").encode()


def chunked(*parts: bytes) -> bytes:
    return b"".join(f"{len(p):x}\r\n".encode() + p + b"\r\n" for p in parts) + b"0\r\n\r\n"


def exchange(sock: socket.socket, raw: bytes) -> tuple[int, dict, dict]:
    sock.sendall(raw)
    resp = http.client.HTTPResponse(sock)
    resp.begin()
    body = json.loads(resp.read())
    return resp.status, {k.lower(): v for k, v in resp.getheaders()}, body


def assert_reusable(sock: socket.socket) -> None:
    status, _, body = exchange(sock, b"GET /healthz HTTP/1.1\r\nHost: relay\r\n\r\n")
    assert status == 200 and body["status"] == "ok"


def assert_closed(sock: socket.socket, headers: dict) -> None:
    assert headers.get("connection", "").lower() == "close"
    assert sock.recv(1024) == b""  # nothing left over was parsed as a further request


def payload(rig, i: int = 0) -> bytes:
    return json.dumps(rig.body(*spot(i), submission_id=f"e{i}")).encode()


def test_a_chunked_post_is_decoded(rig, wire):
    sock = wire()
    status, _, body = exchange(sock, head("/v1/registrations", rig.session(), Transfer_Encoding="chunked")
                               + chunked(payload(rig)))
    assert status == 202, body
    assert body["job"]["state"] == "submitted"
    assert_reusable(sock)


def test_the_edge_shape_end_to_end(rig, wire):
    """Exactly what the edge hands upstream: renamed credential, chunked body, no Content-Length."""
    sock = wire()
    status, _, body = exchange(sock, head("/v1/registrations", rig.session(), EDGE_AUTH, Transfer_Encoding="chunked")
                               + chunked(payload(rig)))
    assert status == 202, body
    assert_reusable(sock)


def test_a_multi_chunk_body_is_reassembled_in_order(rig, wire):
    sock = wire()
    raw = payload(rig)
    parts = [raw[i:i + 7] for i in range(0, len(raw), 7)]
    framed = chunked(*parts).replace(f"{len(parts[0]):x}\r\n".encode(), f"{len(parts[0]):x};ext=1\r\n".encode(), 1)
    status, _, body = exchange(sock, head("/v1/registrations", rig.session(), Transfer_Encoding="chunked")
                               + framed[:-2] + b"X-Trailer: 1\r\n\r\n")
    assert status == 202, body
    stored, sent = rig.store.get(body["job"]["job_id"]), json.loads(raw)
    assert (stored.submission_id, stored.lat, stored.lng) == ("e0", sent["fix"]["lat"], sent["fix"]["lng"])
    assert_reusable(sock)


def test_a_chunked_body_over_the_limit_is_413_and_closes(rig, wire):
    sock = wire()
    big = b"x" * 4096
    status, headers, body = exchange(sock, head("/v1/registrations", rig.session(), Transfer_Encoding="chunked")
                                     + chunked(*[big] * 5))
    assert status == 413 and body["error"]["code"] == "body_too_large"
    assert body["error"]["message"] == f"bodies are limited to {MAX_BODY_BYTES} bytes"
    assert_closed(sock, headers)


@pytest.mark.parametrize("framing", [b"zz\r\n{}\r\n0\r\n\r\n",  # not hex
                                     b"2\r\n{}XX0\r\n\r\n",  # no CRLF after the data
                                     b"5\r\n{}\r\n0\r\n\r\n"])  # length overruns the data
def test_malformed_chunked_framing_is_a_clean_400_and_closes(rig, wire, framing):
    sock = wire()
    status, headers, body = exchange(sock, head("/v1/registrations", rig.session(), Transfer_Encoding="chunked")
                                     + framing)
    assert status == 400 and body["error"]["code"] == "invalid_body"
    assert_closed(sock, headers)


def test_a_content_length_post_still_works(rig, wire):
    sock = wire()
    raw = payload(rig)
    status, headers, body = exchange(sock, head("/v1/registrations", rig.session(),
                                                Content_Length=str(len(raw)))
                                     + raw)
    assert status == 202, body
    assert "connection" not in headers
    assert_reusable(sock)


def test_a_content_length_over_the_limit_is_413_and_closes(rig, wire):
    sock = wire()
    status, headers, body = exchange(sock, head("/v1/registrations", rig.session(),
                                                Content_Length=str(MAX_BODY_BYTES + 1)) + b"x" * 64)
    assert status == 413 and body["error"]["code"] == "body_too_large"
    assert_closed(sock, headers)


def test_a_bare_connection_with_no_request_is_tolerated(rig, wire):
    wire().close()
    sock = wire()
    assert_reusable(sock)
