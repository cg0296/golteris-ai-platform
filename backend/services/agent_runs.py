"""
backend/services/agent_runs.py — Service layer for agent run lifecycle management.

This module is the single place where agent_runs rows are created, updated,
and queried. It enforces the run lifecycle:

    start_run() -> [agent calls happen] -> finish_run()
                                        -> fail_run()
                -> pause_run() -> resume_run() -> finish_run()

Every workflow invocation (email processing, extraction, validation, etc.)
must call start_run() at the beginning and finish_run() or fail_run() at
the end. This is how we satisfy #22's acceptance criteria:
    - Every workflow invocation creates an agent_run row
    - Duration reflects total wall time including HITL pauses
    - Cost and token totals roll up from agent_calls

Called by:
    - The background worker (backend/worker.py) when dispatching workflows
    - Future agent orchestration code when running multi-step pipelines
    - API routes (backend/api/agent_runs.py) for read operations

Cross-cutting constraints:
    C1 — Runs are only created for enabled workflows (checked by the worker,
         not here — this module trusts its callers to have checked C1 already)
    C4 — Every run is visible and traceable via the API endpoints
    C5 — Cost rollup enables per-run and per-day cost tracking
"""

import logging
from datetime import datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import func
from sqlalchemy.orm import Session

from backend.db.models import AgentCall, AgentRun, AgentRunStatus

logger = logging.getLogger("golteris.services.agent_runs")


def start_run(
    db: Session,
    workflow_name: str,
    rfq_id: Optional[int] = None,
    workflow_id: Optional[int] = None,
    trigger_source: Optional[str] = None,
) -> AgentRun:
    """
    Create a new agent run and persist it immediately.

    Call this at the very start of a workflow invocation. The returned run's
    ID is passed to call_llm() so that individual LLM calls are linked to
    this run via agent_calls.run_id.

    Args:
        db: SQLAlchemy session.
        workflow_name: Human-readable name (e.g., "Inbound Quote Processing").
            Denormalized into the row for fast queries without joining workflows.
        rfq_id: The RFQ being processed, if applicable. Null for system-level
            runs like mailbox polling or scheduled maintenance.
        workflow_id: FK to the workflows table. Null if the run isn't tied to
            a specific workflow definition (e.g., ad-hoc manual triggers).
        trigger_source: What kicked off this run. Common values:
            "new_email", "timer", "manual", "state_change", "retry".

    Returns:
        The newly created AgentRun with status=RUNNING and started_at set.

    Side effects:
        Commits the new row to the database so it's immediately visible
        in the Agent -> Tasks Queue view (C4 — visible reasoning).
    """
    run = AgentRun(
        rfq_id=rfq_id,
        workflow_id=workflow_id,
        workflow_name=workflow_name,
        trigger_source=trigger_source,
        status=AgentRunStatus.RUNNING,
        started_at=datetime.utcnow(),
        total_cost_usd=Decimal("0"),
        total_input_tokens=0,
        total_output_tokens=0,
    )
    db.add(run)
    db.commit()
    db.refresh(run)

    logger.info(
        "Agent run started: id=%d workflow=%s rfq_id=%s trigger=%s",
        run.id, workflow_name, rfq_id, trigger_source,
    )
    return run


def finish_run(
    db: Session,
    run_id: int,
    status: AgentRunStatus = AgentRunStatus.COMPLETED,
) -> AgentRun:
    """
    Mark a run as finished, calculate duration, and roll up cost/tokens.

    Call this when a workflow invocation completes (successfully or otherwise).
    The duration_ms reflects total wall time from started_at to now, which
    includes any HITL pauses — this is intentional per the acceptance criteria.

    The cost and token rollup queries the agent_calls table for all calls
    linked to this run and sums their values. This is the authoritative
    source for per-run cost (C5 — cost tracking).

    Args:
        db: SQLAlchemy session.
        run_id: The run to finish.
        status: Final status — typically COMPLETED or FAILED.

    Returns:
        The updated AgentRun with final duration, cost, and token totals.

    Raises:
        ValueError: If the run_id doesn't exist.
    """
    run = db.query(AgentRun).filter(AgentRun.id == run_id).first()
    if not run:
        raise ValueError(f"Agent run {run_id} not found")

    now = datetime.utcnow()
    run.finished_at = now
    run.status = status

    # Calculate wall-clock duration in milliseconds.
    # This includes HITL pause time — the broker sees total elapsed time,
    # which is the honest metric for "how long did this take end-to-end."
    if run.started_at:
        delta = now - run.started_at
        run.duration_ms = int(delta.total_seconds() * 1000)

    # Roll up cost and tokens from all child agent_calls.
    # This is a SUM query, not application-side accumulation, so it's
    # always consistent even if a call was retried or added late.
    rollup = _rollup_from_calls(db, run_id)
    run.total_cost_usd = rollup["total_cost_usd"]
    run.total_input_tokens = rollup["total_input_tokens"]
    run.total_output_tokens = rollup["total_output_tokens"]

    db.commit()
    db.refresh(run)

    logger.info(
        "Agent run finished: id=%d status=%s duration=%dms cost=$%.4f tokens=%d/%d",
        run.id, status.value, run.duration_ms or 0,
        float(run.total_cost_usd), run.total_input_tokens, run.total_output_tokens,
    )
    return run


