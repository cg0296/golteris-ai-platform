"""
tests/test_rfq_state_machine.py — Tests for the RFQ state transition engine (#14).

Verifies the four acceptance criteria:
    1. RFQs have a current state and transition history (FR-DM-2)
    2. State changes happen through explicit rules, not ad hoc updates (FR-DM-3)
    3. Human override is possible and logged (FR-DM-4)
    4. Initial states support the Beltmann MVP quoting flow
"""

from datetime import datetime

import pytest
from sqlalchemy import JSON, create_engine
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import sessionmaker

from backend.db.models import AuditEvent, Base, RFQ, RFQState
from backend.services.rfq_state_machine import (
    TRANSITION_RULES,
    IllegalTransitionError,
    get_allowed_transitions,
    get_transition_history,
    override_rfq_state,
    transition_rfq,
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


def _create_rfq(db, state=RFQState.NEEDS_CLARIFICATION) -> RFQ:
    """Create a minimal RFQ in the given state."""
    rfq = RFQ(
        customer_name="Test Customer",
        origin="Dallas, TX",
        destination="Atlanta, GA",
        state=state,
    )
    db.add(rfq)
    db.commit()
    db.refresh(rfq)
    return rfq


# ---------------------------------------------------------------------------
# Transition rule tests
# ---------------------------------------------------------------------------


class TestTransitionRules:
    """Acceptance criterion: state changes happen through explicit rules."""

    def test_happy_path_full_lifecycle(self, db):
        """Walk the full Beltmann MVP flow from start to won."""
        rfq = _create_rfq(db, RFQState.NEEDS_CLARIFICATION)

        transition_rfq(db, rfq.id, RFQState.READY_TO_QUOTE, "validation_agent", "Follow-up received")
        assert rfq.state == RFQState.READY_TO_QUOTE

        transition_rfq(db, rfq.id, RFQState.WAITING_ON_CARRIERS, "distribution_agent", "Sent to 5 carriers")
        assert rfq.state == RFQState.WAITING_ON_CARRIERS

        transition_rfq(db, rfq.id, RFQState.QUOTES_RECEIVED, "bid_parser", "3 bids received")
        assert rfq.state == RFQState.QUOTES_RECEIVED

        transition_rfq(db, rfq.id, RFQState.WAITING_ON_BROKER, "comparison_agent", "Bids ranked")
        assert rfq.state == RFQState.WAITING_ON_BROKER

        transition_rfq(db, rfq.id, RFQState.QUOTE_SENT, "jillian@beltmann.com", "Approved final quote")
        assert rfq.state == RFQState.QUOTE_SENT

        transition_rfq(db, rfq.id, RFQState.WON, "jillian@beltmann.com", "Customer accepted")
        assert rfq.state == RFQState.WON
        assert rfq.outcome == "won"
        assert rfq.closed_at is not None

    def test_illegal_transition_raises(self, db):
        """Jumping from needs_clarification to quote_sent should fail."""
        rfq = _create_rfq(db, RFQState.NEEDS_CLARIFICATION)

        with pytest.raises(IllegalTransitionError) as exc_info:
            transition_rfq(db, rfq.id, RFQState.QUOTE_SENT, "rogue_agent")

        assert exc_info.value.from_state == RFQState.NEEDS_CLARIFICATION
        assert exc_info.value.to_state == RFQState.QUOTE_SENT

    def test_cancelled_always_reachable(self, db):
        """CANCELLED should be reachable from any non-terminal state."""
        for state in [
            RFQState.NEEDS_CLARIFICATION,
            RFQState.READY_TO_QUOTE,
            RFQState.WAITING_ON_CARRIERS,
            RFQState.QUOTES_RECEIVED,
            RFQState.WAITING_ON_BROKER,
            RFQState.QUOTE_SENT,
        ]:
            rfq = _create_rfq(db, state)
            transition_rfq(db, rfq.id, RFQState.CANCELLED, "jillian@beltmann.com", "Deal fell through")
            assert rfq.state == RFQState.CANCELLED

    def test_cannot_transition_from_terminal(self, db):
        """Won, Lost, and Cancelled are terminal — no further transitions."""
        for terminal_state in [RFQState.WON, RFQState.LOST, RFQState.CANCELLED]:
            rfq = _create_rfq(db, terminal_state)
            with pytest.raises(IllegalTransitionError):
                transition_rfq(db, rfq.id, RFQState.READY_TO_QUOTE, "test")

    def test_cannot_cancel_terminal_state(self, db):
        """Can't cancel something that's already won/lost/cancelled."""
        rfq = _create_rfq(db, RFQState.WON)
        with pytest.raises(IllegalTransitionError):
            transition_rfq(db, rfq.id, RFQState.CANCELLED, "test")

    def test_backward_transition_allowed_where_defined(self, db):
        """ready_to_quote -> needs_clarification is legal (re-opened)."""
        rfq = _create_rfq(db, RFQState.READY_TO_QUOTE)
        transition_rfq(db, rfq.id, RFQState.NEEDS_CLARIFICATION, "validation_agent", "New info needed")
        assert rfq.state == RFQState.NEEDS_CLARIFICATION

    def test_nonexistent_rfq_raises(self, db):
        with pytest.raises(ValueError, match="not found"):
            transition_rfq(db, 99999, RFQState.READY_TO_QUOTE, "test")

    def test_terminal_state_sets_outcome_and_closed_at(self, db):
        """Moving to won/lost/cancelled should populate outcome and closed_at."""
        rfq = _create_rfq(db, RFQState.QUOTE_SENT)

        transition_rfq(db, rfq.id, RFQState.LOST, "jillian@beltmann.com", "Customer went elsewhere")
        assert rfq.outcome == "lost"
        assert rfq.closed_at is not None


# ---------------------------------------------------------------------------
# Audit logging tests
# ---------------------------------------------------------------------------


class TestAuditLogging:
    """Acceptance criterion: RFQs have transition history (FR-DM-2)."""

    def test_transition_creates_audit_event(self, db):
        """Every transition should create an audit event."""
        rfq = _create_rfq(db)
        transition_rfq(db, rfq.id, RFQState.READY_TO_QUOTE, "validation_agent", "Fields complete")

        events = db.query(AuditEvent).filter(AuditEvent.rfq_id == rfq.id).all()
        assert len(events) == 1
        assert events[0].event_type == "state_changed"
        assert events[0].actor == "validation_agent"
        assert "Ready to quote" in events[0].description
        assert events[0].event_data["old_state"] == "needs_clarification"
        assert events[0].event_data["new_state"] == "ready_to_quote"

    def test_transition_history_ordered(self, db):
        """get_transition_history should return events in chronological order."""
        rfq = _create_rfq(db)
        transition_rfq(db, rfq.id, RFQState.READY_TO_QUOTE, "agent", "Step 1")
        transition_rfq(db, rfq.id, RFQState.WAITING_ON_CARRIERS, "agent", "Step 2")
        transition_rfq(db, rfq.id, RFQState.QUOTES_RECEIVED, "agent", "Step 3")

        history = get_transition_history(db, rfq.id)
        assert len(history) == 3
        assert history[0].event_data["new_state"] == "ready_to_quote"
        assert history[1].event_data["new_state"] == "waiting_on_carriers"
        assert history[2].event_data["new_state"] == "quotes_received"

    def test_reason_appears_in_description(self, db):
        """The reason should be included in the plain-English description."""
        rfq = _create_rfq(db)
        transition_rfq(db, rfq.id, RFQState.READY_TO_QUOTE, "agent", "Customer provided missing weight")

        events = get_transition_history(db, rfq.id)
        assert "Customer provided missing weight" in events[0].description


# ---------------------------------------------------------------------------
# Override tests
# ---------------------------------------------------------------------------


class TestOverride:
    """Acceptance criterion: human override is possible and logged (FR-DM-4)."""

    def test_override_bypasses_rules(self, db):
        """Override should allow any transition, even illegal ones."""
        rfq = _create_rfq(db, RFQState.NEEDS_CLARIFICATION)

        # This would fail with transition_rfq — needs_clarification -> quote_sent is illegal
        result = override_rfq_state(
            db, rfq.id, RFQState.QUOTE_SENT,
            "jillian@beltmann.com", "Customer already got pricing verbally, just logging it"
        )
        assert result.state == RFQState.QUOTE_SENT

    def test_override_logs_distinct_event_type(self, db):
        """Override events should have event_type='state_override' to stand out."""
        rfq = _create_rfq(db)
        override_rfq_state(db, rfq.id, RFQState.WON, "jillian@beltmann.com", "Verbal confirmation")

        events = db.query(AuditEvent).filter(AuditEvent.rfq_id == rfq.id).all()
        assert len(events) == 1
        assert events[0].event_type == "state_override"
        assert events[0].event_data["override"] is True
        assert "Manual override" in events[0].description

    def test_override_requires_reason(self, db):
        """Override without a reason should raise ValueError."""
        rfq = _create_rfq(db)
        with pytest.raises(ValueError, match="reason is required"):
            override_rfq_state(db, rfq.id, RFQState.WON, "jillian@beltmann.com", "")

    def test_override_can_reopen_terminal(self, db):
        """Override can move a won/lost/cancelled RFQ back to an active state."""
        rfq = _create_rfq(db, RFQState.LOST)
        override_rfq_state(
            db, rfq.id, RFQState.WAITING_ON_BROKER,
            "jillian@beltmann.com", "Customer came back, reconsidering"
        )
        assert rfq.state == RFQState.WAITING_ON_BROKER
        assert rfq.outcome is None  # Cleared when reopened
        assert rfq.closed_at is None

    def test_override_nonexistent_rfq_raises(self, db):
        with pytest.raises(ValueError, match="not found"):
            override_rfq_state(db, 99999, RFQState.WON, "test", "reason")


# ---------------------------------------------------------------------------
# Allowed transitions helper tests
# ---------------------------------------------------------------------------


class TestGetAllowedTransitions:
    """get_allowed_transitions should return correct options for the UI."""

    def test_needs_clarification_options(self):
        allowed = get_allowed_transitions(RFQState.NEEDS_CLARIFICATION)
        assert RFQState.READY_TO_QUOTE in allowed
        assert RFQState.CANCELLED in allowed
        assert RFQState.WON not in allowed

    def test_terminal_states_have_no_transitions(self):
        for terminal in [RFQState.WON, RFQState.LOST, RFQState.CANCELLED]:
            assert get_allowed_transitions(terminal) == []

    def test_quote_sent_options(self):
        allowed = get_allowed_transitions(RFQState.QUOTE_SENT)
        assert RFQState.WON in allowed
        assert RFQState.LOST in allowed
        assert RFQState.CANCELLED in allowed


# ---------------------------------------------------------------------------
# Every state covered
# ---------------------------------------------------------------------------


class TestAllStatesHaveRules:
    """Every RFQState enum value should have an entry in TRANSITION_RULES."""

    def test_all_states_in_rules(self):
        for state in RFQState:
            assert state in TRANSITION_RULES, f"{state.value} missing from TRANSITION_RULES"
