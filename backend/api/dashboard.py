"""
backend/api/dashboard.py — FastAPI router for the broker dashboard and RFQ views.

Provides the REST API endpoints that power the dashboard and RFQ detail:
    GET /api/dashboard/summary      — KPI counts (needs_review, active_rfqs, etc.)
    GET /api/rfqs                   — Paginated RFQ list (active by default)
    GET /api/rfqs/{id}              — Full RFQ detail for the drawer (#27)
    GET /api/approvals              — Paginated approval list (pending by default)
    GET /api/activity/recent        — Recent audit events for the activity feed

Cross-cutting constraints:
    C2 — Approval list shows what's waiting for broker action (HITL visibility)
    C3 — State labels use plain English via _state_label() from rfq_state_machine
    C5 — Time saved KPI uses defensible duration_ms from completed agent runs

Called by:
    The React frontend via React Query polling (~10s interval).
"""

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session, joinedload

from backend.db.database import get_db
from backend.db.models import (
    Approval,
    AuditEvent,
    CarrierBid,
    Message,
    RFQ,
)
from backend.services.dashboard import (
    get_kpi_summary,
    list_active_rfqs,
    list_pending_approvals,
    list_recent_activity,
)
from backend.services.rfq_state_machine import (
    _state_label,
    get_allowed_transitions,
)

logger = logging.getLogger("golteris.api.dashboard")

router = APIRouter(tags=["dashboard"])


@router.get("/api/dashboard/summary")
def dashboard_summary(db: Session = Depends(get_db)):
    """
    Return the four KPI counts for the dashboard summary strip.

    All counts are computed in a single request so the four KPI cards
    load simultaneously (no visual stagger from separate requests).
    The frontend polls this every 10 seconds via React Query.
    """
    return get_kpi_summary(db)


@router.get("/api/rfqs")
def get_rfqs(
    limit: int = Query(6, ge=1, le=200, description="Page size"),
    offset: int = Query(0, ge=0, description="Pagination offset"),
    state: Optional[str] = Query(None, description="Filter by state (e.g., ready_to_quote)"),
    search: Optional[str] = Query(None, description="Search customer, origin, destination"),
    include_terminal: bool = Query(False, description="Include won/lost/cancelled RFQs"),
    db: Session = Depends(get_db),
):
    """
    List RFQs sorted by most recently updated, with optional filters.

    Default limit=6 matches the dashboard preview. The full RFQs page (#29)
    uses higher limits with state filters and search for 500+ RFQ scale.

    Each RFQ includes a state_label field with the plain-English state name
    for display (C3 — "Waiting on carriers" not "waiting_on_carriers").
    """
    rfqs, total = list_active_rfqs(
        db, limit=limit, offset=offset,
        state_filter=state, search=search,
        include_terminal=include_terminal,
    )
    return {
        "rfqs": [_serialize_rfq(r) for r in rfqs],
        "total": total,
        "limit": limit,
        "offset": offset,
    }


@router.get("/api/rfqs/counts")
def get_rfq_counts(db: Session = Depends(get_db)):
    """
    Return RFQ counts grouped by state, for the filter pill badges (#29).

    Used by the RFQs list page to show how many RFQs are in each state
    without fetching all rows.
    """
    from backend.services.dashboard import count_rfqs_by_state
    counts = count_rfqs_by_state(db)
    return {"counts": counts}