def fail_run(db: Session, run_id: int, error_message: Optional[str] = None) -> AgentRun:
    """
    Mark a run as failed. Convenience wrapper around finish_run().

    Args:
        db: SQLAlchemy session.
        run_id: The run that failed.
        error_message: Optional error detail (logged but not stored on the run —
            individual call errors are in agent_calls.error_message).

    Returns:
        The updated AgentRun with status=FAILED.
    """
    if error_message:
        logger.error("Agent run %d failed: %s", run_id, error_message)
    return finish_run(db, run_id, status=AgentRunStatus.FAILED)


def pause_run(db: Session, run_id: int) -> AgentRun:
    """
    Pause a run for HITL review.

    Called when a workflow reaches a point that requires human approval
    (e.g., the extraction agent produced a draft that needs review before
    the next step). The run stays paused until resume_run() is called
    after the human acts on the approval.

    Duration continues to accumulate — pause time is included in the
    final duration_ms because the broker cares about total elapsed time.

    Args:
        db: SQLAlchemy session.
        run_id: The run to pause.

    Returns:
        The updated AgentRun with status=PAUSED_FOR_HITL.

    Raises:
        ValueError: If the run_id doesn't exist.
    """
    run = db.query(AgentRun).filter(AgentRun.id == run_id).first()
    if not run:
        raise ValueError(f"Agent run {run_id} not found")

    run.status = AgentRunStatus.PAUSED_FOR_HITL
    db.commit()
    db.refresh(run)

    logger.info("Agent run paused for HITL: id=%d", run.id)
    return run


def resume_run(db: Session, run_id: int) -> AgentRun:
    """
    Resume a run after HITL review.

    Called after the broker approves/rejects/skips the pending item.
    Sets status back to RUNNING so the workflow can continue.

    Args:
        db: SQLAlchemy session.
        run_id: The run to resume.

    Returns:
        The updated AgentRun with status=RUNNING.

    Raises:
        ValueError: If the run_id doesn't exist.
    """
    run = db.query(AgentRun).filter(AgentRun.id == run_id).first()
    if not run:
        raise ValueError(f"Agent run {run_id} not found")

    run.status = AgentRunStatus.RUNNING
    db.commit()
    db.refresh(run)

    logger.info("Agent run resumed: id=%d", run.id)
    return run


def get_run(db: Session, run_id: int) -> Optional[AgentRun]:
    """
    Fetch a single run by ID, or None if not found.

    Args:
        db: SQLAlchemy session.
        run_id: The run to fetch.

    Returns:
        The AgentRun or None.
    """
    return db.query(AgentRun).filter(AgentRun.id == run_id).first()


def list_runs(
    db: Session,
    status: Optional[AgentRunStatus] = None,
    rfq_id: Optional[int] = None,
    limit: int = 50,
    offset: int = 0,
) -> list[AgentRun]:
    """
    List agent runs with optional filters, ordered by most recent first.

    Used by the GET /api/agent/runs endpoint to power the Agent -> Run
    Timeline view (#38). Supports filtering by status and RFQ to let
    the broker drill into specific workflows or problematic runs.

    Args:
        db: SQLAlchemy session.
        status: Filter by run status (e.g., only RUNNING or FAILED).
        rfq_id: Filter by RFQ to see all runs for a specific quote request.
        limit: Max rows to return (default 50, for pagination).
        offset: Skip this many rows (for pagination).

    Returns:
        List of AgentRun objects, newest first.
    """
    query = db.query(AgentRun).order_by(AgentRun.started_at.desc())

    if status is not None:
        query = query.filter(AgentRun.status == status)
    if rfq_id is not None:
        query = query.filter(AgentRun.rfq_id == rfq_id)

    return query.offset(offset).limit(limit).all()


def count_runs(
    db: Session,
    status: Optional[AgentRunStatus] = None,
    rfq_id: Optional[int] = None,
) -> int:
    """
    Count agent runs matching the given filters.

    Used by the API for pagination metadata (total count).

    Args:
        db: SQLAlchemy session.
        status: Filter by run status.
        rfq_id: Filter by RFQ.

    Returns:
        Total number of matching runs.
    """
    query = db.query(func.count(AgentRun.id))

    if status is not None:
        query = query.filter(AgentRun.status == status)
    if rfq_id is not None:
        query = query.filter(AgentRun.rfq_id == rfq_id)

    return query.scalar() or 0


def _rollup_from_calls(db: Session, run_id: int) -> dict:
    """
    Sum cost and tokens across all agent_calls for a given run.

    This is the authoritative cost/token rollup. It runs a single SQL
    SUM query rather than iterating in Python, so it's consistent even
    if calls were added concurrently or retried.

    Returns a dict with keys: total_cost_usd, total_input_tokens, total_output_tokens.
    All default to zero if no calls exist (e.g., the run failed before making any calls).
    """
    result = db.query(
        func.coalesce(func.sum(AgentCall.cost_usd), Decimal("0")),
        func.coalesce(func.sum(AgentCall.input_tokens), 0),
        func.coalesce(func.sum(AgentCall.output_tokens), 0),
    ).filter(AgentCall.run_id == run_id).first()

    return {
        "total_cost_usd": result[0] if result else Decimal("0"),
        "total_input_tokens": result[1] if result else 0,
        "total_output_tokens": result[2] if result else 0,
    }
