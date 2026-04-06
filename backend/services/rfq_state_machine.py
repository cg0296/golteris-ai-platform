"""
backend/services/rfq_state_machine.py — RFQ state transition engine.

This module owns all RFQ state changes. No other code should directly update
rfq.state — everything goes through transition_rfq() or override_rfq_state().

The state machine implements the Beltmann MVP quoting flow:

    needs_clarification ─→ ready_to_quote ─→ waiting_on_carriers
                                                    │
                                             quotes_received
                                                    │
                                           waiting_on_broker
                                                    │
                                               quote_sent
                                              ╱    │    ╲
                                           won   lost   cancelled

    Any state ──→ cancelled  (always legal — customer abandoned, deal fell through)

Design decisions:
    - Transitions are enforced in application code, not DB constraints,
      so that manual overrides are possible (FR-DM-4).
    - Every state change creates an audit_events row for the RFQ detail
      timeline (C4 — visible reasoning, FR-DM-2 — full transition history).
    - Override bypasses the rules but still logs — the broker always has
      a record of what happened and who did it.

Called by:
    - Agents (extraction sets initial state, validation transitions to ready_to_quote, etc.)
    - API routes (broker approves, rejects, or manually moves an RFQ)
    - Background worker (carrier responses trigger state changes)

Cross-cutting constraints:
    C4 — Every state change is auditable via audit_events
    FR-DM-2 — Every RFQ has a current state AND full transition history
    FR-DM-3 — States match the MVP lifecycle
    FR-DM-4 — Manual override is supported and logged
"""

import logging
from datetime import datetime
from typing import Optional

from sqlalchemy.orm import Session

from backend.db.models import AuditEvent, RFQ, RFQState

logger = logging.getLogger("golteris.services.rfq_state_machine")


# ---------------------------------------------------------------------------
# Transition rules — the explicit map of what moves are legal.
#
# Format: {from_state: [list of allowed to_states]}
#
# These encode the Beltmann MVP flow. Adding a new transition is as simple
# as adding an entry here — no other code needs to change.
#
# CANCELLED is always reachable from any state (deal can fall through at
# any point). This is enforced in _is_transition_allowed() rather than
# repeating it in every entry.
# ---------------------------------------------------------------------------

TRANSITION_RULES: dict[RFQState, list[RFQState]] = {
    RFQState.NEEDS_CLARIFICATION: [
        RFQState.READY_TO_QUOTE,       # Follow-up received, fields now complete
    ],
    RFQState.READY_TO_QUOTE: [
        RFQState.WAITING_ON_CARRIERS,   # Carrier RFQs sent out
        RFQState.NEEDS_CLARIFICATION,   # Re-opened — new info needed after review
    ],
    RFQState.WAITING_ON_CARRIERS: [
        RFQState.QUOTES_RECEIVED,       # At least one carrier bid came back
        RFQState.READY_TO_QUOTE,        # No bids received, need to re-quote or adjust
    ],
    RFQState.QUOTES_RECEIVED: [
        RFQState.WAITING_ON_BROKER,     # Bids ranked, waiting for broker to pick one
        RFQState.WAITING_ON_CARRIERS,   # Need more bids, sent to additional carriers
    ],
    RFQState.WAITING_ON_BROKER: [
        RFQState.QUOTE_SENT,            # Broker approved and sent final quote to customer
        RFQState.QUOTES_RECEIVED,       # Broker sent back for more carrier options
    ],
    RFQState.QUOTE_SENT: [
        RFQState.WON,                   # Customer accepted the quote
        RFQState.LOST,                  # Customer declined or went with another broker
    ],
    # Terminal states — no further transitions (except override)
    RFQState.WON: [],
    RFQState.LOST: [],
    RFQState.CANCELLED: [],
}


