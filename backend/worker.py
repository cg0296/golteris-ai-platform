"""
backend/worker.py — Background worker for agent orchestration.

This is the long-running process that powers the Golteris pipeline. It:
1. Polls the Postgres job queue for pending work
2. Dispatches jobs to the appropriate agent
3. Handles failures with retry logic
4. Respects workflow enable/disable toggles (C1)

The job queue uses SELECT ... FOR UPDATE SKIP LOCKED on the `jobs` table,
which provides safe, concurrent job processing without an external queue
(Redis, RabbitMQ, Celery). See REQUIREMENTS.md §2.1.

Crash safety (FR-WK-2): All state lives in Postgres. If the worker crashes,
pending jobs stay pending and are picked up on restart. Running jobs that
were interrupted are detected by their stale `started_at` timestamp and
can be re-queued.

To run locally:
    python -m backend.worker

In production (Render), defined as a Background Worker in render.yaml.

Cross-cutting constraints:
    C1 — Checks workflows.enabled before processing each job. Kill switch
         (all workflows disabled) causes the worker to idle.
    C5 — Cost caps enforced at the call_llm level inside each agent.
    FR-WK-1 — Postgres job queue with FOR UPDATE SKIP LOCKED
    FR-WK-2 — All state in Postgres, nothing in memory
    FR-WK-3 — Worker idle state visible via the Tasks view (#39)
"""

import logging
import os
import sys
import time
from datetime import datetime, timedelta

# Add project root to path for imports when running as `python -m backend.worker`
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from dotenv import load_dotenv
load_dotenv()  # Load .env for Graph creds, cost caps, DB URL

from sqlalchemy import text

from backend.db.database import SessionLocal
from backend.db.models import Job, JobStatus, Workflow

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(name)s — %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("golteris.worker")

# How often the worker checks for jobs (in seconds)
POLL_INTERVAL = int(os.environ.get("WORKER_POLL_INTERVAL", "10"))

# Maximum jobs to process per poll cycle (prevents one cycle from running forever)
MAX_JOBS_PER_CYCLE = int(os.environ.get("WORKER_MAX_JOBS_PER_CYCLE", "5"))

# Stale job recovery: any job stuck in RUNNING state longer than this
# (in seconds) is considered abandoned (worker died mid-execution, OOM,
# redeploy, network stall) and gets re-queued by sweep_stale_jobs().
# Default: 3 minutes — longer than any legitimate agent call should take.
STALE_JOB_TIMEOUT = int(os.environ.get("WORKER_STALE_JOB_TIMEOUT", "180"))


# ---------------------------------------------------------------------------
# Job queue operations
# ---------------------------------------------------------------------------


def enqueue_job(
    db,
    job_type: str,
    payload: dict,
    rfq_id: int = None,
    workflow_id: int = None,
) -> Job:
    """
    Add a job to the queue for the worker to pick up.

    This is the standard way to trigger agent work. Agents don't call each
    other directly — they enqueue the next job and let the worker dispatch it.
    This keeps the pipeline loosely coupled and crash-safe.

    Args:
        db: SQLAlchemy session.
        job_type: What agent to run. One of: "extraction", "validation",
                  "quote_sheet", "matching".
        payload: Job-specific parameters as a dict. Common keys:
                 - message_id: for extraction and matching
                 - rfq_id: for validation and quote_sheet
        rfq_id: Optional RFQ this job relates to.
        workflow_id: Optional workflow FK for C1 enforcement.

    Returns:
        The newly created Job with status=PENDING.
    """
    job = Job(
        job_type=job_type,
        payload=payload,
        rfq_id=rfq_id,
        workflow_id=workflow_id,
        status=JobStatus.PENDING,
    )
    db.add(job)
    db.commit()
    db.refresh(job)

    logger.info("Job enqueued: id=%d type=%s rfq=%s", job.id, job_type, rfq_id)
    return job


