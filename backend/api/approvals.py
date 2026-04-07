"""
backend/api/approvals.py — FastAPI router for approval actions (#17, #26).

Provides endpoints for the approval modal's four actions (Send As-Is, Edit,
Reject, Skip) and a detail endpoint for loading full approval content.

Endpoints:
    GET  /api/approvals/{id}          — Full approval detail for the modal
    POST /api/approvals/{id}/approve  — Approve (send as-is or with edits)
    POST /api/approvals/{id}/reject   — Reject (do not send)
    POST /api/approvals/{id}/skip     — Skip (come back later)

Cross-cutting constraints:
    C2 — Only pending_approval items can be actioned; this is the HITL gate
    C4 — Every action creates an audit event for traceability

Called by:
    The React frontend's approval modal (keyboard shortcuts + buttons).
"""

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from backend.db.database import get_db
from backend.db.models import Approval, Message
from backend.services.dashboard import (
    approve_approval,
    get_approval_detail,
    reject_approval,
    skip_approval,
)

logger = logging.getLogger("golteris.api.approvals")

router = APIRouter(prefix="/api/approvals", tags=["approvals"])


class ApproveRequest(BaseModel):
    """Request body for approving a draft. Both fields are optional."""
    # Who is approving — defaults to "broker" if not provided
    resolved_by: str = "broker"
    # If the broker edited the draft before approving, include the new body.
    # None means "send as-is" (the original draft_body).
    resolved_body: Optional[str] = None


class ResolveRequest(BaseModel):
    """Request body for reject/skip actions."""
    resolved_by: str = "broker"


@router.get("/{approval_id}")
def get_approval(
    approval_id: int,
    db: Session = Depends(get_db),
):
    """
    Get full approval detail for the approval modal.

    Returns the complete draft (body, subject, recipient), the reason flag,
    the related RFQ context, and the most recent inbound message on that RFQ
    (the "SHIPPER WROTE" section in the modal).

    FR-HI-2: Modal shows original shipper message, drafted reply, reason flag.
    """
    approval = get_approval_detail(db, approval_id)
    if not approval:
        raise HTTPException(status_code=404, detail=f"Approval {approval_id} not found")

    # Find the most recent inbound message for this RFQ to show "SHIPPER WROTE"
    original_message = None
    if approval.rfq_id:
        msg = (
            db.query(Message)
            .filter(Message.rfq_id == approval.rfq_id, Message.direction == "inbound")
            .order_by(Message.received_at.desc())
            .first()
        )
        if msg:
            original_message = {
                "sender": msg.sender,
                "subject": msg.subject,
                "body": msg.body,
                "received_at": msg.received_at.isoformat() if msg.received_at else None,
            }

    rfq = approval.rfq
    return {
        "id": approval.id,
        "rfq_id": approval.rfq_id,
        "approval_type": approval.approval_type.value if approval.approval_type else None,
        "draft_body": approval.draft_body,
        "draft_subject": approval.draft_subject,
        "draft_recipient": approval.draft_recipient,
        "reason": approval.reason,
        "status": approval.status.value if approval.status else None,
        "created_at": approval.created_at.isoformat() if approval.created_at else None,
        "rfq": {
            "id": rfq.id,
            "customer_name": rfq.customer_name,
            "customer_company": rfq.customer_company,
            "origin": rfq.origin,
            "destination": rfq.destination,
        } if rfq else None,
        "original_message": original_message,
    }


@router.post("/{approval_id}/approve")
def approve(
    approval_id: int,
    body: ApproveRequest,
    db: Session = Depends(get_db),
):
    """
    Approve a pending approval, marking it safe to send.

    C2 constraint: only approvals in 'pending_approval' status can be approved.
    If the approval is already resolved (approved/rejected/skipped), returns 400.
    If the approval doesn't exist, returns 404.

    On success, creates an audit event and returns the updated approval.
    """
    result = approve_approval(
        db,
        approval_id=approval_id,
        resolved_by=body.resolved_by,
        resolved_body=body.resolved_body,
    )
    if result is None:
        return _not_found_or_resolved(db, approval_id)

    return _action_response(result)


@router.post("/{approval_id}/reject")
def reject(
    approval_id: int,
    body: ResolveRequest,
    db: Session = Depends(get_db),
):
    """
    Reject a pending approval — the draft will NOT be sent.

    C2 constraint: rejecting is a deliberate human action. Creates an audit
    event so the rejection is traceable.
    """
    result = reject_approval(db, approval_id=approval_id, resolved_by=body.resolved_by)
    if result is None:
        return _not_found_or_resolved(db, approval_id)

    return _action_response(result)


@router.post("/{approval_id}/skip")
def skip(
    approval_id: int,
    body: ResolveRequest,
    db: Session = Depends(get_db),
):
    """
    Skip a pending approval — come back to it later.

    The approval moves to 'skipped' status. It remains visible in the
    history but is removed from the active pending queue.
    """
    result = skip_approval(db, approval_id=approval_id, resolved_by=body.resolved_by)
    if result is None:
        return _not_found_or_resolved(db, approval_id)

    return _action_response(result)


def _action_response(approval: Approval) -> dict:
    """Standard response shape for approve/reject/skip actions."""
    return {
        "id": approval.id,
        "status": approval.status.value,
        "resolved_by": approval.resolved_by,
        "resolved_at": approval.resolved_at.isoformat() if approval.resolved_at else None,
    }


def _not_found_or_resolved(db: Session, approval_id: int):
    """Raise 404 if approval doesn't exist, 400 if already resolved."""
    exists = db.query(Approval).filter(Approval.id == approval_id).first()
    if not exists:
        raise HTTPException(status_code=404, detail=f"Approval {approval_id} not found")
    raise HTTPException(
        status_code=400,
        detail=f"Approval {approval_id} is not pending (current status: {exists.status.value})",
    )
