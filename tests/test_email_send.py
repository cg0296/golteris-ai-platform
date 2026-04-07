"""
tests/test_email_send.py — Tests for outbound email sending (#25).

Verifies the C2 enforcement gate and the send pipeline:
    1. Only APPROVED drafts trigger a send
    2. Non-approved drafts are refused
    3. Successful sends create outbound Message + AuditEvent
    4. Failed sends create a failure AuditEvent (FR-HI-6)
"""

from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import JSON, create_engine
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import sessionmaker

from backend.db.models import (
    Approval,
    ApprovalStatus,
    ApprovalType,
    AuditEvent,
    Base,
    Message,
    MessageDirection,
    RFQ,
    RFQState,
)
from backend.services.email_send import send_approved_email


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


def _make_rfq(db) -> RFQ:
    rfq = RFQ(
        customer_name="Test Shipper", customer_company="Test Co",
        origin="Chicago, IL", destination="Dallas, TX",
        state=RFQState.READY_TO_QUOTE,
        created_at=datetime.utcnow(), updated_at=datetime.utcnow(),
    )
    db.add(rfq)
    db.commit()
    db.refresh(rfq)
    return rfq


def _make_approval(db, rfq_id, status=ApprovalStatus.APPROVED) -> Approval:
    approval = Approval(
        rfq_id=rfq_id,
        approval_type=ApprovalType.CUSTOMER_REPLY,
        draft_body="Hi, here is your quote.",
        draft_subject="Re: Quote Request",
        draft_recipient="shipper@example.com",
        reason="Draft reply ready",
        status=status,
        resolved_by="broker" if status == ApprovalStatus.APPROVED else None,
        resolved_at=datetime.utcnow() if status == ApprovalStatus.APPROVED else None,
    )
    db.add(approval)
    db.commit()
    db.refresh(approval)
    return approval


class TestC2Gate:
    """C2 enforcement — no email sends without approved=true."""

    @patch("backend.services.email_send.get_provider_from_config")
    def test_approved_sends(self, mock_provider_fn, db):
        """An APPROVED approval triggers a send."""
        mock_provider = MagicMock()
        mock_provider.send_message.return_value = {"success": True, "message_id": "abc", "error": None}
        mock_provider.get_provider_name.return_value = "mock"
        mock_provider_fn.return_value = mock_provider

        rfq = _make_rfq(db)
        approval = _make_approval(db, rfq.id, ApprovalStatus.APPROVED)

        send_approved_email(db, approval.id)

        # Verify provider.send_message was called
        mock_provider.send_message.assert_called_once()
        call_kwargs = mock_provider.send_message.call_args
        assert call_kwargs[1]["to"] == "shipper@example.com"
        assert call_kwargs[1]["subject"] == "Re: Quote Request"

    @patch("backend.services.email_send.get_provider_from_config")
    def test_pending_does_not_send(self, mock_provider_fn, db):
        """A PENDING_APPROVAL approval does NOT trigger a send (C2)."""
        mock_provider = MagicMock()
        mock_provider_fn.return_value = mock_provider

        rfq = _make_rfq(db)
        approval = _make_approval(db, rfq.id, ApprovalStatus.PENDING_APPROVAL)

        send_approved_email(db, approval.id)

        # Provider should never be called
        mock_provider.send_message.assert_not_called()

    @patch("backend.services.email_send.get_provider_from_config")
    def test_rejected_does_not_send(self, mock_provider_fn, db):
        """A REJECTED approval does NOT trigger a send (C2)."""
        mock_provider = MagicMock()
        mock_provider_fn.return_value = mock_provider

        rfq = _make_rfq(db)
        approval = _make_approval(db, rfq.id, ApprovalStatus.REJECTED)

        send_approved_email(db, approval.id)

        mock_provider.send_message.assert_not_called()

    @patch("backend.services.email_send.get_provider_from_config")
    def test_nonexistent_approval_no_crash(self, mock_provider_fn, db):
        """Sending for a nonexistent approval ID doesn't crash."""
        send_approved_email(db, 9999)
        mock_provider_fn.return_value.send_message.assert_not_called()


