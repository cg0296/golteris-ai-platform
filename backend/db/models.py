"""
backend/db/models.py — SQLAlchemy ORM models for the Golteris database.

This file defines every table in the system. It is the Python-side source of truth
for the database schema. Alembic migrations are generated from these models.

Tables and their roles:
    workflows     — Workflow definitions with on/off toggle. Controls whether the
                    background worker dispatches jobs for this workflow. Supports the
                    global kill switch (C1 — human control over agents).
    rfqs          — Core business object. One row per quote request. Holds extracted
                    fields (origin, destination, equipment, etc.), current state, and
                    outcome. This is what the broker sees in the Active RFQs list.
    messages      — Every inbound and outbound email attached to an RFQ. The broker
                    uses this to verify correct message routing (Inbox view, RFQ detail
                    Messages section).
    agent_runs    — One row per workflow invocation (e.g., "process new email for RFQ
                    #42"). Tracks start/end, status, and rolls up cost/tokens from
                    child agent_calls. Powers the Agent → Run Timeline view.
    agent_calls   — One row per LLM API call. Logs the full prompt, model, provider, token
                    counts, cost in USD, and duration. Powers the Agent → Decisions
                    audit view. Required by C4 (visible reasoning) and C5 (cost caps).
    approvals     — HITL review queue. Every outbound email draft lands here with
                    status=pending_approval. Nothing sends without a human flipping it
                    to approved. This is the C2 enforcement point.
    audit_events  — Immutable event log. Every state change, agent action, human
                    decision, and system event gets a row. Powers the RFQ detail
                    Actions & History timeline and the Recent Activity feed.
    carrier_bids  — Carrier quote responses parsed from inbound emails. One row per
                    carrier per RFQ. Used for bid comparison and ranking.
    review_queue  — Ambiguous message matches that need human review. When the
                    matching service can't confidently attach a message to an RFQ,
                    it lands here instead of silently auto-attaching (FR-EI-4).

Cross-cutting constraints enforced at the schema level:
    C1 — workflows.enabled controls whether the worker runs jobs for that workflow.
    C2 — approvals.status defaults to 'pending_approval'; outbound send checks this.
    C4 — audit_events + agent_calls provide full traceability for every action.
    C5 — agent_calls.cost_usd + agent_runs.total_cost_usd enable cost cap enforcement.

See REQUIREMENTS.md §6.2 (FR-DM-1 through FR-DM-5) for the formal requirements
that drove this schema design.
"""

import enum
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, relationship


class Base(DeclarativeBase):
    """Base class for all Golteris ORM models."""
    pass


# ---------------------------------------------------------------------------
# Enums — used as Postgres ENUM types for type safety at the database level.
# These mirror the states defined in REQUIREMENTS.md §6.2 FR-DM-3.
# ---------------------------------------------------------------------------


class RFQState(str, enum.Enum):
    """
    RFQ lifecycle states. An RFQ moves through these states as agents process
    it and the broker takes actions. See REQUIREMENTS.md §6.2 FR-DM-3.

    The state machine transitions are enforced in the application layer (#14),
    not at the database level, so that manual overrides are possible (FR-DM-4).
    """
    NEEDS_CLARIFICATION = "needs_clarification"
    READY_TO_QUOTE = "ready_to_quote"
    WAITING_ON_CARRIERS = "waiting_on_carriers"
    QUOTES_RECEIVED = "quotes_received"
    WAITING_ON_BROKER = "waiting_on_broker"
    QUOTE_SENT = "quote_sent"
    WON = "won"
    LOST = "lost"
    CANCELLED = "cancelled"


class MessageDirection(str, enum.Enum):
    """Whether a message was received from an external party or sent by the system."""
    INBOUND = "inbound"
    OUTBOUND = "outbound"


class ApprovalStatus(str, enum.Enum):
    """
    HITL approval lifecycle. Drafts start as pending_approval.
    C2 constraint: no outbound email sends unless status == APPROVED.
    """
    PENDING_APPROVAL = "pending_approval"
    APPROVED = "approved"
    REJECTED = "rejected"
    SKIPPED = "skipped"