def pick_next_job(db) -> Job:
    """
    Pick up the next pending job using SELECT ... FOR UPDATE SKIP LOCKED.

    This is the core of the Postgres job queue pattern. FOR UPDATE locks the
    row so no other worker picks it up. SKIP LOCKED means if a row is already
    locked by another worker, we skip it and get the next one. This enables
    safe concurrent processing without deadlocks.

    The job's status is set to RUNNING and started_at is set before returning.

    Args:
        db: SQLAlchemy session.

    Returns:
        The locked Job ready for processing, or None if no jobs are pending.
    """
    # Raw SQL for FOR UPDATE SKIP LOCKED — SQLAlchemy ORM doesn't have
    # native SKIP LOCKED support in all versions, and the raw query is
    # clearer about what's happening at the database level.
    result = db.execute(
        text(
            "SELECT id FROM jobs "
            "WHERE status = 'PENDING' "
            "ORDER BY created_at ASC "
            "LIMIT 1 "
            "FOR UPDATE SKIP LOCKED"
        )
    ).fetchone()

    if not result:
        return None

    job = db.query(Job).filter(Job.id == result[0]).first()
    job.status = JobStatus.RUNNING
    job.started_at = datetime.utcnow()
    db.commit()
    db.refresh(job)

    return job


def complete_job(db, job: Job) -> None:
    """Mark a job as successfully completed."""
    job.status = JobStatus.COMPLETED
    job.finished_at = datetime.utcnow()
    db.commit()
    logger.info("Job completed: id=%d type=%s", job.id, job.job_type)


def sweep_stale_jobs(db, timeout_seconds: int = None) -> int:
    """
    Find RUNNING jobs that have been stuck too long and re-queue or fail them.

    This is the recovery mechanism for jobs that were interrupted by worker
    crashes, OOM kills, Render redeploys, or wedged LLM calls. Without this,
    a single stuck job blocks the entire pipeline (see #296).

    Recovery logic:
    - Any job in RUNNING state with started_at older than the cutoff is
      considered abandoned.
    - If retry_count < max_retries: reset to PENDING (will be re-dispatched)
    - Otherwise: mark as FAILED (moved to dead-letter queue)

    Runs at the start of every cycle (with STALE_JOB_TIMEOUT) AND on worker
    startup (with timeout_seconds=0, meaning ALL RUNNING jobs are orphaned).

    Args:
        db: SQLAlchemy session.
        timeout_seconds: How old a RUNNING job must be to count as stale.
                         Defaults to STALE_JOB_TIMEOUT. Pass 0 for aggressive
                         recovery (all RUNNING jobs) — used on startup since
                         if the worker is booting, any RUNNING job is orphaned.

    Returns:
        Number of stale jobs recovered.
    """
    if timeout_seconds is None:
        timeout_seconds = STALE_JOB_TIMEOUT
    cutoff = datetime.utcnow() - timedelta(seconds=timeout_seconds)
    stale = (
        db.query(Job)
        .filter(Job.status == JobStatus.RUNNING)
        .filter(Job.started_at < cutoff)
        .all()
    )

    if not stale:
        return 0

    recovered = 0
    for job in stale:
        age_sec = (datetime.utcnow() - job.started_at).total_seconds()
        job.retry_count += 1

        if job.retry_count < job.max_retries:
            # Re-queue — likely transient (redeploy, transient network)
            job.status = JobStatus.PENDING
            job.started_at = None
            job.error_message = (
                f"Stale recovery {job.retry_count}/{job.max_retries}: "
                f"abandoned after {age_sec:.0f}s in RUNNING state"
            )
            logger.warning(
                "Stale job %d (%s) recovered after %.0fs — re-queued (retry %d/%d)",
                job.id, job.job_type, age_sec, job.retry_count, job.max_retries,
            )
        else:
            # Permanently failed — give up
            job.status = JobStatus.FAILED
            job.finished_at = datetime.utcnow()
            job.error_message = (
                f"Permanently failed after {job.max_retries} stale recovery attempts "
                f"(last run {age_sec:.0f}s stale)"
            )
            logger.error(
                "Stale job %d (%s) permanently failed after %d retries",
                job.id, job.job_type, job.max_retries,
            )

        recovered += 1

    db.commit()
    return recovered


def fail_job(db, job: Job, error: str) -> None:
    """
    Mark a job as failed. If retries remain, re-queue it as pending.

    Retry logic: if retry_count < max_retries, set status back to PENDING
    and increment retry_count. Otherwise, set status to FAILED permanently.
    """
    job.retry_count += 1

    if job.retry_count < job.max_retries:
        # Re-queue for retry
        job.status = JobStatus.PENDING
        job.started_at = None
        job.error_message = f"Retry {job.retry_count}/{job.max_retries}: {error}"
        logger.warning(
            "Job %d failed (retry %d/%d): %s",
            job.id, job.retry_count, job.max_retries, error,
        )
    else:
        # Permanently failed
        job.status = JobStatus.FAILED
        job.finished_at = datetime.utcnow()
        job.error_message = error
        logger.error(
            "Job %d permanently failed after %d retries: %s",
            job.id, job.max_retries, error,
        )

    db.commit()