@router.get("/api/rfqs/{rfq_id}")
def get_rfq_detail(
    rfq_id: int,
    db: Session = Depends(get_db),
):
    """
    Get full RFQ detail for the RFQ detail drawer (#27).

    Returns four sections matching FR-UI-5:
    1. Summary — all extracted fields (customer, route, equipment, dates)
    2. Current Status — state label, allowed transitions, confidence scores
    3. Messages — full inbound/outbound thread sorted chronologically
    4. Actions & History — audit events as a timeline

    Also includes carrier bids and pending approvals for the drawer.

    Cross-cutting constraints:
        C3 — State labels use plain English via _state_label()
        C4 — Timeline shows every action; system reasoning available via agent_calls
    """
    rfq = (
        db.query(RFQ)
        .options(
            joinedload(RFQ.messages),
            joinedload(RFQ.audit_events),
            joinedload(RFQ.carrier_bids),
            joinedload(RFQ.approvals),
        )
        .filter(RFQ.id == rfq_id)
        .first()
    )
    if not rfq:
        raise HTTPException(status_code=404, detail=f"RFQ {rfq_id} not found")

    # Allowed next states for the "Next steps" section in the drawer
    allowed = get_allowed_transitions(rfq.state)

    return {
        # Summary section
        **_serialize_rfq_full(rfq),
        # Current status with transitions
        "allowed_transitions": [
            {"state": s.value, "label": _state_label(s)} for s in allowed
        ],
        # Messages thread sorted chronologically
        "messages": [
            _serialize_message(m)
            for m in sorted(rfq.messages, key=lambda m: m.received_at or m.created_at)
        ],
        # Actions & History timeline (newest first)
        "timeline": [
            _serialize_event(e)
            for e in sorted(rfq.audit_events, key=lambda e: e.created_at, reverse=True)
        ],
        # Carrier bids
        "carrier_bids": [
            _serialize_bid(b)
            for b in sorted(rfq.carrier_bids, key=lambda b: b.received_at, reverse=True)
        ],
        # Pending approvals
        "pending_approvals": [
            _serialize_approval(a)
            for a in rfq.approvals
            if a.status.value == "pending_approval"
        ],
    }


@router.get("/api/history")
def get_history(
    limit: int = Query(50, ge=1, le=200, description="Page size"),
    offset: int = Query(0, ge=0, description="Pagination offset"),
    outcome: Optional[str] = Query(None, description="Filter by outcome: won, lost, cancelled"),
    period: Optional[str] = Query(None, description="Time filter: today, week, month"),
    db: Session = Depends(get_db),
):
    """
    Return closed RFQs with stats for the History view (#30).

    The stat strip shows aggregated performance metrics. The table shows
    individual closed RFQs with outcome, quoted amount, and cycle time.
    Historical entries are immutable per FR-DM-5.
    """
    from backend.services.dashboard import get_history_stats, list_closed_rfqs

    stats = get_history_stats(db)
    rfqs, total = list_closed_rfqs(
        db, limit=limit, offset=offset,
        outcome_filter=outcome, period=period,
    )

    return {
        "stats": stats,
        "rfqs": [_serialize_history_rfq(r) for r in rfqs],
        "total": total,
        "limit": limit,
        "offset": offset,
    }


@router.get("/api/messages")
def get_messages(
    limit: int = Query(50, ge=1, le=200, description="Page size"),
    offset: int = Query(0, ge=0, description="Pagination offset"),
    routing_status: Optional[str] = Query(None, description="Filter by routing status"),
    search: Optional[str] = Query(None, description="Search sender or subject"),
    db: Session = Depends(get_db),
):
    """
    List messages sorted by most recently received, with optional filters.

    Used by the Inbox view (#28) to show every inbound message and how
    Golteris routed it. Each message includes a routing badge and a link
    to the attached RFQ (if any).
    """
    from backend.services.dashboard import list_messages
    messages, total = list_messages(
        db, limit=limit, offset=offset,
        routing_status=routing_status, search=search,
    )
    return {
        "messages": [_serialize_inbox_message(m) for m in messages],
        "total": total,
        "limit": limit,
        "offset": offset,
    }


@router.get("/api/messages/counts")
def get_message_counts(db: Session = Depends(get_db)):
    """
    Return message counts grouped by routing_status, for filter pill badges (#28).
    """
    from backend.services.dashboard import count_messages_by_routing
    counts = count_messages_by_routing(db)
    return {"counts": counts}


