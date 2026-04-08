"""
backend/api/admin.py — Admin panel API endpoints (#131).

Provides system administration capabilities:
- Process status (which services are running)
- Worker restart
- RFQ pipeline tracker (trace an RFQ through every stage)

All endpoints require the "admin" role. Regular broker users (owner,
operator, viewer) cannot access these.

Endpoints:
    GET  /api/admin/processes          — List running processes and their status
    POST /api/admin/restart-worker     — Restart the background worker
    GET  /api/admin/pipeline/:rfq_id   — Full pipeline trace for an RFQ
    GET  /api/admin/pipeline           — Search/filter RFQs with pipeline status
"""

import logging
import os
import signal
import subprocess
import sys
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, text
from sqlalchemy.orm import Session
from typing import Optional

from backend.db.database import get_db
from backend.db.models import (
    AgentCall,
    AgentRun,
    Approval,
    AuditEvent,
    Job,
    JobStatus,
    Message,
    MessageDirection,
    RFQ,
)

logger = logging.getLogger("golteris.api.admin")

router = APIRouter(prefix="/api/admin", tags=["admin"])

# Track the worker subprocess PID so we can restart it
_worker_pid: Optional[int] = None


@router.get("/processes")
def get_processes(db: Session = Depends(get_db)):
    """
    List running processes and their health status.

    Checks:
    - Web server (always running if this endpoint responds)
    - Worker process (checks if PID is alive or if recent jobs were processed)
    - Database connectivity
    - Email provider status (last poll time)
    """
    now = datetime.utcnow()

    # Web server — always alive if we're responding
    web_status = {"name": "Web Server", "status": "running", "pid": os.getpid(), "uptime": None}

    # Worker — check if any jobs were processed recently (last 60s)
    last_job = db.query(func.max(Job.finished_at)).scalar()
    worker_active = last_job and (now - last_job).total_seconds() < 120
    worker_status = {
        "name": "Background Worker",
        "status": "running" if worker_active else "stopped",
        "last_activity": last_job.isoformat() if last_job else None,
        "pid": _worker_pid,
    }

    # Database — alive if this query works
    try:
        db.execute(text("SELECT 1"))
        db_status = {"name": "Database (PostgreSQL)", "status": "running"}
    except Exception:
        db_status = {"name": "Database (PostgreSQL)", "status": "error"}

    # Pending jobs
    pending_count = db.query(func.count(Job.id)).filter(Job.status == JobStatus.PENDING).scalar() or 0
    running_count = db.query(func.count(Job.id)).filter(Job.status == JobStatus.RUNNING).scalar() or 0

    return {
        "processes": [web_status, worker_status, db_status],
        "jobs": {
            "pending": pending_count,
            "running": running_count,
        },
        "checked_at": now.isoformat(),
    }