class ApprovalType(str, enum.Enum):
    """What kind of outbound action this approval gates."""
    CUSTOMER_REPLY = "customer_reply"
    CARRIER_RFQ = "carrier_rfq"
    CUSTOMER_QUOTE = "customer_quote"


class AgentRunStatus(str, enum.Enum):
    """Status of a workflow invocation (agent_runs)."""
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    PAUSED_FOR_HITL = "paused_for_hitl"


class AgentCallStatus(str, enum.Enum):
    """Status of a single LLM API call (agent_calls). Provider-agnostic."""
    SUCCESS = "success"
    FAILED = "failed"
    TIMEOUT = "timeout"
    RATE_LIMITED = "rate_limited"


class ReviewQueueStatus(str, enum.Enum):
    """Status of an ambiguous message match in the review queue."""
    PENDING = "pending"
    RESOLVED = "resolved"
    IGNORED = "ignored"


class MessageRoutingStatus(str, enum.Enum):
    """
    How a message was routed after ingestion. Shown as badges in the Inbox view.
    See REQUIREMENTS.md §6.1 FR-EI-5.
    """
    ATTACHED = "attached"           # Matched to an existing RFQ
    NEW_RFQ_CREATED = "new_rfq"     # Created a new RFQ from this message
    NEEDS_REVIEW = "needs_review"   # Ambiguous — sent to review queue
    IGNORED = "ignored"             # Filtered out by rules (e.g., newsletter)


class JobStatus(str, enum.Enum):
    """
    Status of a job in the Postgres job queue.
    Used by the worker (#47) with SELECT ... FOR UPDATE SKIP LOCKED.
    """
    PENDING = "pending"       # Waiting to be picked up
    RUNNING = "running"       # Worker has locked and is processing
    COMPLETED = "completed"   # Finished successfully
    FAILED = "failed"         # Failed after all retries


# ---------------------------------------------------------------------------
# Tables
# ---------------------------------------------------------------------------


class User(Base):
    """
    User accounts for authentication (#54).

    Stores login credentials and role. Passwords are hashed with bcrypt.
    Roles control access: owner (full), operator (actions), viewer (read-only).
    """
    __tablename__ = "users"

    id = Column(Integer, primary_key=True)
    email = Column(String(255), nullable=False, unique=True)
    hashed_password = Column(String(255), nullable=False)
    name = Column(String(255), nullable=False)
    role = Column(String(50), nullable=False, default="operator")  # owner, operator, viewer
    active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)


class Workflow(Base):
    """
    Workflow definitions with on/off toggle.

    Each workflow represents a category of automated work (e.g., "Inbound Quotes",
    "Carrier Follow-ups"). The `enabled` flag is the C1 enforcement point — when
    False, the background worker will not dispatch new jobs for this workflow.

    The global kill switch (C1, FR-SE-5) sets ALL workflows to enabled=False.
    """
    __tablename__ = "workflows"

    id = Column(Integer, primary_key=True)
    # Human-readable name shown in Settings (e.g., "Inbound Quote Processing")
    name = Column(String(255), nullable=False, unique=True)
    # C1: when False, the worker stops dispatching jobs for this workflow.
    # The kill switch flips all rows to False in a single UPDATE.
    enabled = Column(Boolean, nullable=False, default=False)
    # JSONB config for workflow-specific settings (approval policies, scope rules,
    # mailbox filters, etc.). Keeps the schema flexible without adding columns
    # for every per-workflow option.
    config = Column(JSONB, nullable=False, default=dict)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    agent_runs = relationship("AgentRun", back_populates="workflow")


