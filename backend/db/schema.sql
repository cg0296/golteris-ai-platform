-- ============================================================================
-- Golteris — Database Schema (Human-Readable DDL Reference)
-- ============================================================================
--
-- This file is the standalone DDL for the Golteris database. An engineer can
-- recreate the entire schema from this file alone (acceptance criteria for #60).
--
-- This file is NOT used by the application — Alembic migrations are the
-- authoritative schema management tool. This file is kept in sync manually
-- and serves as documentation.
--
-- Tables:
--   workflows      — Workflow definitions with on/off toggle (C1 kill switch)
--   rfqs           — Core RFQ records with extracted fields and state
--   messages       — Inbound/outbound email records linked to RFQs
--   agent_runs     — Per-workflow-invocation tracking (duration, cost rollup)
--   agent_calls    — Per-Claude-API-call logging (prompt, tokens, cost, duration)
--   approvals      — HITL review queue (C2 — nothing sends without approval)
--   audit_events   — Immutable event log for RFQ detail timeline
--   carrier_bids   — Carrier quote responses for bid comparison
--   review_queue   — Ambiguous message matches needing human review
--
-- Cross-cutting constraints enforced:
--   C1 — workflows.enabled controls agent dispatch
--   C2 — approvals.status gates all outbound email
--   C4 — audit_events + agent_calls provide full traceability
--   C5 — agent_calls.cost_usd enables cost cap enforcement
--
-- See REQUIREMENTS.md §6.2 (FR-DM-1 through FR-DM-5) for formal requirements.
-- See backend/db/models.py for the SQLAlchemy ORM definitions.
-- ============================================================================

-- ---------------------------------------------------------------------------
-- Enum types
-- ---------------------------------------------------------------------------

CREATE TYPE rfq_state AS ENUM (
    'needs_clarification',
    'ready_to_quote',
    'waiting_on_carriers',
    'quotes_received',
    'waiting_on_broker',
    'quote_sent',
    'won',
    'lost',
    'cancelled'
);

CREATE TYPE message_direction AS ENUM ('inbound', 'outbound');

CREATE TYPE message_routing_status AS ENUM (
    'attached',       -- Matched to an existing RFQ
    'new_rfq',        -- Created a new RFQ from this message
    'needs_review',   -- Ambiguous — sent to review queue
    'ignored'         -- Filtered out by rules
);

CREATE TYPE approval_status AS ENUM (
    'pending_approval',
    'approved',
    'rejected',
    'skipped'
);

CREATE TYPE approval_type AS ENUM (
    'customer_reply',
    'carrier_rfq',
    'customer_quote'
);

CREATE TYPE agent_run_status AS ENUM (
    'running',
    'completed',
    'failed',
    'paused_for_hitl'
);

CREATE TYPE agent_call_status AS ENUM (
    'success',
    'failed',
    'timeout',
    'rate_limited'
);

CREATE TYPE review_queue_status AS ENUM (
    'pending',
    'resolved',
    'ignored'
);

-- ---------------------------------------------------------------------------
-- Tables
-- ---------------------------------------------------------------------------

-- Workflow definitions with on/off toggle.
-- C1: enabled=false stops the worker from dispatching jobs for this workflow.
CREATE TABLE workflows (
    id              SERIAL PRIMARY KEY,
    name            VARCHAR(255) NOT NULL UNIQUE,
    enabled         BOOLEAN NOT NULL DEFAULT FALSE,
    config          JSONB NOT NULL DEFAULT '{}',
    created_at      TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMP NOT NULL DEFAULT NOW()
);

-- Core business object — one row per quote request.
-- State history lives in audit_events; rfqs.state is the current snapshot.
CREATE TABLE rfqs (
    id                    SERIAL PRIMARY KEY,
    customer_name         VARCHAR(255),
    customer_email        VARCHAR(255),
    customer_company      VARCHAR(255),
    origin                VARCHAR(500),
    destination           VARCHAR(500),
    equipment_type        VARCHAR(255),
    truck_count           INTEGER,
    commodity             VARCHAR(255),
    weight_lbs            INTEGER,
    pickup_date           TIMESTAMP,
    delivery_date         TIMESTAMP,
    special_requirements  TEXT,
    state                 rfq_state NOT NULL DEFAULT 'needs_clarification',
    confidence_scores     JSONB,           -- Per-field confidence from extraction agent
    outcome               VARCHAR(50),     -- 'won', 'lost', 'cancelled'
    quoted_amount         NUMERIC(12, 2),
    closed_at             TIMESTAMP,
    created_at            TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at            TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE INDEX ix_rfqs_state ON rfqs (state);
CREATE INDEX ix_rfqs_created_at ON rfqs (created_at);

-- Inbound and outbound email records linked to RFQs.
-- rfq_id is nullable — message may not be matched yet.
CREATE TABLE messages (
    id                SERIAL PRIMARY KEY,
    rfq_id            INTEGER REFERENCES rfqs(id),
    direction         message_direction NOT NULL,
    sender            VARCHAR(500) NOT NULL,
    recipients        TEXT,
    subject           VARCHAR(1000),
    body              TEXT NOT NULL,
    raw_content       TEXT,
    thread_id         VARCHAR(500),
    in_reply_to       VARCHAR(500),
    message_id_header VARCHAR(500),
    routing_status    message_routing_status,
    received_at       TIMESTAMP NOT NULL DEFAULT NOW(),
    created_at        TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE INDEX ix_messages_rfq_id ON messages (rfq_id);
CREATE INDEX ix_messages_thread_id ON messages (thread_id);
CREATE INDEX ix_messages_received_at ON messages (received_at);

-- Per-workflow-invocation tracking. One row per "run" (e.g., process one email).
-- Cost and tokens roll up from child agent_calls rows.
CREATE TABLE agent_runs (
    id                  SERIAL PRIMARY KEY,
    rfq_id              INTEGER REFERENCES rfqs(id),
    workflow_id         INTEGER REFERENCES workflows(id),
    workflow_name       VARCHAR(255) NOT NULL,
    trigger_source      VARCHAR(255),
    status              agent_run_status NOT NULL DEFAULT 'running',
    started_at          TIMESTAMP NOT NULL DEFAULT NOW(),
    finished_at         TIMESTAMP,
    duration_ms         INTEGER,
    total_cost_usd      NUMERIC(10, 6) DEFAULT 0,
    total_input_tokens  INTEGER DEFAULT 0,
    total_output_tokens INTEGER DEFAULT 0
);

CREATE INDEX ix_agent_runs_rfq_id ON agent_runs (rfq_id);
CREATE INDEX ix_agent_runs_status ON agent_runs (status);
CREATE INDEX ix_agent_runs_started_at ON agent_runs (started_at);

-- Per-Claude-API-call logging. Full prompt, response, model, tokens, cost, duration.
-- C4: enables tracing any decision to its prompt.
-- C5: cost_usd enables cost cap enforcement.
CREATE TABLE agent_calls (
    id              SERIAL PRIMARY KEY,
    run_id          INTEGER NOT NULL REFERENCES agent_runs(id),
    agent_name      VARCHAR(255) NOT NULL,
    model           VARCHAR(100) NOT NULL,
    system_prompt   TEXT,
    user_prompt     TEXT NOT NULL,
    response        TEXT,
    input_tokens    INTEGER NOT NULL DEFAULT 0,
    output_tokens   INTEGER NOT NULL DEFAULT 0,
    cost_usd        NUMERIC(10, 6) NOT NULL DEFAULT 0,
    started_at      TIMESTAMP NOT NULL DEFAULT NOW(),
    finished_at     TIMESTAMP,
    duration_ms     INTEGER,
    status          agent_call_status NOT NULL DEFAULT 'success',
    error_message   TEXT
);

CREATE INDEX ix_agent_calls_run_id ON agent_calls (run_id);
CREATE INDEX ix_agent_calls_agent_name ON agent_calls (agent_name);
CREATE INDEX ix_agent_calls_started_at ON agent_calls (started_at);

-- HITL review queue. C2 enforcement point — nothing sends without approval.
CREATE TABLE approvals (
    id              SERIAL PRIMARY KEY,
    rfq_id          INTEGER NOT NULL REFERENCES rfqs(id),
    approval_type   approval_type NOT NULL,
    draft_body      TEXT NOT NULL,
    draft_subject   VARCHAR(1000),
    draft_recipient VARCHAR(500),
    reason          TEXT,
    status          approval_status NOT NULL DEFAULT 'pending_approval',
    resolved_body   TEXT,
    resolved_by     VARCHAR(255),
    created_at      TIMESTAMP NOT NULL DEFAULT NOW(),
    resolved_at     TIMESTAMP
);

CREATE INDEX ix_approvals_rfq_id ON approvals (rfq_id);
CREATE INDEX ix_approvals_status ON approvals (status);
CREATE INDEX ix_approvals_created_at ON approvals (created_at);

-- Immutable event log. Every action gets a row. Powers the RFQ timeline.
-- Application code must NEVER update or delete rows in this table.
CREATE TABLE audit_events (
    id          SERIAL PRIMARY KEY,
    rfq_id      INTEGER REFERENCES rfqs(id),
    event_type  VARCHAR(255) NOT NULL,
    actor       VARCHAR(255) NOT NULL,
    description TEXT NOT NULL,
    event_data  JSONB,              -- Named event_data (not metadata) because metadata is reserved by SQLAlchemy
    created_at  TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE INDEX ix_audit_events_rfq_id ON audit_events (rfq_id);
CREATE INDEX ix_audit_events_event_type ON audit_events (event_type);
CREATE INDEX ix_audit_events_created_at ON audit_events (created_at);

-- Carrier quote responses. Placeholder for the carrier loop (#32–#36).
CREATE TABLE carrier_bids (
    id              SERIAL PRIMARY KEY,
    rfq_id          INTEGER NOT NULL REFERENCES rfqs(id),
    carrier_name    VARCHAR(255) NOT NULL,
    carrier_email   VARCHAR(255),
    rate            NUMERIC(12, 2),
    currency        VARCHAR(10) DEFAULT 'USD',
    rate_type       VARCHAR(100),
    terms           TEXT,
    availability    VARCHAR(255),
    notes           TEXT,
    raw_response    JSONB,
    message_id      INTEGER REFERENCES messages(id),
    received_at     TIMESTAMP NOT NULL DEFAULT NOW(),
    created_at      TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE INDEX ix_carrier_bids_rfq_id ON carrier_bids (rfq_id);

-- Ambiguous message matches needing human review (FR-EI-4).
CREATE TABLE review_queue (
    id              SERIAL PRIMARY KEY,
    message_id      INTEGER NOT NULL REFERENCES messages(id),
    candidates      JSONB,
    reason          TEXT NOT NULL,
    status          review_queue_status NOT NULL DEFAULT 'pending',
    resolved_rfq_id INTEGER REFERENCES rfqs(id),
    resolved_by     VARCHAR(255),
    resolved_at     TIMESTAMP,
    created_at      TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE INDEX ix_review_queue_status ON review_queue (status);
CREATE INDEX ix_review_queue_message_id ON review_queue (message_id);
