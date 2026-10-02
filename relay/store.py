"""SQLite (WAL) store: the registrations table that is the queue, sessions, and the rate-limit ledger.

The queue is not a broker; it is a state column with UNIQUE(nullifier). One connection, guarded by a re-entrant
lock, serves every thread; `transaction()` takes SQLite's write lock (BEGIN IMMEDIATE) for the read-then-write
sequences that must not interleave. Migrations are the numbered files in relay/migrations, tracked in
PRAGMA user_version.
"""
from __future__ import annotations

import math
import re
import sqlite3
import threading
import time
import uuid
from collections.abc import Callable, Iterable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, fields
from pathlib import Path

MIGRATIONS_DIR = Path(__file__).resolve().parent / "migrations"
STATES = ("submitted", "verified", "minted", "rejected")
ACTIVE_STATES = ("submitted", "verified", "minted")
_MIGRATION_RE = re.compile(r"^(\d{3})_[a-z0-9_]+\.sql$")


class StoreError(RuntimeError):
    pass


class StateConflict(StoreError):
    """A transition found the row in a different state than expected (another actor moved it first)."""


@dataclass(frozen=True)
class Registration:
    id: str
    submission_id: str | None
    session_id: str | None
    nullifier: str
    cell: str
    tree_ordinal: int
    salt: str
    lat: float
    lng: float
    accuracy_m: float | None
    location_source: str
    fix_captured_at: int | None
    species: str | None
    dbh_cm: int
    client_biomass_kg: float | None
    client_co2e_kg: float | None
    biomass_kg: float | None
    co2e_kg: float | None
    mint_biomass_kg: int
    planter_address: str
    photo_sha256: str | None
    state: str
    attempts: int
    next_attempt_at: float | None
    last_error_code: str | None
    last_error: str | None
    nonce: int | None
    tx_hash: str | None
    token_id: int | None
    tba: str | None
    block: int | None
    gas_used: int | None
    fee_wei: str | None
    created_at: float
    updated_at: float
    verified_at: float | None
    minted_at: float | None
    decided_by: str | None

    @property
    def nullifier_bytes(self) -> bytes:
        return bytes.fromhex(self.nullifier.removeprefix("0x"))

    @property
    def active(self) -> bool:
        return self.state in ACTIVE_STATES


COLUMNS = tuple(f.name for f in fields(Registration))


def migration_files(directory: Path = MIGRATIONS_DIR) -> list[tuple[int, Path]]:
    found = []
    for path in sorted(directory.iterdir()):
        m = _MIGRATION_RE.match(path.name)
        if m:
            found.append((int(m.group(1)), path))
    versions = [v for v, _ in found]
    if versions != list(range(1, len(versions) + 1)):
        raise StoreError(f"migrations must be numbered 001.. without gaps, found {versions}")
    return found