class RFQ(Base):
    """
    Core business object — one row per quote request.

    This is what the broker sees in the Active RFQs list, the RFQ detail drawer,
    and the History tab. Every other table relates back to an RFQ.

    Extracted fields (origin, destination, equipment, etc.) are populated by the
    extraction agent (#24). Fields may be null if extraction hasn't run yet or
    if the field was missing from the original email.

    State management: `state` holds the current state. The full state history
    lives in `audit_events` (FR-DM-2). Transitions are enforced in application
    code (#14), not database constraints, so manual overrides are possible (FR-DM-4).
    """
    __tablename__ = "rfqs"

    id = Column(Integer, primary_key=True)
    # Customer / shipper info — extracted from the email or set manually
    customer_name = Column(String(255))
    customer_email = Column(String(255))
    customer_company = Column(String(255))
    # Route
    origin = Column(String(500))
    destination = Column(String(500))
    # Equipment and load details
    equipment_type = Column(String(255))
    truck_count = Column(Integer)
    commodity = Column(String(255))
    weight_lbs = Column(Integer)
    # Dates
    pickup_date = Column(DateTime)
    delivery_date = Column(DateTime)
    # Special requirements — free text for anything that doesn't fit standard fields
    # (e.g., "tarping required", "driver unload", "lift gate", "storage charges")
    special_requirements = Column(Text)
    # Current RFQ state — see RFQState enum and FR-DM-3
    state = Column(
        Enum(RFQState, name="rfq_state", create_constraint=True),
        nullable=False,
        default=RFQState.NEEDS_CLARIFICATION,
    )
    # Confidence scores from the extraction agent — JSONB object with per-field
    # scores (0.0–1.0). Used by the confidence/HITL escalation policy (#23).
    # Example: {"origin": 0.95, "destination": 0.92, "commodity": 0.3}
    confidence_scores = Column(JSONB)
    # Outcome fields — populated when the RFQ closes (FR-DM-5, History tab)
    outcome = Column(String(50))  # "won", "lost", "cancelled"
    quoted_amount = Column(Numeric(12, 2))
    closed_at = Column(DateTime)
    # Timestamps
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    messages = relationship("Message", back_populates="rfq", order_by="Message.received_at")
    agent_runs = relationship("AgentRun", back_populates="rfq")
    approvals = relationship("Approval", back_populates="rfq")
    audit_events = relationship("AuditEvent", back_populates="rfq", order_by="AuditEvent.created_at")
    carrier_bids = relationship("CarrierBid", back_populates="rfq")

    # Index on state for the Active RFQs list (frequently filtered by state)
    __table_args__ = (
        Index("ix_rfqs_state", "state"),
        Index("ix_rfqs_created_at", "created_at"),
    )


class Message(Base):
    """
    Every inbound and outbound email attached to an RFQ.

    Inbound messages come from the mailbox poller (#12). Outbound messages are
    created by agents (draft replies, carrier RFQs, customer quotes) and only
    sent after human approval (C2 — see Approval table).

    The broker sees these in:
    - Inbox view (FR-EI-5) — with routing_status badge
    - RFQ detail drawer → Messages section — full thread
    - Recent Activity feed — business-level events derived from messages

    rfq_id is nullable because a message may arrive before it's matched to an RFQ
    (it sits in the review queue until matched or a new RFQ is created from it).
    """
    __tablename__ = "messages"

    id = Column(Integer, primary_key=True)
    # Nullable — message may not be matched to an RFQ yet (see review_queue)
    rfq_id = Column(Integer, ForeignKey("rfqs.id"), nullable=True)
    # Inbound or outbound
    direction = Column(
        Enum(MessageDirection, name="message_direction", create_constraint=True),
        nullable=False,
    )
    # Email metadata
    sender = Column(String(500), nullable=False)
    recipients = Column(Text)  # Comma-separated or JSON list of recipients
    subject = Column(String(1000))
    body = Column(Text, nullable=False)
    # Raw email content preserved for debugging and re-processing
    raw_content = Column(Text)
    # Thread metadata — used by the matching service (#13) for deterministic
    # reply matching before falling back to context scoring
    thread_id = Column(String(500))
    in_reply_to = Column(String(500))
    message_id_header = Column(String(500))  # The email Message-ID header
    # How this message was routed after ingestion — shown as a badge in Inbox view
    routing_status = Column(
        Enum(MessageRoutingStatus, name="message_routing_status", create_constraint=True),
    )
    # Timestamps
    received_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    # Relationships
    rfq = relationship("RFQ", back_populates="messages")

    __table_args__ = (
        Index("ix_messages_rfq_id", "rfq_id"),
        Index("ix_messages_thread_id", "thread_id"),
        Index("ix_messages_received_at", "received_at"),
    )


