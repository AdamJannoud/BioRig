"""Areas 2 + 3: the HTTP surface. Standard library only (http.server), so the relay adds no runtime dependency.

ROUTES is the route table; docs/relay-api.md documents exactly these, and a test holds the two together.
`Relay.handle` is a pure request -> response function, so the suite drives it directly; `make_server` wraps it in a
ThreadingHTTPServer. No X-Frame-Options and no frame-ancestors are ever sent.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
import re
import secrets
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit

import h3

from .broadcaster import Broadcaster, TransientChainError
from .config import RelayConfig
from .machine import DAY_S, Machine
from .plot_index import PlotIndex, haversine_m
from .store import STATES, Registration, StateConflict, Store
from .validate import Refusal, parse_submission

log = logging.getLogger("relay.service")
MAX_BODY_BYTES = 16 * 1024
MAX_LINE_BYTES = 1024
MAX_TRAILERS = 32
HOUR_S = 3_600
_JOB_ID = r"(?P<job_id>[0-9a-f]{32})"
_CELL = r"(?P<cell>[0-9a-fA-F]{15,16})"
INSTALL_ID_HEADER = "x-biorig-install-id"  # Request.headers names are lower-cased, so the read is case-insensitive
_INSTALL_ID = re.compile(r"^[0-9a-f]{32}$")


class BootError(RuntimeError):
    """The relay must not listen: wrong chain, no role, or the chain cannot be asked."""


@dataclass(frozen=True)
class Route:
    method: str
    template: str  # as documented, e.g. /v1/registrations/{job_id}
    pattern: str
    handler: str
    auth: str  # none | session | admin


ROUTES: tuple[Route, ...] = (
    Route("POST", "/v1/sessions", r"/v1/sessions", "create_session", "none"),
    Route("POST", "/v1/registrations", r"/v1/registrations", "submit", "session"),
    Route("GET", "/v1/registrations/{job_id}", rf"/v1/registrations/{_JOB_ID}", "get_job", "none"),
    Route("GET", "/v1/plots/{cell}", rf"/v1/plots/{_CELL}", "get_plot", "none"),
    Route("GET", "/healthz", r"/healthz", "health", "none"),
    Route("GET", "/v1/admin/jobs", r"/v1/admin/jobs", "admin_jobs", "admin"),
    Route("POST", "/v1/admin/jobs/{job_id}/reject", rf"/v1/admin/jobs/{_JOB_ID}/reject", "admin_reject", "admin"),
    Route("POST", "/v1/admin/jobs/{job_id}/retry", rf"/v1/admin/jobs/{_JOB_ID}/retry", "admin_retry", "admin"),
    Route("POST", "/v1/admin/pause", r"/v1/admin/pause", "admin_pause", "admin"),
    Route("POST", "/v1/admin/resume", r"/v1/admin/resume", "admin_resume", "admin"),
)


@dataclass
class Request:
    method: str
    path: str  # may carry a query string
    headers: dict[str, str] = field(default_factory=dict)  # lower-cased names
    body: bytes = b""
    client_ip: str = "127.0.0.1"


@dataclass
class Response:
    status: int
    body: dict
    headers: dict[str, str] = field(default_factory=dict)


def _ts(value: float | None) -> int | None:
    return None if value is None else int(value)


def job_view(reg: Registration, admin: bool = False) -> dict:
    """A registration as the API shows it. Coordinates are personal data: only the admin view carries them."""
    view = {
        "job_id": reg.id,
        "submission_id": reg.submission_id,
        "state": reg.state,
        "cell": reg.cell,
        "tree_ordinal": reg.tree_ordinal,
        "salt": reg.salt,
        "nullifier": reg.nullifier,
        "planter_address": reg.planter_address,
        "tree": {"species": reg.species, "dbh_cm": reg.dbh_cm, "biomass_kg": reg.biomass_kg,
                 "co2e_kg": reg.co2e_kg, "mint_biomass_kg": reg.mint_biomass_kg},
        "attempts": reg.attempts,
        "next_attempt_at": _ts(reg.next_attempt_at),
        "last_error_code": reg.last_error_code,
        "mint": None if reg.state != "minted" else {"token_id": reg.token_id, "tba": reg.tba,
                                                    "tx_hash": reg.tx_hash, "block": reg.block},
        "created_at": _ts(reg.created_at),
        "updated_at": _ts(reg.updated_at),
        "verified_at": _ts(reg.verified_at),
        "minted_at": _ts(reg.minted_at),
    }
    if admin:
        view.update(lat=reg.lat, lng=reg.lng, accuracy_m=reg.accuracy_m, location_source=reg.location_source,
                    last_error=reg.last_error, nonce=reg.nonce, gas_used=reg.gas_used, fee_wei=reg.fee_wei,
                    decided_by=reg.decided_by, photo_sha256=reg.photo_sha256,
                    client_biomass_kg=reg.client_biomass_kg, client_co2e_kg=reg.client_co2e_kg)
    return view


def boot(config: RelayConfig, broadcaster: Broadcaster) -> dict:
    """Phase 0's assertion: the RPC is the configured chain and the signer holds VERIFIER_ROLE, or no start."""
    try:
        rpc_chain = broadcaster.chain_id()
        if rpc_chain != config.chain_id:
            raise BootError(f"RPC {config.rpc_url} reports chain {rpc_chain}, the relay is configured for "
                            f"chain {config.chain_id}")
        if not broadcaster.signer_is_verifier():
            raise BootError(f"signer {broadcaster.signer} does not hold VERIFIER_ROLE on proxy "
                            f"{config.proxy.address} (chain {config.chain_id}); a relay that cannot sign refuses "
                            "to start")
    except TransientChainError as exc:
        raise BootError(f"cannot read the chain to check the signer's role: {exc}") from None
    return {"chain_id": rpc_chain, "signer": broadcaster.signer, "signer_is_verifier": True}


