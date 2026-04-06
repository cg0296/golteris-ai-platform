"""
tests/test_validation_agent.py — Tests for missing-info detection and follow-up drafting (#15).

Verifies the three acceptance criteria:
    1. The system can flag missing required fields from a sample Beltmann-style email
    2. A draft follow-up email is generated with the missing items called out clearly
    3. The draft is reviewable before sending (persisted as pending_approval)
"""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import JSON, create_engine
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import sessionmaker

from backend.agents.validation import (
    CONFIDENCE_THRESHOLD,
    REQUIRED_FIELDS,
    detect_missing_info,
    draft_followup,
)
from backend.db.models import (
    Approval,
    ApprovalStatus,
    ApprovalType,
    AuditEvent,
    Base,
    RFQ,
    RFQState,
)
from backend.llm.provider import LLMResponse


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


def _create_rfq(db, **kwargs) -> RFQ:
    """Create an RFQ with given fields. Unspecified fields default to None."""
    defaults = {
        "customer_name": "Test Customer",
        "customer_email": "test@example.com",
        "state": RFQState.NEEDS_CLARIFICATION,
    }
    defaults.update(kwargs)
    rfq = RFQ(**defaults)
    db.add(rfq)
    db.commit()
    db.refresh(rfq)
    return rfq


# ---------------------------------------------------------------------------
# detect_missing_info tests
# ---------------------------------------------------------------------------


class TestDetectMissingInfo:
    """Acceptance criterion: flag missing required fields."""

    def test_complete_rfq_has_no_missing(self, db):
        """An RFQ with all required fields should not need follow-up."""
        rfq = _create_rfq(
            db,
            origin="Dallas, TX",
            destination="Atlanta, GA",
            equipment_type="Flatbed",
            truck_count=1,
            commodity="Steel coils",
            weight_lbs=42000,
            confidence_scores={
                "origin": 0.98, "destination": 0.98, "equipment_type": 0.99,
                "truck_count": 0.99, "commodity": 0.97, "weight_lbs": 0.98,
            },
        )
        result = detect_missing_info(db, rfq.id)

        assert result["needs_followup"] is False
        assert len(result["missing_required"]) == 0
        assert len(result["low_confidence"]) == 0

    def test_missing_commodity_and_weight(self, db):
        """Seed email 03 pattern: missing commodity and weight."""
        rfq = _create_rfq(
            db,
            origin="Chicago, IL",
            destination="Detroit, MI",
            equipment_type="Van",
            truck_count=1,
            commodity=None,
            weight_lbs=None,
            confidence_scores={
                "origin": 0.95, "destination": 0.95, "equipment_type": 0.92,
                "truck_count": 0.99, "commodity": 0.0, "weight_lbs": 0.0,
            },
        )
        result = detect_missing_info(db, rfq.id)

        assert result["needs_followup"] is True
        missing_fields = [f for f, _ in result["missing_required"]]
        assert "commodity" in missing_fields
        # weight_lbs is recommended, not required
        recommended_fields = [f for f, _ in result["missing_recommended"]]
        assert "weight_lbs" in recommended_fields

    def test_low_confidence_destination(self, db):
        """Seed email 05 pattern: ambiguous 'Springfield' with low confidence."""
        rfq = _create_rfq(
            db,
            origin="Kansas City, MO",
            destination="Springfield",
            equipment_type="Van",
            truck_count=1,
            commodity="Household goods",
            weight_lbs=35000,
            confidence_scores={
                "origin": 0.93, "destination": 0.45,
                "equipment_type": 0.97, "truck_count": 0.99,
                "commodity": 0.95, "weight_lbs": 0.94,
            },
        )
        result = detect_missing_info(db, rfq.id)

        assert result["needs_followup"] is True
        assert len(result["missing_required"]) == 0  # Nothing null
        low_conf_fields = [f for f, _, _ in result["low_confidence"]]
        assert "destination" in low_conf_fields

    def test_missing_dates_are_recommended(self, db):
        """Seed email 04 pattern: missing dates flagged as recommended, not required."""
        rfq = _create_rfq(
            db,
            origin="Indianapolis, IN",
            destination="Columbus, OH",
            equipment_type="Reefer",
            truck_count=1,
            commodity="Pharmaceuticals",
            weight_lbs=38000,
            pickup_date=None,
            delivery_date=None,
            confidence_scores={
                "origin": 0.98, "destination": 0.98, "equipment_type": 0.97,
                "truck_count": 0.99, "commodity": 0.95, "weight_lbs": 0.96,
            },
        )
        result = detect_missing_info(db, rfq.id)

        # Dates are recommended, not required — shouldn't trigger needs_followup
        # unless a required field is also missing
        assert result["needs_followup"] is False
        recommended_fields = [f for f, _ in result["missing_recommended"]]
        assert "pickup_date" in recommended_fields
        assert "delivery_date" in recommended_fields

    def test_nonexistent_rfq_returns_none(self, db):
        result = detect_missing_info(db, 99999)
        assert result is None

    def test_no_confidence_scores_defaults_high(self, db):
        """RFQ with no confidence_scores should default to 1.0 (assume confident)."""
        rfq = _create_rfq(
            db,
            origin="A", destination="B", equipment_type="Van",
            truck_count=1, commodity="Stuff",
            confidence_scores=None,
        )
        result = detect_missing_info(db, rfq.id)
        assert result["needs_followup"] is False