class TestSendSuccess:
    """Successful sends persist outbound message and audit event."""

    @patch("backend.services.email_send.get_provider_from_config")
    def test_creates_outbound_message(self, mock_provider_fn, db):
        """A successful send creates an OUTBOUND Message row."""
        mock_provider = MagicMock()
        mock_provider.send_message.return_value = {"success": True, "message_id": None, "error": None}
        mock_provider.get_provider_name.return_value = "mock"
        mock_provider_fn.return_value = mock_provider

        rfq = _make_rfq(db)
        approval = _make_approval(db, rfq.id)

        send_approved_email(db, approval.id)

        outbound = db.query(Message).filter(
            Message.rfq_id == rfq.id,
            Message.direction == MessageDirection.OUTBOUND,
        ).first()
        assert outbound is not None
        assert outbound.recipients == "shipper@example.com"
        assert outbound.subject == "Re: Quote Request"

    @patch("backend.services.email_send.get_provider_from_config")
    def test_creates_email_sent_event(self, mock_provider_fn, db):
        """A successful send creates an 'email_sent' audit event (C4)."""
        mock_provider = MagicMock()
        mock_provider.send_message.return_value = {"success": True, "message_id": None, "error": None}
        mock_provider.get_provider_name.return_value = "mock"
        mock_provider_fn.return_value = mock_provider

        rfq = _make_rfq(db)
        approval = _make_approval(db, rfq.id)

        send_approved_email(db, approval.id)

        event = db.query(AuditEvent).filter(
            AuditEvent.event_type == "email_sent"
        ).first()
        assert event is not None
        assert "shipper@example.com" in event.description

    @patch("backend.services.email_send.get_provider_from_config")
    def test_uses_resolved_body_if_edited(self, mock_provider_fn, db):
        """If the broker edited the draft, the edited body is sent."""
        mock_provider = MagicMock()
        mock_provider.send_message.return_value = {"success": True, "message_id": None, "error": None}
        mock_provider.get_provider_name.return_value = "mock"
        mock_provider_fn.return_value = mock_provider

        rfq = _make_rfq(db)
        approval = _make_approval(db, rfq.id)
        approval.resolved_body = "Edited version of the reply"
        db.commit()

        send_approved_email(db, approval.id)

        call_kwargs = mock_provider.send_message.call_args
        assert call_kwargs[1]["body"] == "Edited version of the reply"


class TestSendFailure:
    """Failed sends create review cards, not silent disappearance (FR-HI-6)."""

    @patch("backend.services.email_send.get_provider_from_config")
    def test_failure_creates_review_event(self, mock_provider_fn, db):
        """A failed send creates an 'email_send_failed' audit event."""
        mock_provider = MagicMock()
        mock_provider.send_message.return_value = {"success": False, "message_id": None, "error": "Auth failed"}
        mock_provider.get_provider_name.return_value = "mock"
        mock_provider_fn.return_value = mock_provider

        rfq = _make_rfq(db)
        approval = _make_approval(db, rfq.id)

        send_approved_email(db, approval.id)

        event = db.query(AuditEvent).filter(
            AuditEvent.event_type == "email_send_failed"
        ).first()
        assert event is not None
        assert "Auth failed" in event.description

    @patch("backend.services.email_send.get_provider_from_config")
    def test_failure_does_not_create_outbound_message(self, mock_provider_fn, db):
        """A failed send does NOT persist an outbound message."""
        mock_provider = MagicMock()
        mock_provider.send_message.return_value = {"success": False, "message_id": None, "error": "Timeout"}
        mock_provider.get_provider_name.return_value = "mock"
        mock_provider_fn.return_value = mock_provider

        rfq = _make_rfq(db)
        approval = _make_approval(db, rfq.id)

        send_approved_email(db, approval.id)

        outbound = db.query(Message).filter(
            Message.direction == MessageDirection.OUTBOUND,
        ).first()
        assert outbound is None
