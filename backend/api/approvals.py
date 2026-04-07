"""
backend/api/approvals.py — FastAPI router for approval actions (#17, #26).

Provides the endpoint for approving pending drafts from the dashboard's
Urgent Actions panel. This is the C2 enforcement point — the broker must
explicitly approve before any outbound email is sent.

Endpoints:
    POST /api/approvals/{id}/approve — Approve a pending draft

Cross-cutting constraints:
    C2 — Only pending_approval items can be approved; this is the gate
    C4 — Approval creates an audit event for traceability

Called by:
    The React frontend's Urgent Actions panel (inline "Approve" button).
"""

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from backend.db.database import get_db
from backend.services.dashboard import approve_approval

logger = logging.getLogger("golteris.api.approvals")

router = APIRouter(prefix="/api/approvals", tags=["approvals"])


class ApproveRequest(BaseModel):
    """Request body for approving a draft. Both fields are optional."""
    # Who is approving — defaults to "broker" if not provided
    resolved_by: str = "broker"
    # If the broker edited the draft before approving, include the new body.
    # None means "send as-is" (the original draft_body).
    resolved_body: Optional[str] = None


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
        # Distinguish between not-found and already-resolved
        from backend.db.models import Approval
        exists = db.query(Approval).filter(Approval.id == approval_id).first()
        if not exists:
            raise HTTPException(status_code=404, detail=f"Approval {approval_id} not found")
        raise HTTPException(
            status_code=400,
            detail=f"Approval {approval_id} is not pending (current status: {exists.status.value})",
        )

    return {
        "id": result.id,
        "status": result.status.value,
        "resolved_by": result.resolved_by,
        "resolved_at": result.resolved_at.isoformat() if result.resolved_at else None,
    }
