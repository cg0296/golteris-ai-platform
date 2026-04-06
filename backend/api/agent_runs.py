"""
backend/api/agent_runs.py — FastAPI router for agent run endpoints.

Provides the REST API that powers the Agent -> Run Timeline view (#38)
and the Agent -> Tasks Queue view (#39). These endpoints let the broker
see every workflow invocation, drill into individual runs, and understand
cost/duration per run.

Endpoints:
    GET /api/agent/runs      — paginated list of runs with filters
    GET /api/agent/runs/:id  — single run with child calls and rollup

Cross-cutting constraints:
    C3 — Response descriptions use plain English, not agent jargon
    C4 — Every run and its child calls are fully visible (visible reasoning)
    C5 — Cost rollup is included so the broker can track spend per run

Called by:
    The React frontend via React Query polling (~10s interval).
"""

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from backend.db.database import get_db
from backend.db.models import AgentCall, AgentRun, AgentRunStatus
from backend.services.agent_runs import count_runs, get_run, list_runs

logger = logging.getLogger("golteris.api.agent_runs")

router = APIRouter(prefix="/api/agent", tags=["agent-runs"])


@router.get("/runs")
def get_agent_runs(
    status: Optional[str] = Query(None, description="Filter by status: running, completed, failed, paused_for_hitl"),
    rfq_id: Optional[int] = Query(None, description="Filter by RFQ ID"),
    limit: int = Query(50, ge=1, le=200, description="Page size"),
    offset: int = Query(0, ge=0, description="Number of rows to skip"),
    db: Session = Depends(get_db),
):
    """
    List agent runs with optional filters.

    Returns a paginated list of workflow runs, newest first. Each run
    includes its status, duration, cost, and token counts. The broker
    uses this to monitor what the system is doing and spot expensive
    or slow runs.

    Response shape matches what the Agent -> Run Timeline view (#38) needs:
    a list of run summaries with enough info to render timeline bars and
    cost badges, plus pagination metadata for infinite scroll.
    """
    # Parse status filter if provided — validate against the enum
    status_filter = None
    if status:
        try:
            status_filter = AgentRunStatus(status)
        except ValueError:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid status '{status}'. Must be one of: "
                       f"{', '.join(s.value for s in AgentRunStatus)}",
            )

    runs = list_runs(db, status=status_filter, rfq_id=rfq_id, limit=limit, offset=offset)
    total = count_runs(db, status=status_filter, rfq_id=rfq_id)

    return {
        "runs": [_serialize_run(r) for r in runs],
        "total": total,
        "limit": limit,
        "offset": offset,
    }


@router.get("/runs/{run_id}")
def get_agent_run_detail(
    run_id: int,
    db: Session = Depends(get_db),
):
    """
    Get a single agent run with its child calls.

    Returns the full run details plus every LLM call made during this run.
    The broker uses this to drill into a specific workflow invocation and
    understand what the agents did, how much it cost, and how long each
    step took.

    The calls are ordered chronologically so the broker can follow the
    decision chain step by step (C4 — visible reasoning).
    """
    run = get_run(db, run_id)
    if not run:
        raise HTTPException(status_code=404, detail=f"Agent run {run_id} not found")

    # Fetch child calls ordered by start time — the broker reads these
    # top-to-bottom as a chronological decision chain
    calls = (
        db.query(AgentCall)
        .filter(AgentCall.run_id == run_id)
        .order_by(AgentCall.started_at.asc())
        .all()
    )

    return {
        "run": _serialize_run(run),
        "calls": [_serialize_call(c) for c in calls],
        "call_count": len(calls),
    }


def _serialize_run(run: AgentRun) -> dict:
    """
    Convert an AgentRun ORM object to a JSON-serializable dict.

    Field names use plain English where possible (C3). Technical fields
    like token counts are included for the observability view but would
    be hidden behind a disclosure in the main broker UI.
    """
    return {
        "id": run.id,
        "rfq_id": run.rfq_id,
        "workflow_id": run.workflow_id,
        "workflow_name": run.workflow_name,
        "trigger": run.trigger_source,
        "status": run.status.value if run.status else None,
        "started_at": run.started_at.isoformat() if run.started_at else None,
        "finished_at": run.finished_at.isoformat() if run.finished_at else None,
        "duration_ms": run.duration_ms,
        "total_cost_usd": float(run.total_cost_usd) if run.total_cost_usd else 0.0,
        "total_input_tokens": run.total_input_tokens or 0,
        "total_output_tokens": run.total_output_tokens or 0,
    }


def _serialize_call(call: AgentCall) -> dict:
    """
    Convert an AgentCall ORM object to a JSON-serializable dict.

    Includes the full prompt and response for the "View system reasoning"
    disclosure in the RFQ detail drawer (C4). These fields are large but
    necessary for auditability — the frontend hides them behind a toggle.
    """
    return {
        "id": call.id,
        "agent_name": call.agent_name,
        "provider": call.provider,
        "model": call.model,
        "status": call.status.value if call.status else None,
        "input_tokens": call.input_tokens or 0,
        "output_tokens": call.output_tokens or 0,
        "cost_usd": float(call.cost_usd) if call.cost_usd else 0.0,
        "started_at": call.started_at.isoformat() if call.started_at else None,
        "finished_at": call.finished_at.isoformat() if call.finished_at else None,
        "duration_ms": call.duration_ms,
        "system_prompt": call.system_prompt,
        "user_prompt": call.user_prompt,
        "response": call.response,
        "error_message": call.error_message,
    }