# ---------------------------------------------------------------------------
# Job dispatch — routes job_type to the right agent/service
# ---------------------------------------------------------------------------

# Job type -> (module_path, function_name, payload_key_for_db_id)
# The dispatch table maps job types to the agent functions they should call.
# Each agent function takes (db, some_id) as arguments.
JOB_DISPATCH = {
    "extraction": ("backend.agents.extraction", "extract_rfq", "message_id"),
    "validation": ("backend.agents.validation", "draft_followup", "rfq_id"),
    "quote_sheet": ("backend.agents.quote_sheet", "generate_quote_sheet", "rfq_id"),
    "matching": ("backend.services.message_matching", "match_message_to_rfq", "message_id"),
    # Outbound email sending (#25) — only runs after C2 approval gate
    "send_outbound_email": ("backend.services.email_send", "send_approved_email", "approval_id"),
    # Carrier bid parsing (#33) — extracts structured bids from carrier reply emails
    "parse_carrier_bid": ("backend.agents.carrier_bid_parser", "parse_carrier_bid", "message_id"),
    # Quote response classification (#160) — classifies customer reply as accepted/rejected/question
    "quote_response": ("backend.agents.quote_response", "handle_quote_response", "message_id"),
}


def dispatch_job(db, job: Job) -> None:
    """
    Route a job to the appropriate agent function.

    Looks up the job_type in the dispatch table, imports the module,
    calls the function with the appropriate ID from the payload.

    Args:
        db: SQLAlchemy session.
        job: The job to dispatch (must have status=RUNNING).

    Raises:
        ValueError: If the job_type is not recognized.
        KeyError: If the required payload key is missing.
    """
    if job.job_type not in JOB_DISPATCH:
        raise ValueError(f"Unknown job type: {job.job_type}")

    module_path, func_name, payload_key = JOB_DISPATCH[job.job_type]

    # Get the ID from the payload
    target_id = job.payload.get(payload_key)
    if target_id is None:
        raise KeyError(f"Job payload missing required key '{payload_key}'")

    # Lazy import — only load the agent module when we need it.
    # This avoids importing all agents at worker startup.
    import importlib
    module = importlib.import_module(module_path)
    func = getattr(module, func_name)

    logger.info(
        "Dispatching job %d: %s.%s(%s=%d)",
        job.id, module_path, func_name, payload_key, target_id,
    )

    func(db, target_id)


# ---------------------------------------------------------------------------
# C1 enforcement — workflow enable/disable check
# ---------------------------------------------------------------------------


def is_workflow_enabled(db, workflow_id: int) -> bool:
    """
    Check if a specific workflow is enabled (C1).

    If the job has no workflow_id, we allow it — system-level jobs
    (like manual triggers) aren't gated by workflow toggles.
    """
    if workflow_id is None:
        return True

    workflow = db.query(Workflow).filter(Workflow.id == workflow_id).first()
    if not workflow:
        return True  # Workflow not found — allow (don't block on missing config)

    return workflow.enabled


def any_workflows_enabled(db) -> bool:
    """
    Check if ANY workflow is enabled. If none are, the kill switch is active.

    Used by the worker to decide whether to even poll for jobs.
    """
    return db.query(Workflow).filter(Workflow.enabled.is_(True)).count() > 0


def is_auto_send_enabled(db, workflow_name: str) -> bool:
    """
    Check if a workflow's auto-send is enabled (#154).

    When enabled, outbound emails for that workflow skip the approval queue
    and send automatically. When disabled, drafts go to pending_approval
    for broker review (original C2 behavior).

    Workflow name mapping:
        "Follow-up Automation"     — clarification follow-ups to shippers
        "Carrier Distribution"     — carrier RFQ emails
        "Inbound Quote Processing" — customer quote emails
    """
    workflow = db.query(Workflow).filter(Workflow.name == workflow_name).first()
    if not workflow:
        return False  # No workflow found — default to requiring approval
    return workflow.enabled


