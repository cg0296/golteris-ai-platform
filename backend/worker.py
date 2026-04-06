"""
backend/worker.py — Background worker entry point.

This is the long-running process that handles:
1. Mailbox polling — checks for new emails on a cron schedule (#12, #47)
2. Job queue processing — picks up jobs from the Postgres queue using
   SELECT ... FOR UPDATE SKIP LOCKED (#47)
3. Delayed job firing — nudge timers, reminders, follow-up deadlines (#32)

This file is a placeholder scaffold. The real implementation will be built
by issue #47 (Build worker process and scheduler). For now, it:
- Connects to the database
- Logs that it's running
- Sleeps in a loop (so the Render worker process stays alive)

The worker runs as a separate process from the web server. On Render, it's
defined as a Background Worker in render.yaml. Locally, run it with:
    python -m backend.worker

Cross-cutting constraints relevant here:
    C1 — The worker MUST check workflows.enabled before dispatching any job.
         If a workflow is disabled, the worker skips it. The kill switch
         (all workflows disabled) effectively pauses the worker.
    C5 — Before making any LLM API call, the worker must check the daily
         cost cap. If the cap is reached, no further calls are made.

See REQUIREMENTS.md §6.8 (FR-WK-1 through FR-WK-3) for formal requirements.
"""

import logging
import os
import sys
import time

# Add the project root to the Python path so imports work when running
# as `python -m backend.worker` from the project root.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from backend.db.database import SessionLocal  # noqa: E402
from backend.db.models import Workflow  # noqa: E402

# Configure logging — structured JSON logs will be added by #52 (observability).
# For now, use a simple format that includes timestamps.
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(name)s — %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("golteris.worker")

# How often the worker checks for new jobs (in seconds).
# The mailbox poller runs on its own schedule inside this loop.
POLL_INTERVAL = int(os.environ.get("WORKER_POLL_INTERVAL", "10"))


def check_enabled_workflows():
    """
    Query the database for workflows that are currently enabled.

    C1 enforcement: the worker only processes jobs for enabled workflows.
    If no workflows are enabled (kill switch active), this returns an empty list
    and the worker effectively idles.

    Returns:
        List of workflow names that are currently enabled.
    """
    db = SessionLocal()
    try:
        enabled = db.query(Workflow).filter(Workflow.enabled.is_(True)).all()
        return [w.name for w in enabled]
    finally:
        db.close()


def run_worker():
    """
    Main worker loop.

    Runs indefinitely, checking for enabled workflows and processing jobs.
    The worker survives crashes because all state lives in Postgres — nothing
    is held in memory across iterations (FR-WK-2).

    This is a placeholder — the real job processing logic will be added by #47.
    """
    logger.info("Golteris worker starting — poll interval: %ds", POLL_INTERVAL)

    while True:
        try:
            # C1: Only process jobs for enabled workflows
            enabled_workflows = check_enabled_workflows()

            if enabled_workflows:
                logger.info(
                    "Enabled workflows: %s — checking for jobs...",
                    ", ".join(enabled_workflows),
                )
                # TODO (#47): Implement job queue processing here.
                # The pattern is:
                #   1. SELECT ... FOR UPDATE SKIP LOCKED from a jobs table
                #   2. Dispatch the job to the appropriate agent
                #   3. Update job status on completion or failure
                #   4. Roll up cost/tokens to the parent agent_run
            else:
                # Kill switch active or no workflows configured — idle quietly.
                # Log at DEBUG to avoid spamming in production.
                logger.debug("No enabled workflows — idling.")

        except Exception:
            # Log the error but don't crash — the worker must survive failures.
            # Real error handling (retries, DLQ) will be added by #51.
            logger.exception("Worker loop error — will retry next cycle")

        # Sleep before the next poll. All state is in Postgres, so sleeping
        # is safe — we won't miss anything, just pick it up next cycle.
        time.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    run_worker()