@router.get("/api/messages/{message_id}/thread")
def get_message_thread(message_id: int, db: Session = Depends(get_db)):
    """
    Return a single message and its full thread (#111).

    The thread is all messages sharing the same rfq_id, sorted chronologically.
    If the message has no rfq_id, only the clicked message is returned.
    Used by the Inbox email thread viewer modal.
    """
    msg = db.query(Message).filter(Message.id == message_id).first()
    if not msg:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Message not found")

    # Build the thread: all messages on the same RFQ, sorted oldest-first
    if msg.rfq_id:
        thread = (
            db.query(Message)
            .filter(Message.rfq_id == msg.rfq_id)
            .order_by(Message.received_at.asc())
            .all()
        )
    else:
        thread = [msg]

    rfq = msg.rfq
    return {
        "message": _serialize_inbox_message(msg),
        "thread": [_serialize_inbox_message(m) for m in thread],
        "rfq": {
            "id": rfq.id,
            "customer_name": rfq.customer_name,
            "customer_company": rfq.customer_company,
            "state_label": _state_label(rfq.state) if rfq.state else None,
            "origin": rfq.origin,
            "destination": rfq.destination,
        } if rfq else None,
    }


@router.get("/api/approvals")
def get_approvals(
    status: Optional[str] = Query("pending_approval", description="Filter by status"),
    limit: int = Query(10, ge=1, le=100, description="Page size"),
    db: Session = Depends(get_db),
):
    """
    List approvals, defaulting to pending ones for the Urgent Actions panel.

    Each approval includes nested RFQ context (customer name, route) so the
    dashboard can show what the approval relates to without a second request.
    """
    approvals, total = list_pending_approvals(db, limit=limit)
    return {
        "approvals": [_serialize_approval(a) for a in approvals],
        "total": total,
    }


@router.get("/api/customers")
def get_customers(db: Session = Depends(get_db)):
    """
    List unique customers derived from RFQ data (#138).

    Groups RFQs by customer_email to build a customer list with
    RFQ counts, last activity, and state breakdown.
    """
    from sqlalchemy import func, case

    results = (
        db.query(
            RFQ.customer_email,
            RFQ.customer_name,
            RFQ.customer_company,
            func.count(RFQ.id).label("rfq_count"),
            func.max(RFQ.created_at).label("last_rfq_at"),
        )
        .filter(RFQ.customer_email.isnot(None))
        .group_by(RFQ.customer_email, RFQ.customer_name, RFQ.customer_company)
        .order_by(func.max(RFQ.created_at).desc())
        .all()
    )

    customers = []
    for row in results:
        # Get state counts for this customer
        state_counts = (
            db.query(RFQ.state, func.count(RFQ.id))
            .filter(RFQ.customer_email == row.customer_email)
            .group_by(RFQ.state)
            .all()
        )
        customers.append({
            "customer_name": row.customer_name,
            "customer_email": row.customer_email,
            "customer_company": row.customer_company,
            "rfq_count": row.rfq_count,
            "last_rfq_at": row.last_rfq_at.isoformat() if row.last_rfq_at else None,
            "states": {s.value: c for s, c in state_counts},
        })

    return {"customers": customers, "total": len(customers)}


@router.post("/api/rfqs/{rfq_id}/request-clarification")
def request_clarification(rfq_id: int, db: Session = Depends(get_db)):
    """
    Manually trigger a clarification follow-up for an RFQ (#156).

    Enqueues a validation job that drafts a follow-up email asking the
    customer for missing or unclear information. Works from any active state.
    """
    from backend.db.models import AuditEvent, RFQ, RFQState
    from backend.worker import enqueue_job

    rfq = db.query(RFQ).filter(RFQ.id == rfq_id).first()
    if not rfq:
        raise HTTPException(status_code=404, detail=f"RFQ {rfq_id} not found")

    if rfq.state in (RFQState.WON, RFQState.LOST, RFQState.CANCELLED):
        raise HTTPException(status_code=400, detail="Cannot request clarification on a closed RFQ")

    # Temporarily set to needs_clarification so validation agent will draft
    original_state = rfq.state
    if rfq.state != RFQState.NEEDS_CLARIFICATION:
        rfq.state = RFQState.NEEDS_CLARIFICATION
        db.commit()

    enqueue_job(db, "validation", {"rfq_id": rfq_id}, rfq_id=rfq_id)

    db.add(AuditEvent(
        rfq_id=rfq_id,
        event_type="clarification_requested",
        actor="broker",
        description="Broker manually requested clarification follow-up",
    ))
    db.commit()

    return {"status": "ok", "rfq_id": rfq_id, "message": "Clarification follow-up enqueued"}


