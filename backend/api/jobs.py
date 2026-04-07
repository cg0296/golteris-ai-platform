"""
backend/api/jobs.py — Job queue management API (#51).

Endpoints for viewing the job queue, dead-letter queue (failed jobs),
and reprocessing failed jobs.

Endpoints:
    GET  /api/agent/jobs     — List jobs with status filter
    GET  /api/agent/dlq      — Dead-letter queue (permanently failed jobs)
    POST /api/agent/dlq/{id}/retry — Reprocess a failed job
"""

import logging

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from backend.db.database import get_db
from backend.db.models import AuditEvent, Job, JobStatus

logger = logging.getLogger("golteris.api.jobs")

router = APIRouter(prefix="/api/agent", tags=["jobs"])


@router.get("/jobs")
def list_jobs(
    status: str | None = Query(None, description="Filter by status"),
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
):
    """List jobs with optional status filter."""
    query = db.query(Job)
    if status:
        try:
            query = query.filter(Job.status == JobStatus(status.upper()))
        except ValueError:
            pass
    jobs = query.order_by(Job.created_at.desc()).limit(limit).all()

    return {
        "jobs": [
            {
                "id": j.id,
                "job_type": j.job_type,
                "status": j.status.value,
                "rfq_id": j.rfq_id,
                "retry_count": j.retry_count,
                "max_retries": j.max_retries,
                "error_message": j.error_message,
                "created_at": j.created_at.isoformat() if j.created_at else None,
                "started_at": j.started_at.isoformat() if j.started_at else None,
                "finished_at": j.finished_at.isoformat() if j.finished_at else None,
            }
            for j in jobs
        ],
        "total": len(jobs),
    }


@router.get("/dlq")
def dead_letter_queue(
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
):
    """
    Dead-letter queue — permanently failed jobs that exhausted retries.

    These jobs need human review. The broker can see what failed,
    investigate, and reprocess if the underlying issue is fixed.
    """
    failed = (
        db.query(Job)
        .filter(Job.status == JobStatus.FAILED)
        .order_by(Job.finished_at.desc())
        .limit(limit)
        .all()
    )

    return {
        "failed_jobs": [
            {
                "id": j.id,
                "job_type": j.job_type,
                "rfq_id": j.rfq_id,
                "retry_count": j.retry_count,
                "error_message": j.error_message,
                "created_at": j.created_at.isoformat() if j.created_at else None,
                "finished_at": j.finished_at.isoformat() if j.finished_at else None,
                "payload": j.payload,
            }
            for j in failed
        ],
        "total": len(failed),
    }


@router.post("/dlq/{job_id}/retry")
def retry_failed_job(
    job_id: int,
    db: Session = Depends(get_db),
):
    """
    Reprocess a failed job — reset it to PENDING and clear the error.

    Use this after fixing the underlying issue (e.g., fixing a bug,
    updating credentials, etc.). The worker will pick it up next cycle.
    """
    job = db.query(Job).filter(Job.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail=f"Job {job_id} not found")

    if job.status != JobStatus.FAILED:
        raise HTTPException(status_code=400, detail=f"Job {job_id} is {job.status.value}, not FAILED")

    job.status = JobStatus.PENDING
    job.started_at = None
    job.finished_at = None
    job.retry_count = 0
    job.error_message = None

    event = AuditEvent(
        rfq_id=job.rfq_id,
        event_type="job_reprocessed",
        actor="broker",
        description=f"Reprocessing failed {job.job_type} job #{job.id}",
        event_data={"job_id": job.id, "job_type": job.job_type},
    )
    db.add(event)
    db.commit()

    return {"id": job.id, "status": "PENDING", "message": "Job reset for reprocessing"}