def transition_rfq(
    db: Session,
    rfq_id: int,
    new_state: RFQState,
    actor: str,
    reason: Optional[str] = None,
) -> RFQ:
    """
    Move an RFQ to a new state through the state machine.

    Validates that the transition is legal before applying it. Creates an
    audit event recording the change for the RFQ detail timeline (C4).

    Args:
        db: SQLAlchemy session.
        rfq_id: The RFQ to transition.
        new_state: The target state.
        actor: Who is making this change — an agent name (e.g., "extraction_agent",
               "validation_agent") or a user identifier (e.g., "jillian@beltmann.com").
        reason: Optional human-readable reason for the transition, shown in the
                RFQ detail timeline (e.g., "Follow-up received with missing fields",
                "Carrier bids received from 3 carriers").

    Returns:
        The updated RFQ with the new state.

    Raises:
        ValueError: If the RFQ doesn't exist.
        IllegalTransitionError: If the transition violates the rules.
    """
    rfq = db.query(RFQ).filter(RFQ.id == rfq_id).first()
    if not rfq:
        raise ValueError(f"RFQ {rfq_id} not found")

    old_state = rfq.state

    # Validate the transition is legal
    if not _is_transition_allowed(old_state, new_state):
        raise IllegalTransitionError(
            rfq_id=rfq_id,
            from_state=old_state,
            to_state=new_state,
            allowed=get_allowed_transitions(old_state),
        )

    # Apply the transition
    rfq.state = new_state
    rfq.updated_at = datetime.utcnow()

    # If moving to a terminal state, record the outcome and closed_at
    if new_state in (RFQState.WON, RFQState.LOST, RFQState.CANCELLED):
        rfq.outcome = new_state.value
        rfq.closed_at = datetime.utcnow()

    # Log the audit event (C4 — visible reasoning, FR-DM-2 — transition history)
    _log_state_change(db, rfq, old_state, new_state, actor, reason)

    db.commit()
    db.refresh(rfq)

    logger.info(
        "RFQ %d transitioned: %s -> %s (actor=%s, reason=%s)",
        rfq_id, old_state.value, new_state.value, actor, reason,
    )

    return rfq


def override_rfq_state(
    db: Session,
    rfq_id: int,
    new_state: RFQState,
    actor: str,
    reason: str,
) -> RFQ:
    """
    Force an RFQ into any state, bypassing transition rules (FR-DM-4).

    This is the manual override for when the broker needs to fix a stuck
    RFQ, reopen a closed deal, or handle an edge case the rules don't cover.
    The reason is REQUIRED (not optional) because overrides must be justified
    in the audit trail.

    The override is logged with event_type="state_override" so it's visually
    distinct from normal transitions in the timeline.

    Args:
        db: SQLAlchemy session.
        rfq_id: The RFQ to override.
        new_state: The target state (any state is legal for overrides).
        actor: Who is doing this — must be a human identifier, not an agent.
        reason: Required explanation for why the override is needed.

    Returns:
        The updated RFQ.

    Raises:
        ValueError: If the RFQ doesn't exist or reason is empty.
    """
    if not reason or not reason.strip():
        raise ValueError("Override reason is required — explain why this override is needed")

    rfq = db.query(RFQ).filter(RFQ.id == rfq_id).first()
    if not rfq:
        raise ValueError(f"RFQ {rfq_id} not found")

    old_state = rfq.state
    rfq.state = new_state
    rfq.updated_at = datetime.utcnow()

    # Handle terminal state fields
    if new_state in (RFQState.WON, RFQState.LOST, RFQState.CANCELLED):
        rfq.outcome = new_state.value
        rfq.closed_at = datetime.utcnow()
    else:
        # If reopening from a terminal state, clear the outcome
        if old_state in (RFQState.WON, RFQState.LOST, RFQState.CANCELLED):
            rfq.outcome = None
            rfq.closed_at = None

    # Log with a distinct event type so overrides stand out in the timeline
    event = AuditEvent(
        rfq_id=rfq.id,
        event_type="state_override",
        actor=actor,
        description=f"Manual override: moved from {_state_label(old_state)} to {_state_label(new_state)} — {reason}",
        event_data={
            "old_state": old_state.value,
            "new_state": new_state.value,
            "reason": reason,
            "override": True,
        },
    )
    db.add(event)
    db.commit()
    db.refresh(rfq)

    logger.warning(
        "RFQ %d OVERRIDE: %s -> %s (actor=%s, reason=%s)",
        rfq_id, old_state.value, new_state.value, actor, reason,
    )

    return rfq


