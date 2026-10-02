"""Relay settings from the process environment. Fail-closed: anything missing or malformed refuses to start.

The relay does not read the dashboard's .env or Streamlit Secrets. It has its own variables, prefixed RELAY_ where
they would otherwise clash, so a dashboard deployment can never hand its key to the relay or the other way round.
Every limit is the plan's default and can be overridden by its variable; none of them is tuned here.
"""
from __future__ import annotations

import json
import os
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path

from dashboard.config import (REPO_ROOT, ChainConfig, PrivateKeyError, Resolution, chain_config, default_chain_id,
                              resolve_proxy, validate_private_key)
from dashboard.h3_nullifier import DEFAULT_RESOLUTION

DEFAULT_DB = REPO_ROOT / "relay" / "var" / "relay.db"  # gitignored; never under /tmp, which this host wipes
_TOKEN_RE = re.compile(r"^[A-Za-z0-9_\-]{32,}$")


class ConfigError(RuntimeError):
    """The environment cannot produce a relay that is safe to start. The message names the variable, never a secret."""


@dataclass(frozen=True)
class Limits:
    """Area 3's limits table plus area 1's thresholds, as defaults. Windows are in seconds."""
    per_session: int = 3  # registrations per session token, over the session's lifetime
    per_ip_hour: int = 5
    per_ip_day: int = 20
    per_planter_day: int = 10
    max_trees_per_cell: int = 4  # R5 ceiling, counted over active (non-rejected) registrations
    global_per_day: int = 200  # counted from minted rows, not submissions
    collision_radius_m: float = 20.0  # R3
    max_accuracy_m: float = 30.0  # R4
    # Not in the plan's table, so they are new values rather than retuned ones: an open endpoint needs a key for the
    # per-session limit, and the key needs its own guard (sessions per IP), a lifetime, and a read limit.
    sessions_per_ip_hour: int = 4
    session_ttl_s: int = 86_400
    plot_reads_per_ip_hour: int = 120
    fix_max_age_s: int = 600
    fix_max_future_s: int = 60
    biomass_tolerance_rel: float = 0.02  # client estimate vs the relay's own, beyond which the client is stale
    biomass_tolerance_abs_kg: float = 0.5


@dataclass(frozen=True)
class Retry:
    backoff_s: tuple[float, ...] = (2.0, 10.0, 45.0)  # the plan's 2s / 10s / 45s
    stuck_after_s: float = 300.0  # a job in verified longer than this is the alert that matters
    idle_poll_s: float = 1.0
    daily_cap_defer_s: float = 300.0

    @property
    def max_attempts(self) -> int:
        """Broadcast attempts before broadcast_unconfirmed: the first, then one after each backoff step."""
        return len(self.backoff_s) + 1


@dataclass(frozen=True)
class RelayConfig:
    chain: ChainConfig
    rpc_url: str
    proxy: Resolution
    db_path: Path
    verifier_key: str = field(repr=False)
    admin_token: str | None = field(default=None, repr=False)
    host: str = "127.0.0.1"
    port: int = 8787
    dry_run: bool = False
    paused: bool = False
    trust_forwarded_for: bool = False
    max_fee_gwei: float = 250.0  # hard cap on maxFeePerGas; the 1 Oct pilot paid 200.0011 gwei
    # Fixed, not configurable: the index, every stored cell and every salt are resolution-12 facts.
    h3_resolution: int = DEFAULT_RESOLUTION
    species: tuple[str, ...] = ("unspecified",)
    denylist: tuple[tuple[tuple[float, float], ...], ...] = ()  # polygons of (lat, lng)
    limits: Limits = Limits()
    retry: Retry = Retry()

    @property
    def chain_id(self) -> int:
        return self.chain.chain_id

    def __repr__(self) -> str:  # never render the key or the admin token
        return (f"RelayConfig(chain_id={self.chain_id}, rpc_url={self.rpc_url!r}, proxy={self.proxy.address}, "
                f"db={self.db_path}, verifier_key=<set>, admin_token=<{'set' if self.admin_token else 'unset'}>, "
                f"dry_run={self.dry_run}, paused={self.paused})")

    __str__ = __repr__


def strict_flag(env: Mapping[str, str], key: str, default: bool = False) -> bool:
    """An on/off variable. Unset or empty keeps the default; an unrecognised value refuses to start, because a typo
    in DRY_RUN must not be what turns signing on."""
    raw = (env.get(key) or "").strip().lower()
    if not raw:
        return default
    if raw in ("1", "true", "yes", "on"):
        return True
    if raw in ("0", "false", "no", "off"):
        return False
    raise ConfigError(f"{key} must be one of 1/0/true/false/yes/no/on/off, got an unrecognised value")


def _number(env: Mapping[str, str], key: str, default, kind=int, minimum=0):
    raw = (env.get(key) or "").strip()
    if not raw:
        return default
    try:
        value = kind(raw)
    except ValueError:
        raise ConfigError(f"{key} must be a {kind.__name__}, got {raw!r}") from None
    if value < minimum:
        raise ConfigError(f"{key} must be at least {minimum}, got {value}")
    return value