class Store:
    def __init__(self, path: Path | str, clock: Callable[[], float] = time.time):
        self.path = str(path)
        self.clock = clock
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(self.path, isolation_level=None, check_same_thread=False, timeout=5.0)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA synchronous=NORMAL")
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._conn.execute("PRAGMA busy_timeout=5000")
        self.migrate()

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    # ------------------------------------------------------------------ plumbing
    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        """BEGIN IMMEDIATE ... COMMIT under the store lock. Re-entrant: a nested call joins the outer transaction."""
        with self._lock:
            if self._conn.in_transaction:
                yield self._conn
                return
            self._conn.execute("BEGIN IMMEDIATE")
            try:
                yield self._conn
            except BaseException:
                self._conn.execute("ROLLBACK")
                raise
            self._conn.execute("COMMIT")

    def _all(self, sql: str, params: Iterable = ()) -> list[sqlite3.Row]:
        with self._lock:
            return self._conn.execute(sql, tuple(params)).fetchall()

    def _one(self, sql: str, params: Iterable = ()) -> sqlite3.Row | None:
        with self._lock:
            return self._conn.execute(sql, tuple(params)).fetchone()

    @property
    def schema_version(self) -> int:
        return int(self._one("PRAGMA user_version")[0])

    def migrate(self) -> int:
        """Apply every migration above user_version, each in its own transaction. Returns the new version."""
        with self._lock:
            current = self.schema_version
            for version, path in migration_files():
                if version <= current:
                    continue
                with self.transaction() as conn:
                    for statement in _split_sql(path.read_text()):
                        conn.execute(statement)
                    conn.execute(f"PRAGMA user_version = {version}")
            return self.schema_version

    # ------------------------------------------------------------------ meta
    def meta(self, key: str) -> str | None:
        row = self._one("SELECT value FROM meta WHERE key = ?", (key,))
        return row["value"] if row else None

    def set_meta(self, key: str, value: str) -> None:
        with self.transaction() as conn:
            conn.execute("INSERT INTO meta (key, value) VALUES (?, ?) "
                         "ON CONFLICT(key) DO UPDATE SET value = excluded.value", (key, value))

    def bind_chain(self, chain_id: int) -> None:
        """A store holds one chain's registrations. The first open records the chain; any other chain is refused."""
        with self.transaction():
            bound = self.meta("chain_id")
            if bound is None:
                self.set_meta("chain_id", str(chain_id))
            elif int(bound) != int(chain_id):
                raise StoreError(f"{self.path} holds chain {bound}'s registrations, not chain {chain_id}'s")

    # ------------------------------------------------------------------ registrations
    def insert(self, values: dict) -> Registration:
        now = self.clock()
        row = {"id": uuid.uuid4().hex, "attempts": 0, "created_at": now, "updated_at": now, **values}
        unknown = set(row) - set(COLUMNS)
        if unknown:
            raise StoreError(f"unknown registration columns {sorted(unknown)}")
        cols = ", ".join(row)
        marks = ", ".join("?" for _ in row)
        with self.transaction() as conn:
            conn.execute(f"INSERT INTO registrations ({cols}) VALUES ({marks})", tuple(row.values()))
        return self.get(row["id"])

    @staticmethod
    def _reg(row: sqlite3.Row | None) -> Registration | None:
        return Registration(**{c: row[c] for c in COLUMNS}) if row else None

    def get(self, job_id: str) -> Registration | None:
        return self._reg(self._one("SELECT * FROM registrations WHERE id = ?", (job_id,)))

    def by_nullifier(self, nullifier: str) -> Registration | None:
        return self._reg(self._one("SELECT * FROM registrations WHERE nullifier = ?", (nullifier.lower(),)))

    def by_submission(self, session_id: str, submission_id: str) -> Registration | None:
        return self._reg(self._one(
            "SELECT * FROM registrations WHERE session_id = ? AND submission_id = ? ORDER BY created_at LIMIT 1",
            (session_id, submission_id)))

    def next_ordinal(self, cell: str) -> int:
        """One past the highest ordinal ever used in the cell, rejected rows included, so a nullifier is never
        derived twice."""
        row = self._one("SELECT COALESCE(MAX(tree_ordinal) + 1, 0) FROM registrations WHERE cell = ?", (cell,))
        return int(row[0])

    def in_cells(self, cells: Iterable[str], active_only: bool = True) -> list[Registration]:
        cells = list(cells)
        if not cells:
            return []
        marks = ", ".join("?" for _ in cells)
        sql = f"SELECT * FROM registrations WHERE cell IN ({marks})"
        if active_only:
            sql += " AND state <> 'rejected'"
        return [self._reg(r) for r in self._all(sql + " ORDER BY cell, tree_ordinal", cells)]

    def count_active_in_cell(self, cell: str) -> int:
        return int(self._one("SELECT COUNT(*) FROM registrations WHERE cell = ? AND state <> 'rejected'",
                             (cell,))[0])

    def update(self, job_id: str, expect_state: str | None = None, **values) -> Registration:
        """Write `values` (and updated_at). With expect_state, only if the row is still in that state."""
        unknown = set(values) - set(COLUMNS)
        if unknown:
            raise StoreError(f"unknown registration columns {sorted(unknown)}")
        values["updated_at"] = self.clock()
        sets = ", ".join(f"{k} = ?" for k in values)
        sql = f"UPDATE registrations SET {sets} WHERE id = ?"
        params = [*values.values(), job_id]
        if expect_state is not None:
            sql += " AND state = ?"
            params.append(expect_state)
        with self.transaction() as conn:
            if conn.execute(sql, params).rowcount != 1:
                current = self.get(job_id)
                raise StateConflict(f"job {job_id} is {current.state if current else 'missing'}, "
                                    f"expected {expect_state}")
        return self.get(job_id)

    def due(self, now: float, states: tuple[str, ...] = ("submitted", "verified"), limit: int = 50) -> list[Registration]:
        marks = ", ".join("?" for _ in states)
        rows = self._all(
            f"SELECT * FROM registrations WHERE state IN ({marks}) "
            "AND (next_attempt_at IS NULL OR next_attempt_at <= ?) "
            "ORDER BY COALESCE(next_attempt_at, created_at), created_at LIMIT ?", (*states, now, limit))
        return [self._reg(r) for r in rows]

    def stuck(self, now: float, after_s: float) -> list[Registration]:
        """Jobs sitting in verified longer than after_s: the alert that matters."""
        rows = self._all("SELECT * FROM registrations WHERE state = 'verified' AND verified_at <= ? "
                         "ORDER BY verified_at", (now - after_s,))
        return [self._reg(r) for r in rows]

    def list_jobs(self, state: str | None = None, limit: int = 100) -> list[Registration]:
        if state:
            rows = self._all("SELECT * FROM registrations WHERE state = ? ORDER BY created_at DESC LIMIT ?",
                             (state, limit))
        else:
            rows = self._all("SELECT * FROM registrations ORDER BY created_at DESC LIMIT ?", (limit,))
        return [self._reg(r) for r in rows]

    def counts_by_state(self) -> dict[str, int]:
        counts = dict.fromkeys(STATES, 0)
        for row in self._all("SELECT state, COUNT(*) AS n FROM registrations GROUP BY state"):
            counts[row["state"]] = int(row["n"])
        return counts

    def oldest_verified_at(self) -> float | None:
        row = self._one("SELECT MIN(verified_at) FROM registrations WHERE state = 'verified'")
        return row[0] if row and row[0] is not None else None

    def minted_since(self, since: float) -> int:
        """Mints this relay broadcast since `since`. Seeded and recovered rows are history, not spend, so they do
        not count against the daily cap."""
        return int(self._one("SELECT COUNT(*) FROM registrations WHERE state = 'minted' AND minted_at >= ? "
                             "AND decided_by = 'auto'", (since,))[0])

    def fee_wei_since(self, since: float) -> int:
        rows = self._all("SELECT fee_wei FROM registrations WHERE state = 'minted' AND minted_at >= ? "
                         "AND decided_by = 'auto' AND fee_wei IS NOT NULL", (since,))
        return sum(int(r["fee_wei"]) for r in rows)

    def oldest_mint_since(self, since: float) -> float | None:
        row = self._one("SELECT MIN(minted_at) FROM registrations WHERE state = 'minted' AND minted_at >= ? "
                        "AND decided_by = 'auto'", (since,))
        return row[0] if row and row[0] is not None else None

    # ------------------------------------------------------------------ sessions
    def create_session(self, session_id: str, ttl_s: float) -> tuple[float, float]:
        now = self.clock()
        with self.transaction() as conn:
            conn.execute("INSERT INTO sessions (id, created_at, expires_at) VALUES (?, ?, ?)",
                         (session_id, now, now + ttl_s))
        return now, now + ttl_s

    def session(self, session_id: str) -> sqlite3.Row | None:
        return self._one("SELECT * FROM sessions WHERE id = ?", (session_id,))

    # ------------------------------------------------------------------ rate limits
    def check_limits(self, rules: Iterable[tuple[str, str, int, float]], now: float) -> tuple[str, int] | None:
        """rules: (name, key, limit, window_s). The first rule already at its limit, as (name, retry_after_s),
        else None. Counts events with at > now - window."""
        with self._lock:
            for name, key, limit, window in rules:
                row = self._one("SELECT COUNT(*), MIN(at) FROM rate_events WHERE key = ? AND at > ?",
                                (key, now - window))
                if int(row[0]) >= limit:
                    return name, max(1, math.ceil(row[1] + window - now))
        return None

    def record_events(self, keys: Iterable[str], now: float) -> None:
        with self.transaction() as conn:
            for key in dict.fromkeys(keys):
                conn.execute("INSERT INTO rate_events (key, at) VALUES (?, ?)", (key, now))
            conn.execute("DELETE FROM rate_events WHERE at < ?", (now - 2 * 86_400,))

    def consume(self, rules: list[tuple[str, str, int, float]], now: float) -> tuple[str, int] | None:
        """check_limits then, if every rule passes, record one event per distinct key, atomically."""
        with self.transaction():
            refused = self.check_limits(rules, now)
            if refused is None:
                self.record_events([key for _, key, _, _ in rules], now)
            return refused


def _split_sql(script: str) -> list[str]:
    """Statements of a migration file. Triggers carry inner semicolons, so split with sqlite3.complete_statement."""
    statements, buf = [], ""
    for line in script.splitlines(keepends=True):
        if line.strip().startswith("--") and not buf.strip():
            continue
        buf += line
        if sqlite3.complete_statement(buf):
            if buf.strip():
                statements.append(buf.strip())
            buf = ""
    if buf.strip():
        raise StoreError(f"incomplete SQL statement at the end of a migration: {buf.strip()[:60]!r}")
    return statements
