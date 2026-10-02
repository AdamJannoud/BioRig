-- One row per registration; one registration is one tree (1 token = 1 tree).
-- UNIQUE(nullifier) is the idempotency guarantee at the storage layer; UNIQUE(cell, tree_ordinal) backs the
-- allocator's write lock, so two concurrent allocations in one cell cannot take the same ordinal.
CREATE TABLE registrations (
    id                TEXT PRIMARY KEY,           -- job id, the one exposed and polled
    submission_id     TEXT,                       -- client correlation id: indexed, deliberately not unique
    session_id        TEXT,                       -- sha256 of the session token that submitted it
    nullifier         TEXT NOT NULL UNIQUE,       -- 0x-hex bytes32, derived by the relay from (cell, salt)
    cell              TEXT NOT NULL,              -- H3 resolution-12 index, hex
    tree_ordinal      INTEGER NOT NULL CHECK (tree_ordinal >= 0),
    salt              TEXT NOT NULL,              -- biorig:v1:<cell>:<ordinal>; the seeded pilot keeps plot-1
    lat               REAL NOT NULL,
    lng               REAL NOT NULL,
    accuracy_m        REAL,                       -- NULL where no fix was reported (seed, recovery)
    location_source   TEXT NOT NULL CHECK (location_source IN ('fix', 'record', 'cell_centroid')),
    fix_captured_at   INTEGER,
    species           TEXT,
    dbh_cm            INTEGER NOT NULL,           -- what mintTree's initialDBH carries (whole centimetres)
    client_biomass_kg REAL,                       -- as submitted, kept beside the relay's own figure
    client_co2e_kg    REAL,
    biomass_kg        REAL,                       -- the relay's allometry.estimate
    co2e_kg           REAL,
    mint_biomass_kg   INTEGER NOT NULL,           -- what mintTree's initialBiomass carries (whole kilograms)
    planter_address   TEXT NOT NULL,              -- checksummed
    photo_sha256      TEXT,
    state             TEXT NOT NULL CHECK (state IN ('submitted', 'verified', 'minted', 'rejected')),
    attempts          INTEGER NOT NULL DEFAULT 0, -- broadcast attempts
    next_attempt_at   REAL,
    last_error_code   TEXT,
    last_error        TEXT,
    nonce             INTEGER,                    -- the verifier nonce this job's broadcasts use
    tx_hash           TEXT,
    token_id          INTEGER,
    tba               TEXT,
    block             INTEGER,
    gas_used          INTEGER,
    fee_wei           TEXT,                       -- decimal string; exceeds SQLite's int64 comfortably otherwise
    created_at        REAL NOT NULL,
    updated_at        REAL NOT NULL,
    verified_at       REAL,
    minted_at         REAL,
    decided_by        TEXT,                       -- auto, admin:<label>, seed:<record>, recovered:chain
    UNIQUE (cell, tree_ordinal)
);

CREATE INDEX ix_registrations_cell ON registrations (cell);
CREATE INDEX ix_registrations_submission ON registrations (session_id, submission_id);
CREATE INDEX ix_registrations_due ON registrations (state, next_attempt_at);
CREATE INDEX ix_registrations_minted_at ON registrations (minted_at);

-- A payload that could still change is not a payload that can be signed: once a row leaves submitted, the fields
-- that go into mintTree are frozen.
CREATE TRIGGER registrations_payload_frozen
BEFORE UPDATE OF nullifier, cell, tree_ordinal, salt, planter_address, dbh_cm, mint_biomass_kg ON registrations
WHEN OLD.state <> 'submitted'
BEGIN
    SELECT RAISE(ABORT, 'payload frozen: the row has left submitted');
END;

-- minted and rejected are terminal.
CREATE TRIGGER registrations_terminal
BEFORE UPDATE OF state ON registrations
WHEN OLD.state IN ('minted', 'rejected') AND NEW.state <> OLD.state
BEGIN
    SELECT RAISE(ABORT, 'terminal state: minted and rejected rows do not move');
END;

CREATE TABLE meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