@router.post("/restart-worker")
def restart_worker():
    """
    Restart the background worker process.

    Kills the current worker (if tracked) and starts a new one.
    The worker is started as a subprocess running backend.worker.run_worker().
    """
    global _worker_pid

    # Kill existing worker if we have its PID
    if _worker_pid:
        try:
            os.kill(_worker_pid, signal.SIGTERM)
            logger.info("Killed worker PID %d", _worker_pid)
        except (OSError, ProcessLookupError):
            logger.warning("Worker PID %d not found — may have already exited", _worker_pid)

    # Start a new worker subprocess
    try:
        proc = subprocess.Popen(
            [sys.executable, "-c",
             "from dotenv import load_dotenv; load_dotenv(); from backend.worker import run_worker; run_worker()"],
            cwd=os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        _worker_pid = proc.pid
        logger.info("Started new worker with PID %d", _worker_pid)
        return {
            "status": "ok",
            "message": f"Worker restarted (PID {_worker_pid})",
            "pid": _worker_pid,
        }
    except Exception as e:
        logger.error("Failed to restart worker: %s", e)
        return {"status": "error", "message": str(e)}


@router.get("/pipeline/{rfq_id}")
def get_pipeline_trace(rfq_id: int, db: Session = Depends(get_db)):
    """
    Full pipeline trace for a specific RFQ.

    Shows every stage the RFQ went through: ingestion, matching,
    extraction, validation, approval, outbound send — with timestamps,
    duration, and status at each stage.
    """
    rfq = db.query(RFQ).filter(RFQ.id == rfq_id).first()
    if not rfq:
        raise HTTPException(status_code=404, detail="RFQ not found")

    # Inbound messages that triggered this RFQ
    messages = db.query(Message).filter(Message.rfq_id == rfq_id).order_by(Message.received_at).all()

    # Jobs related to this RFQ
    jobs = db.query(Job).filter(Job.rfq_id == rfq_id).order_by(Job.created_at).all()

    # Agent runs for this RFQ
    runs = db.query(AgentRun).filter(AgentRun.rfq_id == rfq_id).order_by(AgentRun.started_at).all()

    # Agent calls within those runs
    run_ids = [r.id for r in runs]
    calls = db.query(AgentCall).filter(AgentCall.run_id.in_(run_ids)).order_by(AgentCall.started_at).all() if run_ids else []

    # Approvals for this RFQ
    approvals = db.query(Approval).filter(Approval.rfq_id == rfq_id).order_by(Approval.created_at).all()

    # Audit events
    events = db.query(AuditEvent).filter(AuditEvent.rfq_id == rfq_id).order_by(AuditEvent.created_at).all()

    # Build pipeline stages
    stages = []

    # Stage 1: Ingestion
    inbound = [m for m in messages if m.direction == MessageDirection.INBOUND]
    if inbound:
        first = inbound[0]
        stages.append({
            "stage": "Ingestion",
            "status": "completed",
            "timestamp": first.received_at.isoformat() if first.received_at else None,
            "details": f"Email from {first.sender}: {first.subject}",
        })

    # Stage 2: Matching
    matching_jobs = [j for j in jobs if j.job_type == "matching"]
    if matching_jobs:
        j = matching_jobs[0]
        stages.append({
            "stage": "Matching",
            "status": j.status.value,
            "timestamp": j.created_at.isoformat() if j.created_at else None,
            "duration_ms": _job_duration(j),
            "details": f"Job #{j.id} — matched to RFQ #{rfq_id}",
        })

    # Stage 3: Extraction
    extraction_runs = [r for r in runs if r.workflow_name == "extraction"]
    extraction_jobs = [j for j in jobs if j.job_type == "extraction"]
    if extraction_runs:
        r = extraction_runs[0]
        stages.append({
            "stage": "Extraction",
            "status": r.status.value,
            "timestamp": r.started_at.isoformat() if r.started_at else None,
            "duration_ms": r.duration_ms,
            "cost_usd": float(r.total_cost_usd) if r.total_cost_usd else None,
            "details": f"Extracted {_count_fields(rfq)} fields",
        })
    elif extraction_jobs:
        j = extraction_jobs[0]
        stages.append({
            "stage": "Extraction",
            "status": j.status.value,
            "timestamp": j.created_at.isoformat() if j.created_at else None,
            "details": f"Job #{j.id}",
        })

    # Stage 4: Validation
    validation_runs = [r for r in runs if r.workflow_name == "validation"]
    validation_jobs = [j for j in jobs if j.job_type == "validation"]
    if validation_runs:
        r = validation_runs[0]
        stages.append({
            "stage": "Validation",
            "status": r.status.value,
            "timestamp": r.started_at.isoformat() if r.started_at else None,
            "duration_ms": r.duration_ms,
            "details": f"State: {rfq.state.value}",
        })
    elif validation_jobs:
        j = validation_jobs[0]
        stages.append({
            "stage": "Validation",
            "status": j.status.value,
            "timestamp": j.created_at.isoformat() if j.created_at else None,
            "details": f"Job #{j.id}",
        })

    # Stage 5: Approval
    if approvals:
        for a in approvals:
            stages.append({
                "stage": "Approval",
                "status": a.status.value,
                "timestamp": a.created_at.isoformat() if a.created_at else None,
                "details": f"{a.approval_type.value} — {a.reason or 'pending review'}",
            })

    # Stage 6: Outbound
    outbound = [m for m in messages if m.direction == MessageDirection.OUTBOUND]
    for m in outbound:
        stages.append({
            "stage": "Outbound Send",
            "status": "completed",
            "timestamp": m.created_at.isoformat() if m.created_at else None,
            "details": f"Sent to {m.sender}: {m.subject}",
        })

    return {
        "rfq": {
            "id": rfq.id,
            "customer_name": rfq.customer_name,
            "customer_company": rfq.customer_company,
            "origin": rfq.origin,
            "destination": rfq.destination,
            "state": rfq.state.value,
            "created_at": rfq.created_at.isoformat() if rfq.created_at else None,
        },
        "pipeline": stages,
        "summary": {
            "total_stages": len(stages),
            "messages": len(messages),
            "jobs": len(jobs),
            "agent_runs": len(runs),
            "agent_calls": len(calls),
            "approvals": len(approvals),
            "events": len(events),
        },
    }


@router.get("/pipeline")
def search_pipeline(
    search: Optional[str] = Query(None),
    state: Optional[str] = Query(None),
    limit: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
):
    """
    Search/filter RFQs with their pipeline stage summary.

    Used by the admin Pipeline Tracker to find and drill into any RFQ.
    """
    query = db.query(RFQ).order_by(RFQ.created_at.desc())

    if search:
        query = query.filter(
            (RFQ.customer_name.ilike(f"%{search}%"))
            | (RFQ.customer_company.ilike(f"%{search}%"))
            | (RFQ.origin.ilike(f"%{search}%"))
            | (RFQ.destination.ilike(f"%{search}%"))
        )
    if state:
        query = query.filter(RFQ.state == state)

    rfqs = query.limit(limit).all()

    results = []
    for rfq in rfqs:
        # Quick stage counts
        job_count = db.query(func.count(Job.id)).filter(Job.rfq_id == rfq.id).scalar() or 0
        run_count = db.query(func.count(AgentRun.id)).filter(AgentRun.rfq_id == rfq.id).scalar() or 0
        approval_count = db.query(func.count(Approval.id)).filter(Approval.rfq_id == rfq.id).scalar() or 0

        results.append({
            "id": rfq.id,
            "customer_name": rfq.customer_name,
            "customer_company": rfq.customer_company,
            "origin": rfq.origin,
            "destination": rfq.destination,
            "state": rfq.state.value,
            "created_at": rfq.created_at.isoformat() if rfq.created_at else None,
            "pipeline_counts": {
                "jobs": job_count,
                "runs": run_count,
                "approvals": approval_count,
            },
        })

    return {"rfqs": results, "total": len(results)}


def _job_duration(job: Job) -> Optional[int]:
    """Calculate job duration in ms from started_at to finished_at."""
    if job.started_at and job.finished_at:
        return int((job.finished_at - job.started_at).total_seconds() * 1000)
    return None


def _count_fields(rfq: RFQ) -> int:
    """Count how many extracted fields are populated on an RFQ."""
    fields = [rfq.customer_name, rfq.origin, rfq.destination, rfq.equipment_type,
              rfq.commodity, rfq.weight_lbs, rfq.truck_count, rfq.pickup_date]
    return sum(1 for f in fields if f is not None)
