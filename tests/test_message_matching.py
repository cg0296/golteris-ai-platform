"""
tests/test_message_matching.py — Tests for message-to-RFQ matching (#13).

Verifies the four acceptance criteria:
    1. Deterministic reply matches attach automatically
    2. Non-deterministic messages are scored against active RFQs
    3. Ambiguous matches do not auto-attach silently
    4. Match reason is stored for auditability
"""

import pytest
from sqlalchemy import JSON, create_engine
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import sessionmaker

from backend.db.models import (
    AuditEvent,
    Base,
    Message,
    MessageDirection,
    MessageRoutingStatus,
    ReviewQueue,
    RFQ,
    RFQState,
)
from backend.services.message_matching import (
    MatchResult,
    _extract_email,
    match_message_to_rfq,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_sqlite_compatible():
    for table in Base.metadata.tables.values():
        for column in table.columns:
            if isinstance(column.type, JSONB):
                column.type = JSON()


@pytest.fixture
def db():
    _make_sqlite_compatible()
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()


def _create_message(db, sender, subject="Test", body="Test body", **kwargs) -> Message:
    msg = Message(
        sender=sender,
        subject=subject,
        body=body,
        direction=MessageDirection.INBOUND,
        **kwargs,
    )
    db.add(msg)
    db.commit()
    db.refresh(msg)
    return msg


def _create_rfq(db, customer_email, state=RFQState.NEEDS_CLARIFICATION, **kwargs) -> RFQ:
    defaults = {
        "customer_name": "Test",
        "customer_email": customer_email,
        "state": state,
    }
    defaults.update(kwargs)
    rfq = RFQ(**defaults)
    db.add(rfq)
    db.commit()
    db.refresh(rfq)
    return rfq


# ---------------------------------------------------------------------------
# Thread matching tests (deterministic)
# ---------------------------------------------------------------------------


class TestThreadMatching:
    """Acceptance criterion: deterministic reply matches attach automatically."""

    def test_in_reply_to_matches_parent(self, db):
        """Reply with in_reply_to header -> attaches to parent's RFQ."""
        rfq = _create_rfq(db, "mike@prairie.com")
        original = _create_message(
            db, "mike@prairie.com", "Need a truck",
            message_id_header="<msg-003@prairie.com>",
            rfq_id=rfq.id,
        )

        reply = _create_message(
            db, "mike@prairie.com", "Re: Need a truck",
            body="Here's the missing commodity info: auto parts",
            in_reply_to="<msg-003@prairie.com>",
            message_id_header="<msg-007@prairie.com>",
        )

        result = match_message_to_rfq(db, reply.id)

        assert result.rfq_id == rfq.id
        assert result.confidence == 0.99
        assert result.method == "thread_reply"
        assert reply.routing_status == MessageRoutingStatus.ATTACHED

    def test_thread_id_matches_sibling(self, db):
        """Message with same thread_id as an existing message -> attaches to same RFQ."""
        rfq = _create_rfq(db, "sarah@global.com")
        first_msg = _create_message(
            db, "sarah@global.com", "Quote request",
            thread_id="thread-002",
            message_id_header="<msg-002@global.com>",
            rfq_id=rfq.id,
        )

        follow_up = _create_message(
            db, "sarah@global.com", "Re: Quote request",
            body="Adding more details",
            thread_id="thread-002",
            message_id_header="<msg-002b@global.com>",
        )

        result = match_message_to_rfq(db, follow_up.id)

        assert result.rfq_id == rfq.id
        assert result.confidence == 0.97
        assert result.method == "thread_id"


# ---------------------------------------------------------------------------
# Sender matching tests
# ---------------------------------------------------------------------------


class TestSenderMatching:
    """Acceptance criterion: non-deterministic messages scored against active RFQs."""

    def test_single_active_rfq_auto_attaches(self, db):
        """One active RFQ from this sender + context match -> auto-attach."""
        rfq = _create_rfq(
            db, "tom@acme.com",
            origin="Dallas, TX", destination="Atlanta, GA",
            equipment_type="Flatbed",
        )
        msg = _create_message(
            db, "tom@acme.com", "Updated weight info",
            body="The Dallas to Atlanta flatbed load is actually 44,000 lbs",
        )

        result = match_message_to_rfq(db, msg.id)

        # Sender match (0.70) + origin in body (0.08) + destination in body (0.08)
        # + equipment in body (0.05) = 0.91 >= 0.85 threshold
        assert result.rfq_id == rfq.id
        assert result.routing_status == MessageRoutingStatus.ATTACHED

    def test_no_active_rfqs_flags_new(self, db):
        """No matching RFQs -> flagged as new RFQ."""
        msg = _create_message(
            db, "newcustomer@example.com", "Quote request",
            body="Need a van from LA to SF",
        )

        result = match_message_to_rfq(db, msg.id)

        assert result.rfq_id is None
        assert result.routing_status == MessageRoutingStatus.NEW_RFQ_CREATED
        assert result.method == "no_match"

    def test_closed_rfqs_ignored(self, db):
        """Won/lost/cancelled RFQs should not be matched."""
        _create_rfq(db, "tom@acme.com", state=RFQState.WON)
        msg = _create_message(
            db, "tom@acme.com", "New request",
            body="Need a new quote for something else",
        )

        result = match_message_to_rfq(db, msg.id)

        assert result.rfq_id is None
        assert result.routing_status == MessageRoutingStatus.NEW_RFQ_CREATED


# ---------------------------------------------------------------------------
# Ambiguous matching tests
# ---------------------------------------------------------------------------


class TestAmbiguousMatching:
    """Acceptance criterion: ambiguous matches do not auto-attach silently."""

    def test_multiple_rfqs_same_sender_goes_to_review(self, db):
        """Two active RFQs from same sender, no strong context signal -> review queue."""
        _create_rfq(db, "sarah@global.com", origin="Houston, TX", destination="Memphis, TN")
        _create_rfq(db, "sarah@global.com", origin="Houston, TX", destination="Nashville, TN")

        msg = _create_message(
            db, "sarah@global.com", "Update on the project",
            body="Just wanted to check on the status",
        )

        result = match_message_to_rfq(db, msg.id)

        assert result.rfq_id is None
        assert result.routing_status == MessageRoutingStatus.NEEDS_REVIEW
        assert len(result.candidates) == 2

        # Verify review queue entry was created (FR-EI-4)
        review = db.query(ReviewQueue).filter(ReviewQueue.message_id == msg.id).first()
        assert review is not None
        assert review.status.value == "pending"
        assert len(review.candidates) == 2

    def test_weak_single_match_goes_to_review(self, db):
        """Single sender match but no context boost -> stays below threshold -> review."""
        _create_rfq(db, "someone@company.com", origin="NYC", destination="Boston")
        msg = _create_message(
            db, "someone@company.com", "Hey",
            body="Just following up on something",  # No route/equipment keywords
        )

        result = match_message_to_rfq(db, msg.id)

        # Base sender score is 0.70, no context boosts -> below 0.85 threshold
        assert result.routing_status == MessageRoutingStatus.NEEDS_REVIEW


# ---------------------------------------------------------------------------
# Audit and reason storage tests
# ---------------------------------------------------------------------------


class TestAuditability:
    """Acceptance criterion: match reason is stored for auditability."""

    def test_successful_match_creates_audit_event(self, db):
        """A successful match should log an audit event with the reason."""
        rfq = _create_rfq(db, "tom@acme.com", origin="Dallas, TX", destination="Atlanta, GA")
        original = _create_message(
            db, "tom@acme.com", "Original request",
            message_id_header="<orig@acme.com>",
            rfq_id=rfq.id,
        )
        reply = _create_message(
            db, "tom@acme.com", "Re: Original request",
            in_reply_to="<orig@acme.com>",
            message_id_header="<reply@acme.com>",
        )

        match_message_to_rfq(db, reply.id)

        events = db.query(AuditEvent).filter(
            AuditEvent.rfq_id == rfq.id,
            AuditEvent.event_type == "message_matched",
        ).all()
        assert len(events) == 1
        assert "thread_reply" in events[0].event_data["method"]
        assert events[0].event_data["confidence"] == 0.99

    def test_review_queue_stores_candidates_with_reasons(self, db):
        """Review queue entries should include candidate RFQs with scores and reasons."""
        rfq1 = _create_rfq(db, "multi@company.com", origin="Portland, OR")
        rfq2 = _create_rfq(db, "multi@company.com", origin="Seattle, WA")
        msg = _create_message(db, "multi@company.com", "Update", body="just checking in on status")

        match_message_to_rfq(db, msg.id)

        review = db.query(ReviewQueue).filter(ReviewQueue.message_id == msg.id).first()
        assert review is not None
        # Each candidate has rfq_id, score, and reason
        for candidate in review.candidates:
            assert "rfq_id" in candidate
            assert "score" in candidate
            assert "reason" in candidate


# ---------------------------------------------------------------------------
# Email extraction helper tests
# ---------------------------------------------------------------------------


class TestExtractEmail:
    def test_bare_email(self):
        assert _extract_email("tom@acme.com") == "tom@acme.com"

    def test_angle_bracket_format(self):
        assert _extract_email("Tom Reynolds <tom@acme.com>") == "tom@acme.com"

    def test_case_normalized(self):
        assert _extract_email("TOM@ACME.COM") == "tom@acme.com"

    def test_none_returns_none(self):
        assert _extract_email(None) is None

    def test_empty_returns_none(self):
        assert _extract_email("") is None