class AgentRun(Base):
    """
    One row per workflow invocation — e.g., "process new email for RFQ #42."

    Tracks the full lifecycle of a workflow run from start to finish, including
    HITL pauses. Rolls up cost and token counts from child agent_calls.

    Powers the Agent → Run Timeline view (#38) and the Agent → Tasks Queue (#39).
    See REQUIREMENTS.md NFR-OB-2.

    The run may span multiple LLM API calls (agent_calls) — for example,
    extraction + validation + draft generation in one orchestrated run.
    """
    __tablename__ = "agent_runs"

    id = Column(Integer, primary_key=True)
    # Which RFQ this run is processing (nullable for system-level runs like polling)
    rfq_id = Column(Integer, ForeignKey("rfqs.id"), nullable=True)
    # Which workflow definition triggered this run
    workflow_id = Column(Integer, ForeignKey("workflows.id"), nullable=True)
    # Human-readable workflow name (denormalized for convenience in queries/UI)
    workflow_name = Column(String(255), nullable=False)
    # What triggered this run (e.g., "new_email", "timer", "manual", "state_change")
    trigger_source = Column(String(255))
    # Run status — see AgentRunStatus enum
    status = Column(
        Enum(AgentRunStatus, name="agent_run_status", create_constraint=True),
        nullable=False,
        default=AgentRunStatus.RUNNING,
    )
    # Timing — duration_ms reflects total wall time including HITL pauses
    started_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    finished_at = Column(DateTime)
    duration_ms = Column(Integer)
    # Cost rollup from child agent_calls — enables the "cost per RFQ" metric
    total_cost_usd = Column(Numeric(10, 6), default=Decimal("0"))
    total_input_tokens = Column(Integer, default=0)
    total_output_tokens = Column(Integer, default=0)

    # Relationships
    rfq = relationship("RFQ", back_populates="agent_runs")
    workflow = relationship("Workflow", back_populates="agent_runs")
    agent_calls = relationship("AgentCall", back_populates="agent_run")

    __table_args__ = (
        Index("ix_agent_runs_rfq_id", "rfq_id"),
        Index("ix_agent_runs_status", "status"),
        Index("ix_agent_runs_started_at", "started_at"),
    )