class Relay:
    ROLE_RECHECK_S = 60.0

    def __init__(self, config: RelayConfig, store: Store, broadcaster: Broadcaster, machine: Machine | None = None,
                 clock: Callable[[], float] = time.time):
        self.config = config
        self.limits = config.limits
        self.store = store
        self.broadcaster = broadcaster
        self.clock = clock
        self.machine = machine or Machine(store, broadcaster, retry=config.retry, limits=config.limits,
                                          dry_run=config.dry_run, paused=config.paused, clock=clock)
        self.index = PlotIndex(store, config.limits, config.denylist, config.h3_resolution)
        self._intake = threading.Lock()  # limits check -> index decision -> allocation -> insert, as one step
        self._role = (True, clock())  # boot() proved it; re-read at most every ROLE_RECHECK_S for /healthz
        self._compiled = [(r, re.compile(r.pattern + r"\Z")) for r in ROUTES]

    # ------------------------------------------------------------------ dispatch
    def handle(self, req: Request) -> Response:
        split = urlsplit(req.path)
        path = split.path.rstrip("/") or "/"
        allowed = []
        for route, rx in self._compiled:
            m = rx.match(path)
            if not m:
                continue
            if route.method != req.method:
                allowed.append(route.method)
                continue
            try:
                ctx = self._authorise(route, req)
                return getattr(self, route.handler)(req, m.groupdict(), ctx, parse_qs(split.query))
            except Refusal as exc:
                return self._refusal(exc)
            except Exception:
                log.exception("unhandled error on %s %s", req.method, path)
                return Response(500, {"error": {"code": "internal", "message": "internal error"}})
        if allowed:
            return Response(405, {"error": {"code": "method_not_allowed", "message": f"{req.method} not allowed"}},
                            {"Allow": ", ".join(sorted(set(allowed)))})
        return Response(404, {"error": {"code": "not_found", "message": "no such endpoint"}})

    @staticmethod
    def _refusal(exc: Refusal) -> Response:
        headers = {}
        if exc.status == 429 and "retry_after_s" in exc.detail:
            headers["Retry-After"] = str(exc.detail["retry_after_s"])
        return Response(exc.status, exc.body(), headers)

    def client_ip(self, req: Request) -> str:
        # Off by default, and the deployment never sets TRUST_FORWARDED_FOR: behind the platform edge X-Forwarded-For
        # is whatever the caller wrote, so honouring it would let anyone pick their own bucket. It stays only for a
        # deployment behind a proxy of its own that overwrites the header.
        if self.config.trust_forwarded_for:
            fwd = req.headers.get("x-forwarded-for", "").split(",")[0].strip()
            if fwd:
                return fwd
        return req.client_ip

    def caller(self, req: Request) -> tuple[str, str]:
        """The key the per-caller limits count on, and the family name their refusals carry: the app's install id
        when X-BioRig-Install-Id is present and well-formed, else the caller's address exactly as before the header
        existed (an older APK, loopback, the suite). Every outside caller shares the edge's one address."""
        install_id = req.headers.get(INSTALL_ID_HEADER, "").strip().lower()
        if _INSTALL_ID.match(install_id):
            return f"install:{install_id}", "device"
        return self.client_ip(req), "ip"

    @staticmethod
    def _bearer(req: Request) -> str | None:
        value = req.headers.get("x-sandbox-forwarded-authorization") or req.headers.get("authorization", "")
        return value[7:].strip() if value[:7].lower() == "bearer " else None

    def _authorise(self, route: Route, req: Request) -> dict:
        if route.auth == "session":
            token = self._bearer(req)
            if not token:
                raise Refusal(401, "session_required", "Authorization: Bearer <session_token> is required; "
                                                       "obtain one from POST /v1/sessions")
            sid = hashlib.sha256(token.encode()).hexdigest()
            row = self.store.session(sid)
            if row is None:
                raise Refusal(401, "session_invalid", "unknown session token")
            if row["expires_at"] <= self.clock():
                raise Refusal(401, "session_expired", "session token expired; obtain a new one")
            return {"session_id": sid, "session_created_at": row["created_at"]}
        if route.auth == "admin":
            if not self.config.admin_token:  # admin surface disabled: indistinguishable from absent
                raise Refusal(404, "not_found", "no such endpoint")
            token = self._bearer(req) or ""
            if not hmac.compare_digest(token.encode(), self.config.admin_token.encode()):
                raise Refusal(401, "admin_required", "admin token required")
            return {"admin": True}
        return {}

    @staticmethod
    def _json(req: Request, required: bool = True):
        if not req.body:
            if required:
                raise Refusal(400, "invalid_json", "a JSON body is required")
            return {}
        ctype = req.headers.get("content-type", "").split(";")[0].strip().lower()
        if ctype != "application/json":
            raise Refusal(415, "unsupported_media_type", "Content-Type must be application/json")
        try:
            return json.loads(req.body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise Refusal(400, "invalid_json", "the body is not valid JSON") from None

    def _limit(self, rules: list[tuple[str, str, int, float]], record: bool) -> None:
        now = self.clock()
        refused = self.store.consume(rules, now) if record else self.store.check_limits(rules, now)
        if refused:
            name, retry_after = refused
            raise Refusal(429, "rate_limited", f"limit {name} reached", limit=name, retry_after_s=retry_after)

    # ------------------------------------------------------------------ sessions
    def create_session(self, req, params, ctx, query) -> Response:
        key, per = self.caller(req)
        # The whole-relay ceiling is what bounds rotation: clearing the app's data buys a fresh install id, and with
        # it a fresh per-device allowance, but never a fresh relay-wide one.
        self._limit([(f"sessions_per_{per}_hour", f"session_create:{key}", self.limits.sessions_per_ip_hour, HOUR_S),
                     ("sessions_global_hour", "session_create:*", self.limits.sessions_global_hour, HOUR_S)],
                    record=True)
        token = secrets.token_urlsafe(32)
        created, expires = self.store.create_session(hashlib.sha256(token.encode()).hexdigest(),
                                                     self.limits.session_ttl_s)
        return Response(201, {"session_token": token, "created_at": int(created), "expires_at": int(expires),
                              "registrations_allowed": self.limits.per_session})

    # ------------------------------------------------------------------ registrations
    def submit(self, req, params, ctx, query) -> Response:
        body = self._json(req)
        sid = ctx["session_id"]

        # A client retry carrying the same submission_id gets its job back; it is not a second registration.
        if isinstance(body, dict) and isinstance(body.get("submission_id"), str):
            prior = self.store.by_submission(sid, body["submission_id"])
            if prior is not None:
                same = (str(body.get("planter_address", "")).lower() == prior.planter_address.lower()
                        and isinstance(body.get("tree"), dict) and body["tree"].get("dbh_cm") == prior.dbh_cm)
                if not same:
                    raise Refusal(409, "submission_conflict",
                                  "this submission_id already names a different registration", job_id=prior.id)
                return Response(200, {"job": job_view(prior), "outcome": "replayed"})

        key, per = self.caller(req)
        bucket = key if per == "device" else f"ip:{key}"
        with self._intake:
            now = self.clock()
            self._limit([(f"per_{per}_hour", bucket, self.limits.per_ip_hour, HOUR_S),
                         (f"per_{per}_day", bucket, self.limits.per_ip_day, DAY_S)], record=True)
            sub = parse_submission(body, self.limits, self.config.species, now)
            self._limit([("per_session", f"session:{sid}", self.limits.per_session, self.limits.session_ttl_s),
                         ("per_planter_day", f"planter:{sub.planter_address.lower()}", self.limits.per_planter_day,
                          DAY_S)], record=False)
            if self.store.minted_since(now - DAY_S) >= self.limits.global_per_day:
                oldest = self.store.oldest_mint_since(now - DAY_S) or now
                raise Refusal(429, "rate_limited", "the daily mint cap is reached", limit="global_per_day",
                              retry_after_s=max(1, int(oldest + DAY_S - now) + 1))

            decision = self.index.decide(sub.lat, sub.lng, sub.planter_address)
            if decision.kind != "new":
                return self._existing(decision.existing, decision.distance_m, sub.planter_address, "same_tree")

            def make_values(ordinal, salt, nullifier):
                return {"submission_id": sub.submission_id, "session_id": sid, "lat": sub.lat, "lng": sub.lng,
                        "accuracy_m": sub.accuracy_m, "location_source": "fix", "fix_captured_at": sub.captured_at,
                        "species": sub.species, "dbh_cm": sub.dbh_cm, "client_biomass_kg": sub.client_biomass_kg,
                        "client_co2e_kg": sub.client_co2e_kg, "biomass_kg": sub.biomass_kg,
                        "co2e_kg": sub.co2e_kg, "mint_biomass_kg": sub.mint_biomass_kg,
                        "planter_address": sub.planter_address, "photo_sha256": sub.photo_sha256,
                        "state": "submitted", "next_attempt_at": None}

            reg, created = self.index.allocate(decision.cell, make_values, guard=self._recover_if_active)
            if not created:
                d = haversine_m(sub.lat, sub.lng, reg.lat, reg.lng)
                return self._existing(reg, d, sub.planter_address, "recovered")
            self.store.record_events([f"session:{sid}", f"planter:{sub.planter_address.lower()}"], now)
            return Response(202, {"job": job_view(reg), "outcome": "created"})

    def _existing(self, reg: Registration, distance_m: float, planter: str, outcome: str) -> Response:
        """R3: inside the collision radius it is the same tree. The same planter gets it back; anyone else is
        refused with the distance and the existing token id."""
        if reg.planter_address.lower() == planter.lower():
            return Response(200, {"job": job_view(reg), "outcome": outcome, "distance_m": round(distance_m, 2)})
        raise Refusal(409, "collision",
                      f"a registered tree is {distance_m:.1f} m away, inside the "
                      f"{self.limits.collision_radius_m:g} m collision radius",
                      distance_m=round(distance_m, 2), collision_radius_m=self.limits.collision_radius_m,
                      existing={"cell": reg.cell, "tree_ordinal": reg.tree_ordinal, "state": reg.state,
                                "token_id": reg.token_id})

    def _recover_if_active(self, ordinal: int, salt: str, nullifier: str) -> Registration | None:
        """Allocation guard: the candidate nullifier is already active on chain but has no row here (a lost store,
        or a mint from outside this relay). Recover the mint and record it instead of allocating over it."""
        if self.store.by_nullifier(nullifier) is not None:  # cannot happen under the cell lock; never overwrite
            raise Refusal(503, "index_inconsistent", "allocated nullifier already has a row")
        nb = bytes.fromhex(nullifier[2:])
        try:
            if not self.broadcaster.is_nullifier_active(nb):
                return None
            res = self.broadcaster.find_mint(nb)
        except TransientChainError:
            raise Refusal(503, "chain_unavailable", "the chain could not be asked whether this plot is taken; "
                                                    "retry later", retry_after_s=10) from None
        if res is None:
            raise Refusal(503, "recovery_pending", "this plot's nullifier is active on chain but its mint record "
                                                   "could not be read yet; retry later")
        cell = salt.split(":")[2]
        lat, lng = h3.cell_to_latlng(cell)
        now = self.clock()
        return self.store.insert({
            "nullifier": nullifier, "cell": cell, "tree_ordinal": ordinal, "salt": salt, "lat": lat, "lng": lng,
            "location_source": "cell_centroid", "dbh_cm": res.dbh or 0, "mint_biomass_kg": res.biomass or 0,
            "planter_address": res.planter or "", "state": "minted", "token_id": res.token_id, "tba": res.tba,
            "tx_hash": res.tx_hash, "block": res.block, "minted_at": now, "decided_by": "recovered:chain",
            "last_error": "recovered from the chain at intake: active nullifier with no local row"})

    def get_job(self, req, params, ctx, query) -> Response:
        reg = self.store.get(params["job_id"])
        if reg is None:
            raise Refusal(404, "job_not_found", "no registration with this job id")
        return Response(200, {"job": job_view(reg)})

    # ------------------------------------------------------------------ plots
    def get_plot(self, req, params, ctx, query) -> Response:
        cell = params["cell"].lower()
        if not h3.is_valid_cell(cell) or h3.get_resolution(cell) != self.config.h3_resolution:
            raise Refusal(400, "invalid_cell", f"not a valid resolution-{self.config.h3_resolution} H3 cell")
        key, per = self.caller(req)
        self._limit([(f"plot_reads_per_{per}_hour", f"plot_read:{key}", self.limits.plot_reads_per_ip_hour, HOUR_S)],
                    record=True)
        trees = self.store.in_cells([cell])
        nearby = self.store.in_cells(self.index.neighbourhood(cell))
        return Response(200, {
            "cell": cell, "resolution": self.config.h3_resolution, "active": len(trees),
            "max_trees_per_cell": self.limits.max_trees_per_cell,
            "full": len(trees) >= self.limits.max_trees_per_cell,
            "neighbourhood_active": len(nearby), "collision_radius_m": self.limits.collision_radius_m,
            "trees": [{"tree_ordinal": t.tree_ordinal, "state": t.state, "token_id": t.token_id} for t in trees]})

    # ------------------------------------------------------------------ health
    def signer_role(self) -> bool:
        ok, at = self._role
        if self.clock() - at >= self.ROLE_RECHECK_S:
            try:
                ok = bool(self.broadcaster.signer_is_verifier())
            except TransientChainError:
                pass  # keep the last known answer; role_checked_at shows its age
            else:
                self._role = (ok, self.clock())
        return self._role[0]

    def health_payload(self) -> dict:
        now = self.clock()
        oldest = self.store.oldest_verified_at()
        role = self.signer_role()
        stuck = len(self.store.stuck(now, self.config.retry.stuck_after_s))
        return {
            "status": "ok" if role and not stuck else "degraded",
            "chain_id": self.config.chain_id,
            "proxy": self.config.proxy.address,
            "signer": self.broadcaster.signer,
            "signer_is_verifier": role,
            "role_checked_at": int(self._role[1]),
            "dry_run": self.config.dry_run,
            "paused": self.machine.paused,
            "queue": self.store.counts_by_state(),
            "oldest_verified_age_s": None if oldest is None else int(now - oldest),
            "stuck": stuck,
            "mints_24h": self.store.minted_since(now - DAY_S),
            "global_per_day": self.limits.global_per_day,
            "spend_24h_wei": str(self.store.fee_wei_since(now - DAY_S)),
            "schema_version": self.store.schema_version,
        }

    def health(self, req, params, ctx, query) -> Response:
        payload = self.health_payload()
        return Response(200 if payload["signer_is_verifier"] else 503, payload)

    # ------------------------------------------------------------------ admin
    def admin_jobs(self, req, params, ctx, query) -> Response:
        state = (query.get("state") or [None])[0]
        if state is not None and state not in STATES:
            raise Refusal(400, "invalid_field", f"state must be one of {', '.join(STATES)}", field="state")
        if (query.get("stuck") or ["0"])[0] == "1":
            jobs = self.store.stuck(self.clock(), self.config.retry.stuck_after_s)
        else:
            jobs = self.store.list_jobs(state)
        return Response(200, {"jobs": [job_view(j, admin=True) for j in jobs]})

    def _admin_job(self, params) -> Registration:
        reg = self.store.get(params["job_id"])
        if reg is None:
            raise Refusal(404, "job_not_found", "no registration with this job id")
        return reg

    def admin_reject(self, req, params, ctx, query) -> Response:
        body = self._json(req, required=False)
        reason = body.get("reason") if isinstance(body, dict) else None
        if not isinstance(reason, str) or not 1 <= len(reason) <= 200:
            raise Refusal(400, "invalid_field", "reason: 1-200 characters required", field="reason")
        reg = self._admin_job(params)
        if reg.state not in ("submitted", "verified"):
            raise Refusal(409, "invalid_transition", f"a {reg.state} job cannot be rejected", state=reg.state)
        if reg.attempts > 0:  # something was sent: only the worker, which re-checks the chain, may end it
            raise Refusal(409, "broadcast_in_history", "this job has been broadcast; use retry, or let the worker "
                                                        "settle it", attempts=reg.attempts)
        try:
            reg = self.store.update(reg.id, expect_state=reg.state, state="rejected", next_attempt_at=None,
                                    last_error_code="operator_rejected", last_error=reason, decided_by="admin")
        except StateConflict as exc:
            raise Refusal(409, "invalid_transition", str(exc)) from None
        return Response(200, {"job": job_view(reg, admin=True)})

    def admin_retry(self, req, params, ctx, query) -> Response:
        reg = self._admin_job(params)
        if reg.state not in ("submitted", "verified"):
            raise Refusal(409, "invalid_transition", f"a {reg.state} job is terminal", state=reg.state)
        reg = self.store.update(reg.id, expect_state=reg.state, next_attempt_at=self.clock())
        return Response(200, {"job": job_view(reg, admin=True)})

    def admin_pause(self, req, params, ctx, query) -> Response:
        self.machine.set_paused(True)
        return Response(200, {"paused": True})

    def admin_resume(self, req, params, ctx, query) -> Response:
        self.machine.set_paused(False)
        return Response(200, {"paused": self.machine.paused, "paused_by_env": self.machine.paused_by_env})


# ---------------------------------------------------------------------- HTTP adapter
def _too_large() -> Refusal:
    return Refusal(413, "body_too_large", f"bodies are limited to {MAX_BODY_BYTES} bytes")


def _malformed(what: str) -> Refusal:
    return Refusal(400, "invalid_body", f"malformed chunked body: {what}")


def _line(rfile) -> bytes:
    line = rfile.readline(MAX_LINE_BYTES + 1)
    if not line.endswith(b"\n") or len(line) > MAX_LINE_BYTES:
        raise _malformed("a framing line is truncated or too long")
    return line


def read_chunked(rfile, limit: int) -> bytes:
    """Decode a chunked request body, refusing once the decoded bytes would exceed `limit`."""
    body = bytearray()
    while True:
        size = _line(rfile).split(b";", 1)[0].strip()
        if not re.fullmatch(rb"[0-9a-fA-F]{1,16}", size):
            raise _malformed("a chunk size is not hex")
        n = int(size, 16)
        if n == 0:
            break
        if len(body) + n > limit:
            raise _too_large()
        data = rfile.read(n)
        if len(data) != n or rfile.read(2) != b"\r\n":
            raise _malformed("a chunk does not match its size")
        body += data
    for _ in range(MAX_TRAILERS + 1):
        if _line(rfile).strip() == b"":
            return bytes(body)
    raise _malformed("too many trailers")


def make_handler(relay: Relay):
    class Handler(BaseHTTPRequestHandler):
        server_version = "biorig-relay"
        sys_version = ""
        protocol_version = "HTTP/1.1"

        def _read_body(self) -> bytes:
            coding = self.headers.get("Transfer-Encoding")
            if coding:
                if coding.split(",")[-1].strip().lower() != "chunked":
                    raise Refusal(400, "invalid_body", "Transfer-Encoding must end in chunked")
                return read_chunked(self.rfile, MAX_BODY_BYTES)
            length = self.headers.get("Content-Length")
            try:
                n = int(length) if length else 0
            except ValueError:
                n = -1
            if n < 0 or n > MAX_BODY_BYTES:
                raise _too_large()
            return self.rfile.read(n) if n else b""

        def _dispatch(self):
            try:
                body = self._read_body()
            except Refusal as exc:
                self.close_connection = True
                resp = Response(exc.status, exc.body())
            else:
                req = Request(self.command, self.path, {k.lower(): v for k, v in self.headers.items()}, body,
                              self.client_address[0])
                resp = relay.handle(req)
            data = json.dumps(resp.body, separators=(",", ":")).encode()
            self.send_response(resp.status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            for k, v in resp.headers.items():
                self.send_header(k, v)
            if self.close_connection:
                self.send_header("Connection", "close")
            self.end_headers()
            self.wfile.write(data)

        do_GET = do_POST = do_PUT = do_DELETE = do_PATCH = _dispatch

        def log_message(self, fmt, *args):
            log.info("%s %s", self.address_string(), fmt % args)

    return Handler


def make_server(relay: Relay, host: str, port: int) -> ThreadingHTTPServer:
    server = ThreadingHTTPServer((host, port), make_handler(relay))
    server.daemon_threads = True
    return server
