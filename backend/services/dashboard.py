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
from datetime import datetime, timedelta, timezone
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
    Message,
    MessageRoutingStatus,
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
    state_filter: Optional[str] = None,
    search: Optional[str] = None,
    include_terminal: bool = False,
) -> tuple[list[RFQ], int]:
    """
    Return RFQs sorted by most recently updated, plus total count.

    Used by both the dashboard preview (limit=6, active only) and the
    full RFQs list page (#29) with state filter, search, and pagination.

    Args:
        db: Database session
        limit: Max rows to return (default 6 for dashboard preview)
        offset: Pagination offset
        state_filter: Optional state value to filter by (e.g., "ready_to_quote")
        search: Optional search string — matches customer_name, origin, destination
        include_terminal: If True, include won/lost/cancelled RFQs

    Returns:
        Tuple of (rfq_list, total_count)
    """
    base_query = db.query(RFQ)

    # By default exclude terminal states (dashboard behavior)
    if not include_terminal:
        base_query = base_query.filter(RFQ.state.notin_(TERMINAL_STATES))

    # State filter — narrow to a specific state
    if state_filter:
        try:
            state_enum = RFQState(state_filter)
            base_query = base_query.filter(RFQ.state == state_enum)
        except ValueError:
            pass  # Invalid state value — ignore filter

    # Search — match against customer name, origin, destination
    if search:
        search_term = f"%{search}%"
        base_query = base_query.filter(
            (RFQ.customer_name.ilike(search_term))
            | (RFQ.origin.ilike(search_term))
            | (RFQ.destination.ilike(search_term))
            | (RFQ.customer_company.ilike(search_term))
        )

    total = base_query.count()
    rfqs = (
        base_query
        .order_by(RFQ.updated_at.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )
    return rfqs, total


def count_rfqs_by_state(db: Session) -> dict[str, int]:
    """
    Return a count of RFQs grouped by state, for the filter pill badges.

    Used by the RFQs list page (#29) to show how many RFQs are in each state.
    """
    rows = (
        db.query(RFQ.state, func.count(RFQ.id))
        .group_by(RFQ.state)
        .all()
    )
    return {state.value: count for state, count in rows}


def list_messages(
    db: Session,
    limit: int = 50,
    offset: int = 0,
    routing_status: Optional[str] = None,
    search: Optional[str] = None,
) -> tuple[list[Message], int]:
    """
    Return messages sorted by most recently received, with optional filters.

    Used by the Inbox view (#28) to show every inbound message and how
    Golteris routed it (attached, new_rfq, needs_review, ignored).

    Args:
        db: Database session
        limit: Max rows to return
        offset: Pagination offset
        routing_status: Filter by routing status (e.g., "attached", "needs_review")
        search: Search sender or subject (case-insensitive)

    Returns:
        Tuple of (message_list, total_count)
    """
    base_query = db.query(Message)

    if routing_status:
        try:
            status_enum = MessageRoutingStatus(routing_status)
            base_query = base_query.filter(Message.routing_status == status_enum)
        except ValueError:
            pass

    if search:
        search_term = f"%{search}%"
        base_query = base_query.filter(
            (Message.sender.ilike(search_term))
            | (Message.subject.ilike(search_term))
        )

    total = base_query.count()
    messages = (
        base_query
        .options(joinedload(Message.rfq))
        .order_by(Message.received_at.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )
    return messages, total


def count_messages_by_routing(db: Session) -> dict[str, int]:
    """
    Return message counts grouped by routing_status, for filter pill badges.

    Used by the Inbox view (#28) to show how many messages are in each
    routing category.
    """
    rows = (
        db.query(Message.routing_status, func.count(Message.id))
        .filter(Message.routing_status.isnot(None))
        .group_by(Message.routing_status)
        .all()
    )
    return {status.value: count for status, count in rows}


def get_history_stats(db: Session) -> dict:
    """
    Return the four stat strip values for the History view (#30).

    Stats:
        completed_today (int): RFQs that reached a terminal state today
        avg_time_to_quote_hours (float): Average hours from RFQ creation to quote_sent
        approvals_this_week (int): Approvals resolved in the last 7 days
        time_saved_hours (float): Total agent run duration this week, in hours

    C5 — time_saved uses real agent_run duration_ms (defensible metric).
    """
    today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    week_start = today_start - timedelta(days=today_start.weekday())

    # Completed today — RFQs closed today
    completed_today = (
        db.query(func.count(RFQ.id))
        .filter(
            RFQ.state.in_(TERMINAL_STATES),
            RFQ.closed_at >= today_start,
        )
        .scalar()
    ) or 0

    # Avg time to quote — average hours from creation to closed_at for quote_sent/won/lost
    from sqlalchemy import extract
    avg_query = (
        db.query(
            func.avg(
                func.extract("epoch", RFQ.closed_at) - func.extract("epoch", RFQ.created_at)
            )
        )
        .filter(
            RFQ.closed_at.isnot(None),
            RFQ.state.in_([RFQState.WON, RFQState.LOST, RFQState.QUOTE_SENT]),
        )
        .scalar()
    )
    avg_time_to_quote_hours = round((avg_query or 0) / 3600, 1)

    # Approvals this week
    approvals_this_week = (
        db.query(func.count(Approval.id))
        .filter(
            Approval.resolved_at >= week_start,
            Approval.status.in_([ApprovalStatus.APPROVED, ApprovalStatus.REJECTED]),
        )
        .scalar()
    ) or 0

    # Time saved this week (hours) — sum of completed agent run durations
    total_duration_ms = (
        db.query(func.coalesce(func.sum(AgentRun.duration_ms), 0))
        .filter(
            AgentRun.status == AgentRunStatus.COMPLETED,
            AgentRun.finished_at >= week_start,
        )
        .scalar()
    ) or 0
    time_saved_hours = round(total_duration_ms / 3600000, 1)

    return {
        "completed_today": completed_today,
        "avg_time_to_quote_hours": avg_time_to_quote_hours,
        "approvals_this_week": approvals_this_week,
        "time_saved_hours": time_saved_hours,
    }


def list_closed_rfqs(
    db: Session,
    limit: int = 50,
    offset: int = 0,
    outcome_filter: Optional[str] = None,
    period: Optional[str] = None,
) -> tuple[list[RFQ], int]:
    """
    Return closed RFQs (won/lost/cancelled) for the History view (#30).

    Args:
        db: Database session
        limit: Max rows
        offset: Pagination offset
        outcome_filter: Filter by outcome state (won/lost/cancelled)
        period: Time range filter (today/week/month)

    Returns:
        Tuple of (rfq_list, total_count)
    """
    base_query = db.query(RFQ).filter(RFQ.state.in_(TERMINAL_STATES))

    if outcome_filter:
        try:
            state_enum = RFQState(outcome_filter)
            base_query = base_query.filter(RFQ.state == state_enum)
        except ValueError:
            pass

    if period:
        now = datetime.utcnow()
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        if period == "today":
            base_query = base_query.filter(RFQ.closed_at >= today_start)
        elif period == "week":
            week_start = today_start - timedelta(days=today_start.weekday())
            base_query = base_query.filter(RFQ.closed_at >= week_start)
        elif period == "month":
            month_start = today_start.replace(day=1)
            base_query = base_query.filter(RFQ.closed_at >= month_start)

    total = base_query.count()
    rfqs = (
        base_query
        .order_by(RFQ.closed_at.desc())
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


def get_approval_detail(db: Session, approval_id: int) -> Optional[Approval]:
    """
    Return a single approval with its related RFQ, for the approval modal.

    The modal needs the full draft_body, draft_subject, reason, and RFQ
    context (customer name, route) to display the "SHIPPER WROTE" and
    "AGENT DRAFTED" sections.

    Args:
        approval_id: ID of the approval to fetch

    Returns:
        Approval object with eager-loaded RFQ, or None if not found.
    """
    return (
        db.query(Approval)
        .options(joinedload(Approval.rfq))
        .filter(Approval.id == approval_id)
        .first()
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


def reject_approval(
    db: Session,
    approval_id: int,
    resolved_by: str = "broker",
) -> Optional[Approval]:
    """
    Reject a pending approval — the draft will NOT be sent.

    C2 enforcement: rejecting is a deliberate human action that prevents
    outbound communication. The broker chose not to send this draft.

    Args:
        approval_id: ID of the approval to reject
        resolved_by: Who rejected

    Returns:
        Updated Approval object, or None if not found / not pending.
    """
    approval = db.query(Approval).filter(Approval.id == approval_id).first()
    if not approval:
        return None
    if approval.status != ApprovalStatus.PENDING_APPROVAL:
        return None

    approval.status = ApprovalStatus.REJECTED
    approval.resolved_by = resolved_by
    approval.resolved_at = datetime.now(timezone.utc)

    event = AuditEvent(
        rfq_id=approval.rfq_id,
        event_type="approval_rejected",
        actor=resolved_by,
        description=f"Rejected {approval.approval_type.value.replace('_', ' ')} draft",
        event_data={
            "approval_id": approval.id,
            "approval_type": approval.approval_type.value,
        },
    )
    db.add(event)
    db.commit()
    db.refresh(approval)
    return approval


def skip_approval(
    db: Session,
    approval_id: int,
    resolved_by: str = "broker",
) -> Optional[Approval]:
    """
    Skip a pending approval — it stays in the queue for later review.

    The broker wants to come back to this one. The approval remains
    visible but moves to 'skipped' status. It can be re-opened later.

    Args:
        approval_id: ID of the approval to skip
        resolved_by: Who skipped

    Returns:
        Updated Approval object, or None if not found / not pending.
    """
    approval = db.query(Approval).filter(Approval.id == approval_id).first()
    if not approval:
        return None
    if approval.status != ApprovalStatus.PENDING_APPROVAL:
        return None

    approval.status = ApprovalStatus.SKIPPED
    approval.resolved_by = resolved_by
    approval.resolved_at = datetime.now(timezone.utc)

    event = AuditEvent(
        rfq_id=approval.rfq_id,
        event_type="approval_skipped",
        actor=resolved_by,
        description=f"Skipped {approval.approval_type.value.replace('_', ' ')} draft",
        event_data={
            "approval_id": approval.id,
            "approval_type": approval.approval_type.value,
        },
    )
    db.add(event)
    db.commit()
    db.refresh(approval)
    return approval