class AgentCall(Base):
    """
    One row per LLM API call (any provider — Anthropic, OpenAI, etc.).

    This is the most granular audit record in the system. Every time the LLM
    provider abstraction layer is called, it writes a row here with the full
    prompt, response, provider, model, token counts, cost, and duration.

    Required by:
    - C4 (visible reasoning) — the broker can trace any decision to its prompt
    - C5 (cost caps) — cost_usd enables per-call and per-day cost tracking
    - NFR-OB-1 — cost must match the provider's bill within 1%

    Powers the Agent → Decisions audit view (#37).
    """
    __tablename__ = "agent_calls"

    id = Column(Integer, primary_key=True)
    # Links to the parent workflow run
    run_id = Column(Integer, ForeignKey("agent_runs.id"), nullable=False)
    # Which agent made this call (e.g., "extraction", "validation", "draft_reply")
    agent_name = Column(String(255), nullable=False)
    # LLM provider used (e.g., "anthropic", "openai") — enables multi-provider cost tracking
    provider = Column(String(100), nullable=False, default="anthropic")
    # The model used (e.g., "claude-sonnet-4-6", "gpt-4o", "gpt-4.1")
    model = Column(String(100), nullable=False)
    # Full prompts — stored for auditability. The "View system reasoning" disclosure
    # in the RFQ detail drawer reads these fields.
    system_prompt = Column(Text)
    user_prompt = Column(Text, nullable=False)
    # The full response from the LLM — stored as text (may be JSON for tool-use)
    response = Column(Text)
    # Token counts — used for cost calculation and the Decisions audit view
    input_tokens = Column(Integer, nullable=False, default=0)
    output_tokens = Column(Integer, nullable=False, default=0)
    # Cost in USD — calculated from token counts using the provider's pricing.
    # Must match the actual provider bill within 1% (NFR-OB-1).
    cost_usd = Column(Numeric(10, 6), nullable=False, default=Decimal("0"))
    # Timing
    started_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    finished_at = Column(DateTime)
    duration_ms = Column(Integer)
    # Status — tracks failures (timeouts, rate limits) for the DLQ and alerts
    status = Column(
        Enum(AgentCallStatus, name="agent_call_status", create_constraint=True),
        nullable=False,
        default=AgentCallStatus.SUCCESS,
    )
    # Error details if the call failed
    error_message = Column(Text)

    # Relationships
    agent_run = relationship("AgentRun", back_populates="agent_calls")

    __table_args__ = (
        Index("ix_agent_calls_run_id", "run_id"),
        Index("ix_agent_calls_agent_name", "agent_name"),
        Index("ix_agent_calls_started_at", "started_at"),
    )


class Approval(Base):
    """
    HITL review queue — the C2 enforcement point.

    Every outbound email draft (customer reply, carrier RFQ, customer quote) creates
    a row here with status=pending_approval. The draft body is stored in this table.
    The broker reviews it in the Needs Review panel / approval modal (#26).

    C2 CONSTRAINT: The outbound email send job MUST check approvals.status == APPROVED
    before sending. This is the single gate between the system and any external
    communication. See REQUIREMENTS.md §5 C2.

    Actions available to the broker:
    - Approve (Send As-Is) → status = approved, original draft_body sent
    - Edit → status = approved, edited_body sent (stored in resolved_body)
    - Reject → status = rejected, nothing sent
    - Skip → status = skipped, stays in queue for later
    """
    __tablename__ = "approvals"

    id = Column(Integer, primary_key=True)
    rfq_id = Column(Integer, ForeignKey("rfqs.id"), nullable=False)
    # What this approval gates — determines which outbound pipeline to use
    approval_type = Column(
        Enum(ApprovalType, name="approval_type", create_constraint=True),
        nullable=False,
    )
    # The draft email body generated by the agent — shown in the approval modal
    draft_body = Column(Text, nullable=False)
    # The subject line for the outbound email
    draft_subject = Column(String(1000))
    # Who the outbound email will be sent to
    draft_recipient = Column(String(500))
    # Why this was flagged for review — shown in the approval modal as the reason badge
    # (e.g., "Missing commodity info", "Low confidence on destination", "First email to customer")
    reason = Column(Text)
    # Current status — defaults to pending_approval. See ApprovalStatus enum.
    status = Column(
        Enum(ApprovalStatus, name="approval_status", create_constraint=True),
        nullable=False,
        default=ApprovalStatus.PENDING_APPROVAL,
    )
    # If the broker edited the draft before approving, the edited version is stored here.
    # If null and status=approved, the original draft_body was sent as-is.
    resolved_body = Column(Text)
    # Who approved/rejected (for audit trail)
    resolved_by = Column(String(255))
    # Timestamps
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    resolved_at = Column(DateTime)

    # Relationships
    rfq = relationship("RFQ", back_populates="approvals")

    __table_args__ = (
        Index("ix_approvals_rfq_id", "rfq_id"),
        Index("ix_approvals_status", "status"),
        Index("ix_approvals_created_at", "created_at"),
    )