def get_allowed_transitions(current_state: RFQState) -> list[RFQState]:
    """
    Return the list of states an RFQ can legally move to from its current state.

    Always includes CANCELLED (unless already in a terminal state).
    Used by the UI to show which actions are available on an RFQ.

    Args:
        current_state: The RFQ's current state.

    Returns:
        List of RFQState values that are legal transitions.
    """
    allowed = list(TRANSITION_RULES.get(current_state, []))

    # CANCELLED is always reachable from non-terminal states
    if current_state not in (RFQState.WON, RFQState.LOST, RFQState.CANCELLED):
        if RFQState.CANCELLED not in allowed:
            allowed.append(RFQState.CANCELLED)

    return allowed


def get_transition_history(db: Session, rfq_id: int) -> list[AuditEvent]:
    """
    Return all state change events for an RFQ, ordered chronologically.

    This is how the RFQ detail timeline is populated (FR-DM-2 — full
    transition history). Includes both normal transitions and overrides.

    Args:
        db: SQLAlchemy session.
        rfq_id: The RFQ to get history for.

    Returns:
        List of AuditEvent rows with event_type in ("state_changed", "state_override").
    """
    return (
        db.query(AuditEvent)
        .filter(
            AuditEvent.rfq_id == rfq_id,
            AuditEvent.event_type.in_(["state_changed", "state_override"]),
        )
        .order_by(AuditEvent.created_at.asc())
        .all()
    )


def _is_transition_allowed(from_state: RFQState, to_state: RFQState) -> bool:
    """
    Check whether a state transition is legal per the rules.

    CANCELLED is always allowed from non-terminal states (a deal can fall
    through at any point). Other transitions must be explicitly listed in
    TRANSITION_RULES.
    """
    # CANCELLED is always reachable from non-terminal states
    if to_state == RFQState.CANCELLED:
        return from_state not in (RFQState.WON, RFQState.LOST, RFQState.CANCELLED)

    allowed = TRANSITION_RULES.get(from_state, [])
    return to_state in allowed


def _log_state_change(
    db: Session,
    rfq: RFQ,
    old_state: RFQState,
    new_state: RFQState,
    actor: str,
    reason: Optional[str],
) -> None:
    """
    Create an audit event for a state transition.

    Uses plain English descriptions per C3 so the broker sees something
    meaningful in the timeline, not raw state names.
    """
    description = f"Moved from {_state_label(old_state)} to {_state_label(new_state)}"
    if reason:
        description += f" — {reason}"

    event = AuditEvent(
        rfq_id=rfq.id,
        event_type="state_changed",
        actor=actor,
        description=description,
        event_data={
            "old_state": old_state.value,
            "new_state": new_state.value,
            "reason": reason,
        },
    )
    db.add(event)


def _state_label(state: RFQState) -> str:
    """
    Convert a state enum to a plain-English label for the UI (C3).

    The broker sees "Needs clarification" not "needs_clarification".
    """
    labels = {
        RFQState.NEEDS_CLARIFICATION: "Needs clarification",
        RFQState.READY_TO_QUOTE: "Ready to quote",
        RFQState.WAITING_ON_CARRIERS: "Waiting on carriers",
        RFQState.QUOTES_RECEIVED: "Quotes received",
        RFQState.WAITING_ON_BROKER: "Waiting on broker review",
        RFQState.QUOTE_SENT: "Quote sent",
        RFQState.WON: "Won",
        RFQState.LOST: "Lost",
        RFQState.CANCELLED: "Cancelled",
    }
    return labels.get(state, state.value)


class IllegalTransitionError(Exception):
    """
    Raised when code attempts a state transition that violates the rules.

    Includes the from/to states and the allowed transitions so the caller
    (or the broker in the UI) can understand what went wrong.
    """

    def __init__(
        self,
        rfq_id: int,
        from_state: RFQState,
        to_state: RFQState,
        allowed: list[RFQState],
    ):
        self.rfq_id = rfq_id
        self.from_state = from_state
        self.to_state = to_state
        self.allowed = allowed
        allowed_names = [s.value for s in allowed]
        super().__init__(
            f"Cannot transition RFQ {rfq_id} from {from_state.value} to {to_state.value}. "
            f"Allowed transitions: {allowed_names}"
        )