def load_limits(env: Mapping[str, str]) -> Limits:
    d = Limits()
    return Limits(
        per_session=_number(env, "LIMIT_PER_SESSION", d.per_session, minimum=1),
        per_ip_hour=_number(env, "LIMIT_PER_IP_HOUR", d.per_ip_hour, minimum=1),
        per_ip_day=_number(env, "LIMIT_PER_IP_DAY", d.per_ip_day, minimum=1),
        per_planter_day=_number(env, "LIMIT_PER_PLANTER_DAY", d.per_planter_day, minimum=1),
        max_trees_per_cell=_number(env, "MAX_TREES_PER_CELL", d.max_trees_per_cell, minimum=1),
        global_per_day=_number(env, "LIMIT_GLOBAL_PER_DAY", d.global_per_day, minimum=1),
        collision_radius_m=_number(env, "COLLISION_RADIUS_M", d.collision_radius_m, float, minimum=1.0),
        max_accuracy_m=_number(env, "MAX_ACCURACY_M", d.max_accuracy_m, float, minimum=1.0),
        sessions_per_ip_hour=_number(env, "SESSIONS_PER_IP_HOUR", d.sessions_per_ip_hour, minimum=1),
        session_ttl_s=_number(env, "SESSION_TTL_S", d.session_ttl_s, minimum=60),
        plot_reads_per_ip_hour=_number(env, "PLOT_READS_PER_IP_HOUR", d.plot_reads_per_ip_hour, minimum=1),
        fix_max_age_s=_number(env, "FIX_MAX_AGE_S", d.fix_max_age_s, minimum=1),
        fix_max_future_s=_number(env, "FIX_MAX_FUTURE_S", d.fix_max_future_s),
        biomass_tolerance_rel=_number(env, "BIOMASS_TOLERANCE_REL", d.biomass_tolerance_rel, float, minimum=0.0),
        biomass_tolerance_abs_kg=_number(env, "BIOMASS_TOLERANCE_ABS_KG", d.biomass_tolerance_abs_kg, float,
                                         minimum=0.0),
    )


def load_retry(env: Mapping[str, str]) -> Retry:
    d = Retry()
    raw = (env.get("BACKOFF_S") or "").strip()
    backoff = d.backoff_s
    if raw:
        try:
            backoff = tuple(float(x) for x in raw.split(","))
        except ValueError:
            raise ConfigError(f"BACKOFF_S must be comma-separated seconds, got {raw!r}") from None
        if not backoff or any(b < 0 for b in backoff):
            raise ConfigError("BACKOFF_S must list at least one non-negative delay")
    return Retry(backoff_s=backoff,
                 stuck_after_s=_number(env, "STUCK_AFTER_S", d.stuck_after_s, float, minimum=1.0))


def load_denylist(path: str | None) -> tuple[tuple[tuple[float, float], ...], ...]:
    """DENYLIST_FILE: JSON list of polygons, each a list of [lat, lng] vertices. Unset means no excluded areas."""
    if not path:
        return ()
    try:
        data = json.loads(Path(path).read_text())
        polys = tuple(tuple((float(lat), float(lng)) for lat, lng in poly) for poly in data)
    except (OSError, ValueError, TypeError) as exc:
        raise ConfigError(f"DENYLIST_FILE {path}: not a JSON list of [lat, lng] polygons ({exc})") from None
    if any(len(p) < 3 for p in polys):
        raise ConfigError(f"DENYLIST_FILE {path}: every polygon needs at least three vertices")
    return polys


def load_config(env: Mapping[str, str] | None = None) -> RelayConfig:
    env = os.environ if env is None else env
    try:
        key = validate_private_key(env.get("RELAY_VERIFIER_KEY"))
    except PrivateKeyError as exc:
        raise ConfigError(f"RELAY_VERIFIER_KEY: {exc}".replace("PRIVATE_KEY", "the key")) from None
    if not key:
        raise ConfigError("RELAY_VERIFIER_KEY is not set: a relay that cannot sign refuses to start")

    admin = (env.get("RELAY_ADMIN_TOKEN") or "").strip() or None
    if admin and not _TOKEN_RE.match(admin):
        raise ConfigError("RELAY_ADMIN_TOKEN must be at least 32 characters of [A-Za-z0-9_-]")

    try:
        chain = chain_config(_number(env, "RELAY_CHAIN_ID", None) or default_chain_id())
        proxy_env = {k: env[k] for k in ("PROXY_ADDRESS", "PROXY_DEPLOY_BLOCK") if env.get(k)}
        proxy = resolve_proxy(REPO_ROOT, proxy_env, chain.chain_id)
    except ConfigError:
        raise
    except Exception as exc:  # ChainSelectionError, ProxyResolutionError
        raise ConfigError(str(exc)) from None

    species = tuple(s.strip() for s in (env.get("RELAY_SPECIES") or "").split(",") if s.strip())
    return RelayConfig(
        chain=chain,
        rpc_url=(env.get("RELAY_RPC_URL") or "").strip() or chain.rpc_url,
        proxy=proxy,
        db_path=Path((env.get("RELAY_DB") or "").strip() or DEFAULT_DB),
        verifier_key=key,
        admin_token=admin,
        host=(env.get("RELAY_HOST") or "").strip() or "127.0.0.1",
        port=_number(env, "RELAY_PORT", 8787, minimum=1),
        dry_run=strict_flag(env, "DRY_RUN"),
        paused=strict_flag(env, "PAUSED"),
        trust_forwarded_for=strict_flag(env, "TRUST_FORWARDED_FOR"),
        max_fee_gwei=_number(env, "MAX_FEE_GWEI", 250.0, float, minimum=0.001),
        species=species or ("unspecified",),
        denylist=load_denylist((env.get("DENYLIST_FILE") or "").strip() or None),
        limits=load_limits(env),
        retry=load_retry(env),
    )
