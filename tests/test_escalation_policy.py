"""
tests/test_escalation_policy.py — Tests for confidence scoring and HITL escalation (#23).

Verifies the three acceptance criteria:
    1. Low-confidence fields flag the whole RFQ
    2. Threshold configurable per workflow
    3. Escalation reason is human-readable in the review card
"""

import pytest
from sqlalchemy import JSON, create_engine
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import sessionmaker

from backend.db.models import AuditEvent, Base, RFQ, RFQState, Workflow
from backend.services.escalation_policy import (
    DEFAULT_THRESHOLD,
    EscalationPolicy,
    create_review_card,
    evaluate_rfq,
    get_policy_for_workflow,
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


def _create_rfq(db, confidence_scores=None, **kwargs) -> RFQ:
    defaults = {
        "customer_name": "Test",
        "customer_email": "test@example.com",
        "origin": "Dallas, TX",
        "destination": "Atlanta, GA",
        "equipment_type": "Flatbed",
        "truck_count": 1,
        "commodity": "Steel coils",
        "state": RFQState.NEEDS_CLARIFICATION,
        "confidence_scores": confidence_scores,
    }
    defaults.update(kwargs)
    rfq = RFQ(**defaults)
    db.add(rfq)
    db.commit()
    db.refresh(rfq)
    return rfq


# ---------------------------------------------------------------------------
# EscalationPolicy tests
# ---------------------------------------------------------------------------


class TestEscalationPolicy:
    def test_default_threshold(self):
        policy = EscalationPolicy()
        assert policy.default_threshold == 0.90
        assert policy.get_threshold("origin") == 0.90
        assert policy.get_threshold("destination") == 0.90

    def test_per_field_override(self):
        policy = EscalationPolicy(
            default_threshold=0.90,
            field_thresholds={"destination": 0.80, "commodity": 0.75},
        )
        assert policy.get_threshold("origin") == 0.90  # Uses default
        assert policy.get_threshold("destination") == 0.80  # Uses override
        assert policy.get_threshold("commodity") == 0.75  # Uses override

    def test_custom_default_threshold(self):
        policy = EscalationPolicy(default_threshold=0.85)
        assert policy.get_threshold("origin") == 0.85


# ---------------------------------------------------------------------------
# Policy loading from workflow config
# ---------------------------------------------------------------------------


class TestGetPolicyForWorkflow:
    def test_no_workflow_returns_default(self, db):
        policy = get_policy_for_workflow(db, workflow_id=None)
        assert policy.default_threshold == DEFAULT_THRESHOLD

    def test_workflow_without_policy_returns_default(self, db):
        wf = Workflow(name="Basic", enabled=True, config={})
        db.add(wf)
        db.commit()

        policy = get_policy_for_workflow(db, wf.id)
        assert policy.default_threshold == DEFAULT_THRESHOLD

    def test_workflow_with_custom_policy(self, db):
        wf = Workflow(name="Custom", enabled=True, config={
            "escalation_policy": {
                "default_threshold": 0.85,
                "field_thresholds": {"destination": 0.80},
            },
        })
        db.add(wf)
        db.commit()

        policy = get_policy_for_workflow(db, wf.id)
        assert policy.default_threshold == 0.85
        assert policy.get_threshold("destination") == 0.80
        assert policy.get_threshold("origin") == 0.85  # Falls back to custom default

    def test_nonexistent_workflow_returns_default(self, db):
        policy = get_policy_for_workflow(db, workflow_id=99999)
        assert policy.default_threshold == DEFAULT_THRESHOLD


# ---------------------------------------------------------------------------
# RFQ evaluation tests
# ---------------------------------------------------------------------------


class TestEvaluateRfq:
    """Acceptance criterion: low-confidence fields flag the whole RFQ."""

    def test_high_confidence_no_escalation(self, db):
        rfq = _create_rfq(db, confidence_scores={
            "origin": 0.98, "destination": 0.98, "equipment_type": 0.99,
            "truck_count": 0.99, "commodity": 0.97, "weight_lbs": 0.98,
        })
        result = evaluate_rfq(rfq)
        assert result.needs_review is False
        assert len(result.reasons) == 0

    def test_low_confidence_triggers_escalation(self, db):
        rfq = _create_rfq(db, confidence_scores={
            "origin": 0.95, "destination": 0.45,  # Ambiguous Springfield
            "equipment_type": 0.97, "truck_count": 0.99,
            "commodity": 0.95, "weight_lbs": 0.94,
        })
        result = evaluate_rfq(rfq)
        assert result.needs_review is True
        low_fields = [f for f, _, _, _ in result.low_confidence_fields]
        assert "destination" in low_fields

    def test_missing_field_triggers_escalation(self, db):
        rfq = _create_rfq(db, commodity=None, confidence_scores={
            "origin": 0.95, "destination": 0.95, "equipment_type": 0.92,
            "truck_count": 0.99, "commodity": 0.0, "weight_lbs": 0.0,
        })
        result = evaluate_rfq(rfq)
        assert result.needs_review is True
        missing = [f for f, _ in result.missing_fields]
        assert "commodity" in missing

    def test_custom_threshold_changes_outcome(self, db):
        """With a lower threshold, a borderline field should pass."""
        rfq = _create_rfq(db, confidence_scores={
            "origin": 0.95, "destination": 0.87,  # Would fail at 0.90
            "equipment_type": 0.97, "truck_count": 0.99,
            "commodity": 0.95, "weight_lbs": 0.94,
        })

        # Default policy (0.90) — destination fails
        result_strict = evaluate_rfq(rfq, EscalationPolicy(default_threshold=0.90))
        assert result_strict.needs_review is True

        # Relaxed policy (0.85) — destination passes
        result_relaxed = evaluate_rfq(rfq, EscalationPolicy(default_threshold=0.85))
        assert result_relaxed.needs_review is False

    def test_per_field_threshold_override(self, db):
        """Per-field threshold should override the default for that field only."""
        rfq = _create_rfq(db, confidence_scores={
            "origin": 0.95, "destination": 0.87,
            "equipment_type": 0.97, "truck_count": 0.99,
            "commodity": 0.95, "weight_lbs": 0.94,
        })

        policy = EscalationPolicy(
            default_threshold=0.90,
            field_thresholds={"destination": 0.85},  # Relax just destination
        )
        result = evaluate_rfq(rfq, policy)
        assert result.needs_review is False  # 0.87 >= 0.85

    def test_no_confidence_scores_defaults_high(self, db):
        """RFQ with no confidence_scores should default to 1.0 (no escalation)."""
        rfq = _create_rfq(db, confidence_scores=None)
        result = evaluate_rfq(rfq)
        assert result.needs_review is False


# ---------------------------------------------------------------------------
# Review card tests
# ---------------------------------------------------------------------------


class TestCreateReviewCard:
    """Acceptance criterion: escalation reason is human-readable."""

    def test_creates_audit_event_with_plain_english(self, db):
        rfq = _create_rfq(db, confidence_scores={
            "origin": 0.95, "destination": 0.45,
            "equipment_type": 0.97, "truck_count": 0.99,
            "commodity": 0.95, "weight_lbs": 0.94,
        })
        escalation = evaluate_rfq(rfq)
        event = create_review_card(db, rfq.id, escalation)

        assert event is not None
        assert event.event_type == "escalated_for_review"
        assert event.actor == "escalation_policy"
        # C3: plain English, not jargon
        assert "flagged for review" in event.description.lower()
        assert "delivery location" in event.description.lower()
        assert "unclear" in event.description.lower()

    def test_no_review_card_when_not_escalated(self, db):
        rfq = _create_rfq(db, confidence_scores={
            "origin": 0.98, "destination": 0.98, "equipment_type": 0.99,
            "truck_count": 0.99, "commodity": 0.97, "weight_lbs": 0.98,
        })
        escalation = evaluate_rfq(rfq)
        event = create_review_card(db, rfq.id, escalation)
        assert event is None

    def test_multiple_reasons_in_card(self, db):
        rfq = _create_rfq(db, commodity=None, confidence_scores={
            "origin": 0.95, "destination": 0.45,
            "equipment_type": 0.97, "truck_count": 0.99,
            "commodity": 0.0, "weight_lbs": 0.0,
        })
        escalation = evaluate_rfq(rfq)
        event = create_review_card(db, rfq.id, escalation)

        assert event is not None
        assert len(escalation.reasons) >= 2
        # Both reasons should be in the event data
        assert len(event.event_data["reasons"]) >= 2

    def test_event_data_has_structured_details(self, db):
        rfq = _create_rfq(db, confidence_scores={
            "origin": 0.95, "destination": 0.45,
            "equipment_type": 0.97, "truck_count": 0.99,
            "commodity": 0.95, "weight_lbs": 0.94,
        })
        escalation = evaluate_rfq(rfq)
        event = create_review_card(db, rfq.id, escalation)

        # Structured data for the UI to render the review card
        assert "low_confidence_fields" in event.event_data
        assert event.event_data["low_confidence_fields"][0]["field"] == "destination"
        assert event.event_data["low_confidence_fields"][0]["score"] == 0.45