@router.get("/api/activity/recent")
def get_recent_activity(
    limit: int = Query(20, ge=1, le=100, description="Max events to return"),
    db: Session = Depends(get_db),
):
    """
    Return recent audit events for the activity feed.

    Events are ordered newest-first. The description field is already in
    operator language (C3) — set by the service that created the event.
    The event_type field is machine-readable for the frontend to pick icons.
    """
    events = list_recent_activity(db, limit=limit)
    return {
        "events": [_serialize_event(e) for e in events],
    }


# ---------------------------------------------------------------------------
# Serialization helpers — convert ORM objects to JSON-serializable dicts.
# Same pattern as backend/api/agent_runs.py. Field names use plain English
# where possible (C3).
# ---------------------------------------------------------------------------


def _serialize_rfq(rfq: RFQ) -> dict:
    """
    Convert an RFQ ORM object to a JSON dict for the dashboard table.

    Includes state_label (plain English) alongside state (machine-readable)
    so the frontend doesn't need its own label mapping (C3 compliance).
    """
    return {
        "id": rfq.id,
        "customer_name": rfq.customer_name,
        "customer_company": rfq.customer_company,
        "origin": rfq.origin,
        "destination": rfq.destination,
        "equipment_type": rfq.equipment_type,
        "truck_count": rfq.truck_count,
        "state": rfq.state.value if rfq.state else None,
        "state_label": _state_label(rfq.state) if rfq.state else None,
        "updated_at": rfq.updated_at.isoformat() if rfq.updated_at else None,
        "created_at": rfq.created_at.isoformat() if rfq.created_at else None,
    }


def _serialize_approval(approval: Approval) -> dict:
    """
    Convert an Approval ORM object to a JSON dict for the Urgent Actions panel.

    Includes nested RFQ context so the dashboard can show what the approval
    relates to (customer name, route) without a second API call.
    """
    rfq = approval.rfq
    return {
        "id": approval.id,
        "rfq_id": approval.rfq_id,
        "approval_type": approval.approval_type.value if approval.approval_type else None,
        "draft_subject": approval.draft_subject,
        "draft_body": approval.draft_body,
        "draft_recipient": approval.draft_recipient,
        "reason": approval.reason,
        "status": approval.status.value if approval.status else None,
        "created_at": approval.created_at.isoformat() if approval.created_at else None,
        "rfq": {
            "id": rfq.id,
            "customer_name": rfq.customer_name,
            "origin": rfq.origin,
            "destination": rfq.destination,
        } if rfq else None,
    }


def _serialize_event(event: AuditEvent) -> dict:
    """
    Convert an AuditEvent ORM object to a JSON dict for the activity feed.

    The description is already in operator language (C3) — it was written
    that way by the service that created the event (rfq_state_machine,
    escalation_policy, etc.).
    """
    return {
        "id": event.id,
        "rfq_id": event.rfq_id,
        "event_type": event.event_type,
        "actor": event.actor,
        "description": event.description,
        "created_at": event.created_at.isoformat() if event.created_at else None,
    }


def _serialize_rfq_full(rfq: RFQ) -> dict:
    """
    Convert an RFQ to a full JSON dict for the detail drawer (#27).

    Includes all extracted fields (not just the summary subset used in the
    dashboard table). The drawer's Summary section shows these fields as
    a definition list.
    """
    return {
        "id": rfq.id,
        "customer_name": rfq.customer_name,
        "customer_email": rfq.customer_email,
        "customer_company": rfq.customer_company,
        "origin": rfq.origin,
        "destination": rfq.destination,
        "equipment_type": rfq.equipment_type,
        "truck_count": rfq.truck_count,
        "commodity": rfq.commodity,
        "weight_lbs": rfq.weight_lbs,
        "pickup_date": rfq.pickup_date.isoformat() if rfq.pickup_date else None,
        "delivery_date": rfq.delivery_date.isoformat() if rfq.delivery_date else None,
        "special_requirements": rfq.special_requirements,
        "state": rfq.state.value if rfq.state else None,
        "state_label": _state_label(rfq.state) if rfq.state else None,
        "confidence_scores": rfq.confidence_scores,
        "outcome": rfq.outcome,
        "quoted_amount": float(rfq.quoted_amount) if rfq.quoted_amount else None,
        "closed_at": rfq.closed_at.isoformat() if rfq.closed_at else None,
        "updated_at": rfq.updated_at.isoformat() if rfq.updated_at else None,
        "created_at": rfq.created_at.isoformat() if rfq.created_at else None,
    }