class AuditEvent(Base):
    """
    Immutable event log — every action that happens in the system gets a row here.

    This powers:
    - RFQ detail drawer → Actions & History timeline (#27)
    - Recent Activity feed on the Home screen (#17)
    - The "plain English" translation layer — event_type maps to operator language
      (C3: "Draft reply prepared" not "extraction_completed")

    Events are IMMUTABLE (FR-DM-5 for closed RFQs). The application layer must
    never UPDATE or DELETE rows in this table.

    The description field is human-readable — it's what the broker sees in the
    timeline. The event_type field is machine-readable — it's what the frontend
    uses to pick icons and filter events.
    """
    __tablename__ = "audit_events"

    id = Column(Integer, primary_key=True)
    # Which RFQ this event belongs to (nullable for system-level events)
    rfq_id = Column(Integer, ForeignKey("rfqs.id"), nullable=True)
    # Machine-readable event type (e.g., "rfq_created", "state_changed",
    # "approval_approved", "email_sent", "extraction_completed")
    event_type = Column(String(255), nullable=False)
    # Who or what caused this event: "system", "extraction_agent", "validation_agent",
    # or a user identifier like "jillian@beltmann.com"
    actor = Column(String(255), nullable=False)
    # Human-readable description shown in the UI timeline.
    # Uses operator language per C3 (e.g., "Draft reply prepared for Tom @ Beltmann")
    description = Column(Text, nullable=False)
    # Optional structured data for events that carry extra context
    # (e.g., {"old_state": "needs_clarification", "new_state": "ready_to_quote"})
    # Named 'event_data' instead of 'metadata' because 'metadata' is reserved
    # by SQLAlchemy's Declarative API.
    event_data = Column(JSONB)
    # Timestamp — when this event occurred
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    # Relationships
    rfq = relationship("RFQ", back_populates="audit_events")

    __table_args__ = (
        Index("ix_audit_events_rfq_id", "rfq_id"),
        Index("ix_audit_events_event_type", "event_type"),
        Index("ix_audit_events_created_at", "created_at"),
    )


class CarrierBid(Base):
    """
    Carrier quote responses — one row per carrier per RFQ.

    Populated by the carrier quote response parser (#33) when a carrier replies
    to an RFQ distribution email. Used by the bid comparison and ranking engine (#34).

    This is a placeholder table for the MVP. Fields will expand as the carrier
    loop (#32–#36) is implemented. The JSONB raw_response column preserves the
    original parsed data for debugging.
    """
    __tablename__ = "carrier_bids"

    id = Column(Integer, primary_key=True)
    rfq_id = Column(Integer, ForeignKey("rfqs.id"), nullable=False)
    # Carrier info
    carrier_name = Column(String(255), nullable=False)
    carrier_email = Column(String(255))
    # The bid amount — normalized to USD for comparison
    rate = Column(Numeric(12, 2))
    currency = Column(String(10), default="USD")
    # Rate structure (e.g., "all_in", "linehaul_plus_fsc", "per_mile")
    rate_type = Column(String(100))
    # Terms, availability, and notes from the carrier
    terms = Column(Text)
    availability = Column(String(255))
    notes = Column(Text)
    # Raw parsed response — JSONB for flexible storage of whatever the parser extracted
    raw_response = Column(JSONB)
    # Link to the inbound message that contained this bid
    message_id = Column(Integer, ForeignKey("messages.id"), nullable=True)
    # Timestamps
    received_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    # Relationships
    rfq = relationship("RFQ", back_populates="carrier_bids")

    __table_args__ = (
        Index("ix_carrier_bids_rfq_id", "rfq_id"),
    )