# ---------------------------------------------------------------------------
# Main worker loop
# ---------------------------------------------------------------------------


def process_cycle(db) -> int:
    """
    Process one cycle of jobs from the queue.

    Picks up to MAX_JOBS_PER_CYCLE pending jobs and dispatches them.
    Returns the number of jobs processed.

    Before picking up new work, sweeps any stale RUNNING jobs (#296) so a
    crashed worker or wedged LLM call doesn't block the pipeline forever.

    This is extracted from run_worker() so it can be tested independently.
    """
    # Recover any stuck jobs from a previous crash or wedge (#296)
    recovered = sweep_stale_jobs(db)
    if recovered > 0:
        logger.info("Sweep recovered %d stale job(s)", recovered)

    processed = 0

    for _ in range(MAX_JOBS_PER_CYCLE):
        job = pick_next_job(db)
        if not job:
            break  # No more pending jobs

        # C1: Check if the workflow is still enabled before processing
        if not is_workflow_enabled(db, job.workflow_id):
            logger.info(
                "Job %d skipped — workflow %d is disabled (C1)",
                job.id, job.workflow_id,
            )
            # Put it back as pending — it'll be picked up if the workflow is re-enabled
            job.status = JobStatus.PENDING
            job.started_at = None
            db.commit()
            continue

        try:
            dispatch_job(db, job)
            complete_job(db, job)
            processed += 1
        except Exception as e:
            fail_job(db, job, str(e))

    return processed


def poll_mailbox(db) -> int:
    """
    Check all configured mailboxes for new emails and ingest them (#48).

    Reads active mailboxes from the database first. Falls back to env-var
    config if no database mailboxes exist (backwards compatibility).

    New messages are persisted and matching jobs are enqueued for the
    process_cycle to pick up. Returns the total number of new messages ingested.

    This runs at the start of each worker cycle, before job processing.
    """
    try:
        from backend.services.email_ingestion import get_providers_from_db, ingest_new_messages
        providers = get_providers_from_db(db)
        total = 0
        for provider in providers:
            try:
                messages = ingest_new_messages(db, provider)
                total += len(messages)
            except Exception:
                logger.exception("Poll failed for %s provider — will retry next cycle", provider.get_provider_name())
        return total
    except Exception:
        logger.exception("Mailbox poll failed — will retry next cycle")
        return 0


def run_worker():
    """
    Main worker loop — runs indefinitely.

    Each cycle:
    1. Sweep stale RUNNING jobs (recover from previous crashes)
    2. Poll the mailbox for new emails (creates matching jobs)
    3. Process pending jobs from the queue (dispatches agents)
    4. Sleep before next cycle

    All state lives in Postgres (FR-WK-2), so the worker can crash and
    restart without losing work.
    """
    logger.info(
        "Golteris worker starting — poll_interval=%ds, max_jobs_per_cycle=%d, stale_timeout=%ds",
        POLL_INTERVAL, MAX_JOBS_PER_CYCLE, STALE_JOB_TIMEOUT,
    )

    # Startup recovery — any job left RUNNING from a previous worker
    # instance (crash, redeploy) gets re-queued before we start polling.
    # timeout_seconds=0 means ALL RUNNING jobs, since if we're booting,
    # any job in RUNNING state is definitionally orphaned.
    try:
        startup_db = SessionLocal()
        recovered = sweep_stale_jobs(startup_db, timeout_seconds=0)
        if recovered > 0:
            logger.warning(
                "Startup recovery — re-queued %d stale job(s) from previous worker",
                recovered,
            )
        startup_db.close()
    except Exception:
        logger.exception("Startup stale-job sweep failed — continuing anyway")

    while True:
        db = SessionLocal()
        try:
            # Step 1: Poll mailbox for new emails
            ingested = poll_mailbox(db)
            if ingested > 0:
                logger.info("Mailbox poll — ingested %d new messages", ingested)

            # Step 2: Process pending jobs (including newly enqueued matching jobs)
            processed = process_cycle(db)
            if processed > 0:
                logger.info("Cycle complete — processed %d jobs", processed)
        except Exception:
            logger.exception("Worker cycle error — will retry next cycle")
        finally:
            db.close()

        time.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    run_worker()