def _serialize_message(msg: Message) -> dict:
    """
    Convert a Message to a JSON dict for the detail drawer's Messages section.

    Direction is included so the frontend can style inbound vs outbound
    messages differently (IN tag vs OUT tag per the proof-of-concept).
    """
    return {
        "id": msg.id,
        "direction": msg.direction.value if msg.direction else None,
        "sender": msg.sender,
        "recipients": msg.recipients,
        "subject": msg.subject,
        "body": msg.body,
        "received_at": msg.received_at.isoformat() if msg.received_at else None,
    }


def _serialize_bid(bid: CarrierBid) -> dict:
    """
    Convert a CarrierBid to a JSON dict for the detail drawer.

    Shows carrier name, rate, and terms so the broker can compare bids
    directly in the RFQ context.
    """
    return {
        "id": bid.id,
        "carrier_name": bid.carrier_name,
        "carrier_email": bid.carrier_email,
        "rate": float(bid.rate) if bid.rate else None,
        "currency": bid.currency,
        "rate_type": bid.rate_type,
        "terms": bid.terms,
        "availability": bid.availability,
        "notes": bid.notes,
        "received_at": bid.received_at.isoformat() if bid.received_at else None,
    }


def _serialize_history_rfq(rfq: RFQ) -> dict:
    """
    Convert a closed RFQ to a JSON dict for the History table (#30).

    Includes outcome, quoted amount, and cycle time (hours from creation
    to close) so the broker can see performance at a glance.
    """
    cycle_hours = None
    if rfq.closed_at and rfq.created_at:
        delta = (rfq.closed_at - rfq.created_at).total_seconds() / 3600
        cycle_hours = round(delta, 1)

    return {
        "id": rfq.id,
        "customer_name": rfq.customer_name,
        "customer_company": rfq.customer_company,
        "origin": rfq.origin,
        "destination": rfq.destination,
        "equipment_type": rfq.equipment_type,
        "state": rfq.state.value if rfq.state else None,
        "state_label": _state_label(rfq.state) if rfq.state else None,
        "outcome": rfq.outcome,
        "quoted_amount": float(rfq.quoted_amount) if rfq.quoted_amount else None,
        "cycle_hours": cycle_hours,
        "closed_at": rfq.closed_at.isoformat() if rfq.closed_at else None,
        "created_at": rfq.created_at.isoformat() if rfq.created_at else None,
    }


def _serialize_inbox_message(msg: Message) -> dict:
    """
    Convert a Message to a JSON dict for the Inbox view (#28).

    Includes routing_status badge and attached RFQ context (customer name)
    so the broker can see at a glance how each message was handled.
    """
    rfq = msg.rfq
    # Plain-English routing labels (C3)
    routing_labels = {
        "attached": "Attached to RFQ",
        "new_rfq": "New RFQ created",
        "needs_review": "Needs review",
        "ignored": "Ignored",
    }
    routing_value = msg.routing_status.value if msg.routing_status else None
    return {
        "id": msg.id,
        "rfq_id": msg.rfq_id,
        "direction": msg.direction.value if msg.direction else None,
        "sender": msg.sender,
        "subject": msg.subject,
        "body": msg.body,
        "routing_status": routing_value,
        "routing_label": routing_labels.get(routing_value, routing_value),
        "received_at": msg.received_at.isoformat() if msg.received_at else None,
        "rfq": {
            "id": rfq.id,
            "customer_name": rfq.customer_name,
            "state_label": _state_label(rfq.state) if rfq.state else None,
        } if rfq else None,
    }