class ReviewQueue(Base):
    """
    Ambiguous message matches that need human review.

    When the matching service (#13) can't confidently attach an inbound message
    to an RFQ, it creates a row here instead of silently auto-attaching (FR-EI-4).
    The broker sees these as "Needs review" items in the Inbox view.

    Resolution: the broker either assigns the message to an existing RFQ, creates
    a new RFQ from it, or marks it as ignored.
    """
    __tablename__ = "review_queue"

    id = Column(Integer, primary_key=True)
    # The unmatched message
    message_id = Column(Integer, ForeignKey("messages.id"), nullable=False)
    # Candidate RFQs that the matching service considered, with their scores.
    # JSONB array: [{"rfq_id": 42, "score": 0.72, "reason": "same sender, different route"}, ...]
    candidates = Column(JSONB)
    # Why the match was ambiguous — shown to the broker in the review card
    reason = Column(Text, nullable=False)
    # Resolution status
    status = Column(
        Enum(ReviewQueueStatus, name="review_queue_status", create_constraint=True),
        nullable=False,
        default=ReviewQueueStatus.PENDING,
    )
    # If resolved by assigning to an RFQ, which one
    resolved_rfq_id = Column(Integer, ForeignKey("rfqs.id"), nullable=True)
    resolved_by = Column(String(255))
    resolved_at = Column(DateTime)
    # Timestamps
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    __table_args__ = (
        Index("ix_review_queue_status", "status"),
        Index("ix_review_queue_message_id", "message_id"),
    )


class CarrierSendStatus(str, enum.Enum):
    """Status of an individual carrier RFQ send in a distribution batch."""
    PENDING_APPROVAL = "pending_approval"  # Awaiting broker approval
    QUEUED = "queued"                      # Approved, send job enqueued
    SENT = "sent"                          # Email sent successfully
    FAILED = "failed"                      # Send failed (bounce, auth error)


class Carrier(Base):
    """
    Carrier directory — trucking companies that Beltmann sends RFQs to.

    Each carrier has contact info, equipment capabilities, and lane coverage.
    The distribution service (#32) matches carriers to RFQs based on equipment
    type and origin/destination lanes. Preferred carriers are shown first.
    """
    __tablename__ = "carriers"

    id = Column(Integer, primary_key=True)
    name = Column(String(255), nullable=False)
    email = Column(String(255), nullable=False)
    # Contact info
    contact_name = Column(String(255))
    phone = Column(String(50))
    # Capabilities — JSONB arrays for flexible matching
    # e.g., ["Dry Van", "Flatbed"] or ["Reefer"]
    equipment_types = Column(JSONB, default=list)
    # Lane coverage — JSONB array of {origin, destination} objects
    # e.g., [{"origin": "Chicago", "destination": "Dallas"}]
    lanes = Column(JSONB, default=list)
    # Preferred carrier flag — shown first in selection UI
    preferred = Column(Boolean, nullable=False, default=False)
    # Active flag — inactive carriers are hidden from selection
    active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    __table_args__ = (
        Index("ix_carriers_active", "active"),
    )


class CarrierRfqSend(Base):
    """
    Tracks individual carrier sends within a distribution batch (#32).

    One row per carrier per RFQ distribution. Links to the approval
    (C2 gate) and tracks delivery status per carrier.
    """
    __tablename__ = "carrier_rfq_sends"

    id = Column(Integer, primary_key=True)
    rfq_id = Column(Integer, ForeignKey("rfqs.id"), nullable=False)
    carrier_id = Column(Integer, ForeignKey("carriers.id"), nullable=False)
    # The approval that gates this send (C2)
    approval_id = Column(Integer, ForeignKey("approvals.id"), nullable=True)
    # Per-carrier send status
    status = Column(
        Enum(CarrierSendStatus, name="carrier_send_status", create_constraint=True),
        nullable=False,
        default=CarrierSendStatus.PENDING_APPROVAL,
    )
    # Personalized email content for this carrier
    email_subject = Column(String(1000))
    email_body = Column(Text)
    # Delivery tracking
    sent_at = Column(DateTime)
    error_message = Column(Text)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    __table_args__ = (
        Index("ix_carrier_rfq_sends_rfq_id", "rfq_id"),
        Index("ix_carrier_rfq_sends_carrier_id", "carrier_id"),
    )


