"""
backend/api/dashboard.py — FastAPI router for the broker home dashboard (#17).

Provides the REST API endpoints that power the four dashboard zones:
    GET /api/dashboard/summary      — KPI counts (needs_review, active_rfqs, etc.)
    GET /api/rfqs                   — Paginated RFQ list (active by default)
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

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from backend.db.database import get_db
from backend.db.models import Approval, AuditEvent, RFQ
from backend.services.dashboard import (
    get_kpi_summary,
    list_active_rfqs,
    list_pending_approvals,
    list_recent_activity,
)
from backend.services.rfq_state_machine import _state_label

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
    db: Session = Depends(get_db),
):
    """
    List active RFQs sorted by most recently updated.

    Default limit=6 matches the dashboard preview table. The "View all"
    link on the dashboard passes a higher limit for the full RFQs page.

    Each RFQ includes a state_label field with the plain-English state name
    for display (C3 — "Waiting on carriers" not "waiting_on_carriers").
    """
    rfqs, total = list_active_rfqs(db, limit=limit, offset=offset)
    return {
        "rfqs": [_serialize_rfq(r) for r in rfqs],
        "total": total,
        "limit": limit,
        "offset": offset,
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
