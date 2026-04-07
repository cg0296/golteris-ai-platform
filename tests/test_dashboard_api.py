"""
tests/test_dashboard_api.py — Tests for the broker home dashboard (#17).

Verifies the dashboard service functions and API endpoints:
    1. KPI summary returns correct counts across tables
    2. Active RFQs excludes terminal states and respects pagination
    3. Pending approvals returns only pending items with RFQ context
    4. Recent activity returns events in reverse chronological order
    5. Approve action flips status and creates audit event

Uses an in-memory SQLite database. Same pattern as test_agent_runs.py.
"""

from datetime import datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import JSON, create_engine
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import sessionmaker

from backend.db.models import (
    AgentRun,
    AgentRunStatus,
    Approval,
    ApprovalStatus,
    ApprovalType,
    AuditEvent,
    Base,
    CarrierBid,
    RFQ,
    RFQState,
    ReviewQueue,
    ReviewQueueStatus,
)
from backend.services.dashboard import (
    approve_approval,
    get_approval_detail,
    get_kpi_summary,
    list_active_rfqs,
    list_pending_approvals,
    list_recent_activity,
    reject_approval,
    skip_approval,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_sqlite_compatible():
    """Swap JSONB -> JSON so SQLite can create the tables."""
    for table in Base.metadata.tables.values():
        for column in table.columns:
            if isinstance(column.type, JSONB):
                column.type = JSON()


@pytest.fixture
def db():
    """Fresh in-memory SQLite database for each test."""
    _make_sqlite_compatible()
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()


def _make_rfq(db, state=RFQState.READY_TO_QUOTE, **kwargs) -> RFQ:
    """Helper — create an RFQ with sensible defaults."""
    rfq = RFQ(
        customer_name=kwargs.get("customer_name", "Test Shipper"),
        customer_company=kwargs.get("customer_company", "Test Co"),
        origin=kwargs.get("origin", "Chicago, IL"),
        destination=kwargs.get("destination", "Dallas, TX"),
        state=state,
        created_at=kwargs.get("created_at", datetime.utcnow()),
        updated_at=kwargs.get("updated_at", datetime.utcnow()),
    )
    db.add(rfq)
    db.commit()
    db.refresh(rfq)
    return rfq


# ---------------------------------------------------------------------------
# KPI Summary tests
# ---------------------------------------------------------------------------


class TestGetKpiSummary:
    """Tests for get_kpi_summary — the four-card KPI strip."""

    def test_empty_database(self, db):
        """KPIs should all be zero with no data."""
        result = get_kpi_summary(db)
        assert result["needs_review"] == 0
        assert result["active_rfqs"] == 0
        assert result["quotes_received_today"] == 0
        assert result["time_saved_minutes"] == 0

    def test_needs_review_counts_approvals_and_review_queue(self, db):
        """needs_review = pending approvals + pending review queue items."""
        rfq = _make_rfq(db)

        # Two pending approvals
        db.add(Approval(rfq_id=rfq.id, approval_type=ApprovalType.CUSTOMER_REPLY,
                        draft_body="Draft 1", status=ApprovalStatus.PENDING_APPROVAL))
        db.add(Approval(rfq_id=rfq.id, approval_type=ApprovalType.CARRIER_RFQ,
                        draft_body="Draft 2", status=ApprovalStatus.PENDING_APPROVAL))
        # One already-approved (should NOT count)
        db.add(Approval(rfq_id=rfq.id, approval_type=ApprovalType.CUSTOMER_QUOTE,
                        draft_body="Draft 3", status=ApprovalStatus.APPROVED))
        # One pending review queue item
        db.add(ReviewQueue(message_id=1, reason="Ambiguous", status=ReviewQueueStatus.PENDING))
        # One resolved review queue item (should NOT count)
        db.add(ReviewQueue(message_id=2, reason="Resolved", status=ReviewQueueStatus.RESOLVED))
        db.commit()

        result = get_kpi_summary(db)
        assert result["needs_review"] == 3  # 2 approvals + 1 review

    def test_active_rfqs_excludes_terminal(self, db):
        """active_rfqs counts only non-terminal RFQs."""
        _make_rfq(db, state=RFQState.READY_TO_QUOTE)
        _make_rfq(db, state=RFQState.WAITING_ON_CARRIERS)
        _make_rfq(db, state=RFQState.WON)       # terminal
        _make_rfq(db, state=RFQState.LOST)       # terminal
        _make_rfq(db, state=RFQState.CANCELLED)  # terminal

        result = get_kpi_summary(db)
        assert result["active_rfqs"] == 2

    def test_quotes_received_today(self, db):
        """quotes_received_today counts bids received since midnight."""
        rfq = _make_rfq(db)
        # Today's bid
        db.add(CarrierBid(rfq_id=rfq.id, carrier_name="Carrier A",
                          received_at=datetime.utcnow()))
        # Yesterday's bid (should NOT count)
        db.add(CarrierBid(rfq_id=rfq.id, carrier_name="Carrier B",
                          received_at=datetime.utcnow() - timedelta(days=1)))
        db.commit()

        result = get_kpi_summary(db)
        assert result["quotes_received_today"] == 1

    def test_time_saved_minutes(self, db):
        """time_saved sums completed agent run durations from today."""
        # Completed today — 120 seconds
        db.add(AgentRun(
            workflow_name="extraction", status=AgentRunStatus.COMPLETED,
            duration_ms=120000, finished_at=datetime.utcnow(),
        ))
        # Completed today — 60 seconds
        db.add(AgentRun(
            workflow_name="validation", status=AgentRunStatus.COMPLETED,
            duration_ms=60000, finished_at=datetime.utcnow(),
        ))
        # Still running (should NOT count)
        db.add(AgentRun(
            workflow_name="draft", status=AgentRunStatus.RUNNING,
            duration_ms=None,
        ))
        db.commit()

        result = get_kpi_summary(db)
        assert result["time_saved_minutes"] == 3.0  # (120000 + 60000) / 60000


# ---------------------------------------------------------------------------
# Active RFQs tests
# ---------------------------------------------------------------------------


class TestListActiveRfqs:
    """Tests for list_active_rfqs — the dashboard's RFQ preview table."""

    def test_excludes_terminal_states(self, db):
        """Only non-terminal RFQs are returned."""
        _make_rfq(db, state=RFQState.READY_TO_QUOTE)
        _make_rfq(db, state=RFQState.WON)
        _make_rfq(db, state=RFQState.CANCELLED)

        rfqs, total = list_active_rfqs(db)
        assert total == 1
        assert len(rfqs) == 1
        assert rfqs[0].state == RFQState.READY_TO_QUOTE

    def test_respects_limit(self, db):
        """Limit parameter controls page size."""
        for _ in range(10):
            _make_rfq(db, state=RFQState.NEEDS_CLARIFICATION)

        rfqs, total = list_active_rfqs(db, limit=3)
        assert len(rfqs) == 3
        assert total == 10

    def test_ordered_by_updated_at_desc(self, db):
        """Most recently updated RFQs come first."""
        old = _make_rfq(db, updated_at=datetime.utcnow() - timedelta(hours=2))
        new = _make_rfq(db, updated_at=datetime.utcnow())

        rfqs, _ = list_active_rfqs(db)
        assert rfqs[0].id == new.id
        assert rfqs[1].id == old.id


# ---------------------------------------------------------------------------
# Pending Approvals tests
# ---------------------------------------------------------------------------


class TestListPendingApprovals:
    """Tests for list_pending_approvals — the Urgent Actions panel."""

    def test_returns_only_pending(self, db):
        """Only pending_approval items are returned."""
        rfq = _make_rfq(db)
        db.add(Approval(rfq_id=rfq.id, approval_type=ApprovalType.CUSTOMER_REPLY,
                        draft_body="Pending", status=ApprovalStatus.PENDING_APPROVAL))
        db.add(Approval(rfq_id=rfq.id, approval_type=ApprovalType.CARRIER_RFQ,
                        draft_body="Approved", status=ApprovalStatus.APPROVED))
        db.commit()

        approvals, total = list_pending_approvals(db)
        assert total == 1
        assert approvals[0].status == ApprovalStatus.PENDING_APPROVAL

    def test_includes_rfq_context(self, db):
        """Approvals eager-load their related RFQ for display context."""
        rfq = _make_rfq(db, customer_name="Acme Freight")
        db.add(Approval(rfq_id=rfq.id, approval_type=ApprovalType.CUSTOMER_REPLY,
                        draft_body="Draft", status=ApprovalStatus.PENDING_APPROVAL))
        db.commit()

        approvals, _ = list_pending_approvals(db)
        assert approvals[0].rfq.customer_name == "Acme Freight"


# ---------------------------------------------------------------------------
# Recent Activity tests
# ---------------------------------------------------------------------------


class TestListRecentActivity:
    """Tests for list_recent_activity — the activity feed."""

    def test_returns_events_newest_first(self, db):
        """Events are ordered by created_at descending."""
        db.add(AuditEvent(event_type="rfq_created", actor="system",
                          description="Old event",
                          created_at=datetime.utcnow() - timedelta(hours=1)))
        db.add(AuditEvent(event_type="state_changed", actor="system",
                          description="New event",
                          created_at=datetime.utcnow()))
        db.commit()

        events = list_recent_activity(db)
        assert events[0].description == "New event"
        assert events[1].description == "Old event"

    def test_respects_limit(self, db):
        """Limit parameter controls how many events are returned."""
        for i in range(10):
            db.add(AuditEvent(event_type="test", actor="system",
                              description=f"Event {i}"))
        db.commit()

        events = list_recent_activity(db, limit=3)
        assert len(events) == 3


# ---------------------------------------------------------------------------
# Approve Action tests
# ---------------------------------------------------------------------------


class TestApproveApproval:
    """Tests for approve_approval — inline approve from dashboard."""

    def test_approve_pending(self, db):
        """Approving a pending item flips status and sets resolved fields."""
        rfq = _make_rfq(db)
        db.add(Approval(rfq_id=rfq.id, approval_type=ApprovalType.CUSTOMER_REPLY,
                        draft_body="Draft", status=ApprovalStatus.PENDING_APPROVAL))
        db.commit()
        approval_id = db.query(Approval).first().id

        result = approve_approval(db, approval_id, resolved_by="jillian@beltmann.com")
        assert result is not None
        assert result.status == ApprovalStatus.APPROVED
        assert result.resolved_by == "jillian@beltmann.com"
        assert result.resolved_at is not None

    def test_approve_creates_audit_event(self, db):
        """Approving creates an audit event for traceability (C4)."""
        rfq = _make_rfq(db)
        db.add(Approval(rfq_id=rfq.id, approval_type=ApprovalType.CUSTOMER_REPLY,
                        draft_body="Draft", status=ApprovalStatus.PENDING_APPROVAL))
        db.commit()
        approval_id = db.query(Approval).first().id

        approve_approval(db, approval_id)
        events = db.query(AuditEvent).filter(
            AuditEvent.event_type == "approval_approved"
        ).all()
        assert len(events) == 1
        assert events[0].rfq_id == rfq.id

    def test_approve_already_approved_returns_none(self, db):
        """Cannot approve an already-approved item."""
        rfq = _make_rfq(db)
        db.add(Approval(rfq_id=rfq.id, approval_type=ApprovalType.CUSTOMER_REPLY,
                        draft_body="Draft", status=ApprovalStatus.APPROVED))
        db.commit()
        approval_id = db.query(Approval).first().id

        result = approve_approval(db, approval_id)
        assert result is None

    def test_approve_nonexistent_returns_none(self, db):
        """Approving a nonexistent ID returns None."""
        result = approve_approval(db, 9999)
        assert result is None

    def test_approve_with_edited_body(self, db):
        """Broker can edit the draft body before approving."""
        rfq = _make_rfq(db)
        db.add(Approval(rfq_id=rfq.id, approval_type=ApprovalType.CUSTOMER_REPLY,
                        draft_body="Original", status=ApprovalStatus.PENDING_APPROVAL))
        db.commit()
        approval_id = db.query(Approval).first().id

        result = approve_approval(db, approval_id, resolved_body="Edited version")
        assert result.resolved_body == "Edited version"
        assert result.status == ApprovalStatus.APPROVED


# ---------------------------------------------------------------------------
# Reject Action tests (#26)
# ---------------------------------------------------------------------------


class TestRejectApproval:
    """Tests for reject_approval — reject from approval modal."""

    def test_reject_pending(self, db):
        """Rejecting a pending item flips status to rejected."""
        rfq = _make_rfq(db)
        db.add(Approval(rfq_id=rfq.id, approval_type=ApprovalType.CUSTOMER_REPLY,
                        draft_body="Draft", status=ApprovalStatus.PENDING_APPROVAL))
        db.commit()
        approval_id = db.query(Approval).first().id

        result = reject_approval(db, approval_id)
        assert result is not None
        assert result.status == ApprovalStatus.REJECTED
        assert result.resolved_at is not None

    def test_reject_creates_audit_event(self, db):
        """Rejecting creates an audit event (C4)."""
        rfq = _make_rfq(db)
        db.add(Approval(rfq_id=rfq.id, approval_type=ApprovalType.CARRIER_RFQ,
                        draft_body="Draft", status=ApprovalStatus.PENDING_APPROVAL))
        db.commit()
        approval_id = db.query(Approval).first().id

        reject_approval(db, approval_id)
        events = db.query(AuditEvent).filter(
            AuditEvent.event_type == "approval_rejected"
        ).all()
        assert len(events) == 1

    def test_reject_already_resolved_returns_none(self, db):
        """Cannot reject an already-resolved item."""
        rfq = _make_rfq(db)
        db.add(Approval(rfq_id=rfq.id, approval_type=ApprovalType.CUSTOMER_REPLY,
                        draft_body="Draft", status=ApprovalStatus.APPROVED))
        db.commit()
        approval_id = db.query(Approval).first().id

        result = reject_approval(db, approval_id)
        assert result is None


# ---------------------------------------------------------------------------
# Skip Action tests (#26)
# ---------------------------------------------------------------------------


class TestSkipApproval:
    """Tests for skip_approval — skip from approval modal."""

    def test_skip_pending(self, db):
        """Skipping a pending item flips status to skipped."""
        rfq = _make_rfq(db)
        db.add(Approval(rfq_id=rfq.id, approval_type=ApprovalType.CUSTOMER_REPLY,
                        draft_body="Draft", status=ApprovalStatus.PENDING_APPROVAL))
        db.commit()
        approval_id = db.query(Approval).first().id

        result = skip_approval(db, approval_id)
        assert result is not None
        assert result.status == ApprovalStatus.SKIPPED
        assert result.resolved_at is not None

    def test_skip_creates_audit_event(self, db):
        """Skipping creates an audit event (C4)."""
        rfq = _make_rfq(db)
        db.add(Approval(rfq_id=rfq.id, approval_type=ApprovalType.CUSTOMER_QUOTE,
                        draft_body="Draft", status=ApprovalStatus.PENDING_APPROVAL))
        db.commit()
        approval_id = db.query(Approval).first().id

        skip_approval(db, approval_id)
        events = db.query(AuditEvent).filter(
            AuditEvent.event_type == "approval_skipped"
        ).all()
        assert len(events) == 1


# ---------------------------------------------------------------------------
# Approval Detail tests (#26)
# ---------------------------------------------------------------------------


class TestGetApprovalDetail:
    """Tests for get_approval_detail — full approval for modal display."""

    def test_returns_approval_with_rfq(self, db):
        """Detail includes the related RFQ via eager load."""
        rfq = _make_rfq(db, customer_name="Acme Corp")
        db.add(Approval(rfq_id=rfq.id, approval_type=ApprovalType.CUSTOMER_REPLY,
                        draft_body="Hello Acme", draft_subject="Re: Quote",
                        reason="First email", status=ApprovalStatus.PENDING_APPROVAL))
        db.commit()
        approval_id = db.query(Approval).first().id

        result = get_approval_detail(db, approval_id)
        assert result is not None
        assert result.draft_body == "Hello Acme"
        assert result.rfq.customer_name == "Acme Corp"

    def test_nonexistent_returns_none(self, db):
        """Nonexistent ID returns None."""
        result = get_approval_detail(db, 9999)
        assert result is None