class Job(Base):
    """
    Postgres-backed job queue for the background worker (#47).

    The worker picks up pending jobs using SELECT ... FOR UPDATE SKIP LOCKED,
    which provides safe, concurrent job processing without an external queue
    (Redis, RabbitMQ, Celery). See REQUIREMENTS.md §2.1.

    Job types map to agent functions:
    - "extraction" → backend.agents.extraction.extract_rfq
    - "validation" → backend.agents.validation.draft_followup
    - "quote_sheet" → backend.agents.quote_sheet.generate_quote_sheet
    - "matching" → backend.services.message_matching.match_message_to_rfq

    The payload JSONB stores job-specific parameters (e.g., message_id, rfq_id).

    Cross-cutting constraints:
        C1 — Worker checks workflows.enabled before processing each job
        FR-WK-1 — Postgres job queue with FOR UPDATE SKIP LOCKED
        FR-WK-2 — All state in Postgres, nothing in memory (crash-safe)
    """
    __tablename__ = "jobs"

    id = Column(Integer, primary_key=True)
    # What kind of job (maps to an agent/service function)
    job_type = Column(String(100), nullable=False)
    # Job-specific parameters — e.g., {"message_id": 42} or {"rfq_id": 7}
    payload = Column(JSONB, nullable=False, default=dict)
    # Current status — pending jobs are picked up by the worker
    status = Column(
        Enum(JobStatus, name="job_status", create_constraint=True),
        nullable=False,
        default=JobStatus.PENDING,
    )
    # Optional link to the RFQ this job relates to
    rfq_id = Column(Integer, ForeignKey("rfqs.id"), nullable=True)
    # Optional link to the workflow that created this job (for C1 checking)
    workflow_id = Column(Integer, ForeignKey("workflows.id"), nullable=True)
    # Retry tracking — jobs can be retried on transient failures
    retry_count = Column(Integer, nullable=False, default=0)
    max_retries = Column(Integer, nullable=False, default=3)
    # Error details if the job failed
    error_message = Column(Text)
    # Timestamps
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    started_at = Column(DateTime)
    finished_at = Column(DateTime)

    __table_args__ = (
        Index("ix_jobs_status_created", "status", "created_at"),
        Index("ix_jobs_rfq_id", "rfq_id"),
    )


class AgentMemory(Base):
    """
    Learned patterns and preferences from broker-approved drafts (#49).

    When the broker edits a draft before approving, the system compares the
    original and edited versions to extract style, tone, and vocabulary
    preferences. These memories are applied to future draft generation to
    make agents gradually sound more like the broker.

    The broker can review, approve, reject, or delete learned memories
    from the Agent → Memory view (#40).

    Categories:
        style — Language patterns (e.g., "Always sign off with 'Best regards'")
        preference — Broker preferences (e.g., "Prefer flat rates over per-mile")
        customer — Customer-specific knowledge (e.g., "Tom at Reynolds always needs tarping")
        lane — Route patterns (e.g., "Chicago to Dallas usually runs $2,800-3,200")
        pricing — Markup rules (e.g., "15% markup for new customers, 10% for repeat")
    """
    __tablename__ = "agent_memories"

    id = Column(Integer, primary_key=True)
    # Category of the learned pattern
    category = Column(String(50), nullable=False)  # style, preference, customer, lane, pricing
    # What was learned — plain English description
    content = Column(Text, nullable=False)
    # Where it was learned from — e.g., "Approval #42 — edited draft for Tom Reynolds"
    source = Column(Text)
    # Link to the approval that triggered this learning (if applicable)
    approval_id = Column(Integer, ForeignKey("approvals.id"), nullable=True)
    # Whether the broker has reviewed and approved this memory
    # pending = just learned, approved = broker confirmed, rejected = broker dismissed
    status = Column(String(20), nullable=False, default="pending")
    # Confidence score (0.0–1.0) — how strongly the system believes this pattern
    confidence = Column(Numeric(3, 2), default=Decimal("0.80"))
    # How many times this memory has been applied to drafts
    times_applied = Column(Integer, nullable=False, default=0)
    # Timestamps
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)
