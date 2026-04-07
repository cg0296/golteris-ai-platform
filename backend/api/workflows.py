"""
backend/api/workflows.py — FastAPI router for workflow management (#31).

Provides the Settings page endpoints for toggling workflows on/off,
the global kill switch, and viewing workflow status.

Endpoints:
    GET  /api/workflows           — List all workflows with enabled status
    PUT  /api/workflows/{id}      — Toggle a workflow on/off
    POST /api/workflows/kill      — Kill switch — disable ALL workflows
    GET  /api/settings/status     — System status (cost caps, mailbox, worker)

Cross-cutting constraints:
    C1 — Workflow toggles are the enforcement point. When disabled, the worker
         stops dispatching jobs for that workflow within 30 seconds.
"""

import logging
import os
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from backend.db.database import get_db
from backend.db.models import AuditEvent, Workflow

logger = logging.getLogger("golteris.api.workflows")

router = APIRouter(tags=["settings"])


@router.get("/api/workflows")
def list_workflows(db: Session = Depends(get_db)):
    """
    List all workflows with their enabled status.

    The Settings page renders a toggle switch for each workflow.
    C1: when enabled=False, the worker stops processing jobs for that workflow.
    """
    workflows = db.query(Workflow).order_by(Workflow.name.asc()).all()
    return {
        "workflows": [
            {
                "id": w.id,
                "name": w.name,
                "enabled": w.enabled,
                "updated_at": w.updated_at.isoformat() if w.updated_at else None,
            }
            for w in workflows
        ],
    }


class ToggleRequest(BaseModel):
    """Request body for toggling a workflow."""
    enabled: bool


@router.put("/api/workflows/{workflow_id}")
def toggle_workflow(
    workflow_id: int,
    body: ToggleRequest,
    db: Session = Depends(get_db),
):
    """
    Toggle a workflow on or off (C1 enforcement point).

    When disabled, the background worker will stop dispatching new jobs
    for this workflow. Existing running jobs complete but no new ones start.
    """
    workflow = db.query(Workflow).filter(Workflow.id == workflow_id).first()
    if not workflow:
        raise HTTPException(status_code=404, detail=f"Workflow {workflow_id} not found")

    old_state = workflow.enabled
    workflow.enabled = body.enabled
    workflow.updated_at = datetime.now(timezone.utc)

    # Audit the toggle (C1 visibility)
    action = "enabled" if body.enabled else "disabled"
    event = AuditEvent(
        event_type=f"workflow_{action}",
        actor="broker",
        description=f"Workflow '{workflow.name}' {action}",
        event_data={
            "workflow_id": workflow.id,
            "workflow_name": workflow.name,
            "old_state": old_state,
            "new_state": body.enabled,
        },
    )
    db.add(event)
    db.commit()

    return {
        "id": workflow.id,
        "name": workflow.name,
        "enabled": workflow.enabled,
    }


@router.post("/api/workflows/kill")
def kill_switch(db: Session = Depends(get_db)):
    """
    Global kill switch — disable ALL workflows immediately (C1).

    This is the "stop everything" button. Sets every workflow to enabled=False
    in a single UPDATE. The worker checks workflow.enabled before processing
    each job, so all processing stops within one poll cycle (~10-30 seconds).

    C1 constraint: the broker must be able to stop all agent work at any time.
    """
    workflows = db.query(Workflow).all()
    disabled_count = 0
    for w in workflows:
        if w.enabled:
            w.enabled = False
            w.updated_at = datetime.now(timezone.utc)
            disabled_count += 1

    # Audit the kill switch activation
    event = AuditEvent(
        event_type="kill_switch_activated",
        actor="broker",
        description=f"Kill switch activated — {disabled_count} workflow(s) disabled",
        event_data={"disabled_count": disabled_count},
    )
    db.add(event)
    db.commit()

    logger.warning("KILL SWITCH activated — %d workflows disabled", disabled_count)

    return {
        "status": "all_disabled",
        "disabled_count": disabled_count,
    }


@router.get("/api/settings/status")
def get_system_status(db: Session = Depends(get_db)):
    """
    System status overview for the Settings page.

    Returns cost cap configuration, mailbox provider status, and
    workflow summary so the broker sees the system health at a glance.
    """
    # Cost caps from environment
    daily_cap = os.environ.get("LLM_DAILY_COST_CAP", "20.00")
    monthly_cap = os.environ.get("LLM_MONTHLY_COST_CAP", "100.00")

    # Mailbox provider detection
    graph_configured = bool(os.environ.get("MS_GRAPH_CLIENT_ID"))
    imap_configured = bool(os.environ.get("IMAP_HOST"))
    if graph_configured:
        mailbox_provider = "Microsoft Graph"
        mailbox_email = os.environ.get("MS_GRAPH_USER_EMAIL", "")
    elif imap_configured:
        mailbox_provider = "IMAP"
        mailbox_email = os.environ.get("IMAP_USER", "")
    else:
        mailbox_provider = "File (demo)"
        mailbox_email = ""

    # Workflow summary
    workflows = db.query(Workflow).all()
    enabled_count = sum(1 for w in workflows if w.enabled)

    return {
        "cost_caps": {
            "daily": float(daily_cap),
            "monthly": float(monthly_cap),
        },
        "mailbox": {
            "provider": mailbox_provider,
            "email": mailbox_email,
            "connected": graph_configured or imap_configured,
        },
        "workflows": {
            "total": len(workflows),
            "enabled": enabled_count,
        },
    }
