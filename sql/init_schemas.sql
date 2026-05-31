-- kairos-evolve RDS bootstrap (idempotent).
--
-- Run ONCE against a fresh dedicated RDS instance to provision the schemas,
-- tables, role, and grants that the evolve-api service owns. Safe to re-run
-- (every statement is IF NOT EXISTS / exception-guarded).
--
-- The evolve service owns:
--   kairos_evolve: routing_policies, routing_policy_versions, routing_events
--   kairos_audit:  audit_log, envelope_batches, idempotency_keys
-- Role:
--   kairos_evolve_api — owns kairos_evolve.*, INSERT on kairos_audit.audit_log
-- The kairos schema is left empty here (no kairos.* tables needed in Phase 2A;
-- routing_events do not FK into kairos.runs in this phase).
--
-- This mirrors tests/sql/ddl_phase2a.sql (the Phase 2A test fixture); keep the
-- two in sync until Plan 2B replaces both with an Alembic migration.
--
-- Apply with e.g.:
--   psql "$KAIROS_EVOLVE_DATABASE_URL" -v ON_ERROR_STOP=1 -f sql/init_schemas.sql

CREATE SCHEMA IF NOT EXISTS kairos;
CREATE SCHEMA IF NOT EXISTS kairos_evolve;
CREATE SCHEMA IF NOT EXISTS kairos_audit;

-- ----------------------------------------------------------------------------
-- kairos_audit (created first — referenced by FK from kairos_evolve)
-- ----------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS kairos_audit.audit_log (
    id              UUID PRIMARY KEY,
    prev_id         UUID REFERENCES kairos_audit.audit_log(id),
    actor_service   TEXT NOT NULL,
    actor_key_id    TEXT NOT NULL,
    request_id      TEXT,
    idempotency_key TEXT,
    envelope_hash   TEXT,
    body_sha256     TEXT NOT NULL,
    target_schema   TEXT NOT NULL,
    target_table    TEXT NOT NULL,
    target_id       TEXT NOT NULL,
    action          TEXT NOT NULL,
    previous_state  TEXT,
    next_state      TEXT,
    signature       BYTEA,
    batch_id        UUID,
    payload         JSONB NOT NULL,
    ts              TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_audit_log_target ON kairos_audit.audit_log (target_schema, target_table, target_id);
CREATE INDEX IF NOT EXISTS idx_audit_log_action ON kairos_audit.audit_log (action);
CREATE INDEX IF NOT EXISTS idx_audit_log_ts     ON kairos_audit.audit_log (ts);

CREATE TABLE IF NOT EXISTS kairos_audit.envelope_batches (
    batch_id        UUID PRIMARY KEY,
    event_kinds     TEXT[] NOT NULL,
    merkle_root     TEXT NOT NULL,
    member_count    INT NOT NULL,
    signature       BYTEA NOT NULL,
    signed_by       TEXT NOT NULL,
    ts              TIMESTAMPTZ NOT NULL DEFAULT now()
);

DO $$
BEGIN
  ALTER TABLE kairos_audit.audit_log
    ADD CONSTRAINT fk_audit_log_batch FOREIGN KEY (batch_id)
    REFERENCES kairos_audit.envelope_batches(batch_id);
EXCEPTION WHEN duplicate_object THEN NULL;
END
$$;

CREATE TABLE IF NOT EXISTS kairos_audit.idempotency_keys (
    key                 TEXT PRIMARY KEY,
    request_hash        TEXT NOT NULL,
    response_status     INT NOT NULL,
    response_body_jsonb JSONB,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    expires_at          TIMESTAMPTZ NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_idempotency_keys_expires ON kairos_audit.idempotency_keys (expires_at);

-- ----------------------------------------------------------------------------
-- kairos_evolve
-- ----------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS kairos_evolve.routing_policies (
    scope_key       TEXT PRIMARY KEY,
    active_version  BIGINT,
    last_activated_at TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS kairos_evolve.routing_policy_versions (
    id                  UUID PRIMARY KEY,
    scope_key           TEXT NOT NULL,
    policy_version      BIGINT NOT NULL,
    etag                TEXT NOT NULL,
    description_weights JSONB NOT NULL,
    trigger_hints       JSONB NOT NULL DEFAULT '{}',
    activated_at        TIMESTAMPTZ,
    superseded_at       TIMESTAMPTZ,
    signed_by           TEXT NOT NULL,
    signature           BYTEA NOT NULL,
    audit_id            UUID NOT NULL REFERENCES kairos_audit.audit_log(id),
    UNIQUE (scope_key, policy_version)
);

CREATE INDEX IF NOT EXISTS idx_active_policies ON kairos_evolve.routing_policy_versions (scope_key)
    WHERE superseded_at IS NULL AND activated_at IS NOT NULL;

CREATE TABLE IF NOT EXISTS kairos_evolve.routing_events (
    event_id        TEXT PRIMARY KEY,
    scope_key       TEXT NOT NULL,
    query_hash      TEXT NOT NULL,
    routed_skill_id TEXT NOT NULL,
    accepted_skill_id TEXT,
    at              TIMESTAMPTZ NOT NULL,
    batch_id        UUID NOT NULL REFERENCES kairos_audit.envelope_batches(batch_id),
    received_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_routing_events_scope ON kairos_evolve.routing_events (scope_key, received_at);
CREATE INDEX IF NOT EXISTS idx_routing_events_batch ON kairos_evolve.routing_events (batch_id);

-- ----------------------------------------------------------------------------
-- Role
-- ----------------------------------------------------------------------------

DO $$
BEGIN
  CREATE ROLE kairos_evolve_api NOLOGIN;
EXCEPTION WHEN duplicate_object THEN NULL;
END
$$;

GRANT USAGE ON SCHEMA kairos_evolve TO kairos_evolve_api;
GRANT SELECT, INSERT, UPDATE ON ALL TABLES IN SCHEMA kairos_evolve TO kairos_evolve_api;
ALTER DEFAULT PRIVILEGES IN SCHEMA kairos_evolve
  GRANT SELECT, INSERT, UPDATE ON TABLES TO kairos_evolve_api;

GRANT USAGE ON SCHEMA kairos_audit TO kairos_evolve_api;
GRANT INSERT ON kairos_audit.audit_log TO kairos_evolve_api;
GRANT INSERT ON kairos_audit.envelope_batches TO kairos_evolve_api;
GRANT SELECT, INSERT, DELETE ON kairos_audit.idempotency_keys TO kairos_evolve_api;
-- INSERT-only on audit_log + envelope_batches (no UPDATE / DELETE)
REVOKE UPDATE, DELETE ON kairos_audit.audit_log FROM kairos_evolve_api;
REVOKE UPDATE, DELETE ON kairos_audit.envelope_batches FROM kairos_evolve_api;