# ---------------------------------------------------------------------------
# draft_followup tests (mocked LLM)
# ---------------------------------------------------------------------------


class TestDraftFollowup:
    """Acceptance criteria: draft follow-up generated and reviewable."""

    @patch("backend.agents.validation.call_llm")
    @patch("backend.agents.validation.start_run")
    @patch("backend.agents.validation.finish_run")
    def test_drafts_followup_for_missing_fields(self, mock_finish, mock_start, mock_llm, db):
        """Missing commodity -> draft follow-up with pending_approval status (C2)."""
        rfq = _create_rfq(
            db,
            origin="Chicago, IL",
            destination="Detroit, MI",
            equipment_type="Van",
            truck_count=1,
            commodity=None,
            confidence_scores={"origin": 0.95, "destination": 0.95,
                               "equipment_type": 0.92, "truck_count": 0.99,
                               "commodity": 0.0, "weight_lbs": 0.0},
        )

        mock_run = MagicMock()
        mock_run.id = 1
        mock_start.return_value = mock_run

        mock_llm.return_value = LLMResponse(
            content=None,
            tool_calls=[{
                "name": "draft_followup_email",
                "input": {
                    "subject": "Re: Need a truck ASAP — A couple details needed",
                    "body": "Hi Mike,\n\nThanks for reaching out about the Chicago to Detroit move. We'd love to get you a rate — could you let us know:\n\n- What commodity will be shipped?\n- Approximate weight per truck?\n\nOnce we have those details, we'll get you a quote right away.\n\nBest,\nBeltmann Logistics",
                },
            }],
            input_tokens=800,
            output_tokens=200,
            model="claude-sonnet-4-6",
        )

        approval = draft_followup(db, rfq.id)

        # C2: draft stored as pending_approval
        assert approval is not None
        assert approval.status == ApprovalStatus.PENDING_APPROVAL
        assert approval.approval_type == ApprovalType.CUSTOMER_REPLY
        assert "couple details needed" in approval.draft_subject
        assert "commodity" in approval.draft_body.lower() or "shipped" in approval.draft_body.lower()
        assert approval.draft_recipient == "test@example.com"
        assert "commodity" in approval.reason.lower() or "missing" in approval.reason.lower()

    @patch("backend.agents.validation.call_llm")
    @patch("backend.agents.validation.start_run")
    @patch("backend.agents.validation.finish_run")
    def test_no_followup_for_complete_rfq(self, mock_finish, mock_start, mock_llm, db):
        """Complete RFQ should return None — no follow-up needed."""
        rfq = _create_rfq(
            db,
            origin="Dallas, TX", destination="Atlanta, GA",
            equipment_type="Flatbed", truck_count=1, commodity="Steel",
            confidence_scores={"origin": 0.98, "destination": 0.98,
                               "equipment_type": 0.99, "truck_count": 0.99,
                               "commodity": 0.97, "weight_lbs": 0.98},
        )

        result = draft_followup(db, rfq.id)

        assert result is None
        mock_llm.assert_not_called()  # No LLM call needed

    @patch("backend.agents.validation.call_llm")
    @patch("backend.agents.validation.start_run")
    @patch("backend.agents.validation.finish_run")
    def test_low_confidence_triggers_followup(self, mock_finish, mock_start, mock_llm, db):
        """Ambiguous destination (confidence 0.45) should trigger a follow-up."""
        rfq = _create_rfq(
            db,
            origin="Kansas City, MO", destination="Springfield",
            equipment_type="Van", truck_count=1, commodity="Household goods",
            weight_lbs=35000,
            confidence_scores={"origin": 0.93, "destination": 0.45,
                               "equipment_type": 0.97, "truck_count": 0.99,
                               "commodity": 0.95, "weight_lbs": 0.94},
        )

        mock_run = MagicMock()
        mock_run.id = 2
        mock_start.return_value = mock_run

        mock_llm.return_value = LLMResponse(
            content=None,
            tool_calls=[{
                "name": "draft_followup_email",
                "input": {
                    "subject": "Re: Quote - Van Load to Springfield — Quick clarification",
                    "body": "Hi David,\n\nThanks for the quote request for the Kansas City to Springfield van load. Just a quick question — could you confirm which Springfield you need delivery to? (Springfield, MO or Springfield, IL?)\n\nWe'll get your rate over as soon as we confirm.\n\nBest,\nBeltmann Logistics",
                },
            }],
            input_tokens=700,
            output_tokens=180,
            model="claude-sonnet-4-6",
        )

        approval = draft_followup(db, rfq.id)

        assert approval is not None
        assert approval.status == ApprovalStatus.PENDING_APPROVAL
        assert "Springfield" in approval.draft_body or "destination" in approval.reason.lower()

    @patch("backend.agents.validation.call_llm")
    @patch("backend.agents.validation.start_run")
    @patch("backend.agents.validation.finish_run")
    def test_audit_event_created(self, mock_finish, mock_start, mock_llm, db):
        """Drafting a follow-up should create a plain-English audit event (C3)."""
        rfq = _create_rfq(
            db,
            origin="A", destination="B", equipment_type="Van",
            truck_count=1, commodity=None,
            confidence_scores={"origin": 0.98, "destination": 0.98,
                               "equipment_type": 0.99, "truck_count": 0.99,
                               "commodity": 0.0, "weight_lbs": 0.0},
        )

        mock_run = MagicMock()
        mock_run.id = 3
        mock_start.return_value = mock_run
        mock_llm.return_value = LLMResponse(
            content=None,
            tool_calls=[{
                "name": "draft_followup_email",
                "input": {"subject": "Follow up", "body": "Please provide details."},
            }],
            input_tokens=500, output_tokens=100, model="claude-sonnet-4-6",
        )

        draft_followup(db, rfq.id)

        events = db.query(AuditEvent).filter(AuditEvent.rfq_id == rfq.id).all()
        assert len(events) == 1
        assert events[0].event_type == "followup_drafted"
        assert events[0].actor == "validation_agent"
        # C3: plain English, not jargon
        assert "Draft follow-up prepared" in events[0].description
        assert "what is being shipped" in events[0].description

    @patch("backend.agents.validation.call_llm")
    @patch("backend.agents.validation.start_run")
    @patch("backend.agents.validation.finish_run")
    @patch("backend.agents.validation.fail_run")
    def test_llm_no_tool_call_fails_gracefully(self, mock_fail, mock_finish, mock_start, mock_llm, db):
        """If the LLM doesn't call the tool, draft_followup returns None."""
        rfq = _create_rfq(
            db,
            origin="A", commodity=None,
            confidence_scores={"origin": 0.98, "destination": 0.0,
                               "equipment_type": 0.0, "truck_count": 0.0,
                               "commodity": 0.0, "weight_lbs": 0.0},
        )

        mock_run = MagicMock()
        mock_run.id = 4
        mock_start.return_value = mock_run
        mock_llm.return_value = LLMResponse(
            content="I can't draft this.", tool_calls=[],
            input_tokens=100, output_tokens=50, model="claude-sonnet-4-6",
        )

        result = draft_followup(db, rfq.id)
        assert result is None
        mock_fail.assert_called_once()

    def test_nonexistent_rfq_returns_none(self, db):
        result = draft_followup(db, 99999)
        assert result is None
