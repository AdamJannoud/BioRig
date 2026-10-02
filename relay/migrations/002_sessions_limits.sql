-- Session tokens (stored as their sha256, never in the clear) and the rate-limit ledger.
CREATE TABLE sessions (
    id         TEXT PRIMARY KEY,   -- sha256 hex of the bearer token
    created_at REAL NOT NULL,
    expires_at REAL NOT NULL
);

-- One row per counted event. key is e.g. ip:<addr>, session:<id>, planter:<addr>, session_create:<addr>.
CREATE TABLE rate_events (
    id  INTEGER PRIMARY KEY,
    key TEXT NOT NULL,
    at  REAL NOT NULL
);
CREATE INDEX ix_rate_events_key_at ON rate_events (key, at);
