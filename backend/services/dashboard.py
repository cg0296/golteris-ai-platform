"""
backend/services/dashboard.py — Service functions for the broker home dashboard (#17).

Aggregates data from multiple tables to power the four dashboard zones:
1. KPI summary strip (needs_review, active_rfqs, quotes_received, time_saved)
2. Active RFQs table (non-terminal RFQs sorted by most recently updated)
3. Pending approvals list (HITL queue for urgent actions panel)
4. Recent activity feed (audit events in reverse chronological order)

All queries are pure SQLAlchemy — no HTTP concerns. The API router
(backend/api/dashboard.py) calls these and serializes the results.

Cross-cutting constraints:
    C2 — Approval counts feed the "Needs Review" KPI so the broker sees what's pending
    C3 — State labels are resolved by the API layer using _state_label(), not here
    C5 — Time saved calculation uses actual agent_run duration (defensible metric)

Called by:
    backend/api/dashboard.py
"""

import logging
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import func
from sqlalchemy.orm import Session, joinedload

from backend.db.models import (
    AgentRun,
    AgentRunStatus,
    Approval,
    ApprovalStatus,
    AuditEvent,
    CarrierBid,
    RFQ,
    RFQState,
    ReviewQueue,
    ReviewQueueStatus,
)

logger = logging.getLogger("golteris.services.dashboard")

# Terminal states — RFQs in these states are no longer "active"
TERMINAL_STATES = {RFQState.WON, RFQState.LOST, RFQState.CANCELLED}


def get_kpi_summary(db: Session) -> dict:
    """
    Return all four KPI counts for the dashboard summary strip.

    Returns:
        dict with keys:
            needs_review (int): Pending approvals + pending review queue items
            active_rfqs (int): RFQs not in terminal states (won/lost/cancelled)
            quotes_received_today (int): Carrier bids received since midnight UTC
            time_saved_minutes (float): Sum of completed agent run durations today,
                converted to minutes. This is defensible because it measures actual
                automation wall-clock time the broker didn't spend manually.

    Cross-cutting: C5 — time_saved uses real duration_ms from agent_runs, not fabricated.
    """
    # Pending approvals waiting for broker action (C2 enforcement visibility)
    pending_approvals = (
        db.query(func.count(Approval.id))
        .filter(Approval.status == ApprovalStatus.PENDING_APPROVAL)
        .scalar()
    ) or 0

    # Pending review queue items (ambiguous message matches needing human triage)
    pending_reviews = (
        db.query(func.count(ReviewQueue.id))
        .filter(ReviewQueue.status == ReviewQueueStatus.PENDING)
        .scalar()
    ) or 0

    needs_review = pending_approvals + pending_reviews

    # Active RFQs — everything that isn't in a terminal state
    active_rfqs = (
        db.query(func.count(RFQ.id))
        .filter(RFQ.state.notin_(TERMINAL_STATES))
        .scalar()
    ) or 0

    # Carrier bids received today (UTC midnight boundary)
    today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    quotes_received_today = (
        db.query(func.count(CarrierBid.id))
        .filter(CarrierBid.received_at >= today_start)
        .scalar()
    ) or 0

    # Time saved: sum of completed agent run durations today, in minutes.
    # This measures how much wall-clock processing time the AI agents spent
    # on tasks that would otherwise require manual broker work.
    total_duration_ms = (
        db.query(func.coalesce(func.sum(AgentRun.duration_ms), 0))
        .filter(
            AgentRun.status == AgentRunStatus.COMPLETED,
            AgentRun.finished_at >= today_start,
        )
        .scalar()
    ) or 0
    time_saved_minutes = round(total_duration_ms / 60000, 1)

    return {
        "needs_review": needs_review,
        "active_rfqs": active_rfqs,
        "quotes_received_today": quotes_received_today,
        "time_saved_minutes": time_saved_minutes,
    }


def list_active_rfqs(
    db: Session,
    limit: int = 6,
    offset: int = 0,
) -> tuple[list[RFQ], int]:
    """
    Return non-terminal RFQs sorted by most recently updated, plus total count.

    Used by the Active RFQs table on the dashboard (6-row preview).
    The "View all" link navigates to the full RFQs page.

    Args:
        db: Database session
        limit: Max rows to return (default 6 for dashboard preview)
        offset: Pagination offset

    Returns:
        Tuple of (rfq_list, total_count)
    """
    base_query = db.query(RFQ).filter(RFQ.state.notin_(TERMINAL_STATES))

    total = base_query.count()
    rfqs = (
        base_query
        .order_by(RFQ.updated_at.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )
    return rfqs, total


def list_pending_approvals(
    db: Session,
    limit: int = 10,
) -> tuple[list[Approval], int]:
    """
    Return pending approvals with their related RFQs, for the Urgent Actions panel.

    Eager-loads the RFQ relationship so the API can include customer name and
    route info without N+1 queries.

    Args:
        db: Database session
        limit: Max approvals to return

    Returns:
        Tuple of (approval_list, total_count)
    """
    base_query = db.query(Approval).filter(
        Approval.status == ApprovalStatus.PENDING_APPROVAL
    )

    total = base_query.count()
    approvals = (
        base_query
        .options(joinedload(Approval.rfq))
        .order_by(Approval.created_at.desc())
        .limit(limit)
        .all()
    )
    return approvals, total


def list_recent_activity(
    db: Session,
    limit: int = 20,
) -> list[AuditEvent]:
    """
    Return the most recent audit events for the activity feed.

    Events are ordered newest-first. The description field is already in
    operator language (C3) — set by the services that create events
    (rfq_state_machine, escalation_policy, etc.).

    Args:
        db: Database session
        limit: Max events to return

    Returns:
        List of AuditEvent objects
    """
    return (
        db.query(AuditEvent)
        .order_by(AuditEvent.created_at.desc())
        .limit(limit)
        .all()
    )


def approve_approval(
    db: Session,
    approval_id: int,
    resolved_by: str = "broker",
    resolved_body: Optional[str] = None,
) -> Optional[Approval]:
    """
    Approve a pending approval and create an audit event.

    This is the C2 enforcement point — flipping status from pending_approval
    to approved is what gates outbound email sends. The outbound send job
    checks approvals.status == APPROVED before sending.

    Args:
        approval_id: ID of the approval to approve
        resolved_by: Who approved (e.g., "broker", "jillian@beltmann.com")
        resolved_body: If the broker edited the draft, the new body. None = send as-is.

    Returns:
        Updated Approval object, or None if not found / not pending.
    """
    approval = db.query(Approval).filter(Approval.id == approval_id).first()
    if not approval:
        return None
    if approval.status != ApprovalStatus.PENDING_APPROVAL:
        return None

    approval.status = ApprovalStatus.APPROVED
    approval.resolved_by = resolved_by
    approval.resolved_at = datetime.now(timezone.utc)
    if resolved_body is not None:
        approval.resolved_body = resolved_body

    # Create an audit event for this approval (C4 — visible reasoning)
    event = AuditEvent(
        rfq_id=approval.rfq_id,
        event_type="approval_approved",
        actor=resolved_by,
        description=f"Approved {approval.approval_type.value.replace('_', ' ')} draft",
        event_data={
            "approval_id": approval.id,
            "approval_type": approval.approval_type.value,
        },
    )
    db.add(event)
    db.commit()
    db.refresh(approval)
    return approval
