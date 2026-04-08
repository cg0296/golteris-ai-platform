"""
backend/api/metrics.py — Observability metrics and alerts API (#52).

Endpoints:
    GET /api/metrics   — System metrics: call counts, error rates, cost, latency
    GET /api/alerts    — Active alerts: cost cap warnings, error spikes, queue backup

These power the Agent page's observability cards and can be consumed by
external monitoring tools.

Cross-cutting constraints:
    NFR-OB-4 — Metrics cover call count, error rate, p95 latency, cost per day
    C5 — Cost monitored and alerted
"""

import logging
import os
from datetime import datetime, timedelta
from decimal import Decimal

from fastapi import APIRouter, Depends
from sqlalchemy import func, text
from sqlalchemy.orm import Session

from backend.db.database import get_db
from backend.db.models import AgentCall, AgentRun, AgentRunStatus, Job, JobStatus

logger = logging.getLogger("golteris.api.metrics")

router = APIRouter(prefix="/api", tags=["observability"])


@router.get("/metrics")
def get_metrics(db: Session = Depends(get_db)):
    """
    Return system-wide metrics computed from agent_calls, agent_runs, and jobs.

    Metrics cover the last 24 hours unless otherwise noted.
    Used by the Agent page observability cards and external monitoring.
    """
    now = datetime.utcnow()
    day_ago = now - timedelta(hours=24)
    week_ago = now - timedelta(days=7)

    # --- Agent call metrics (last 24h) ---
    calls_today = db.query(func.count(AgentCall.id)).filter(
        AgentCall.started_at >= day_ago
    ).scalar() or 0

    calls_failed = db.query(func.count(AgentCall.id)).filter(
        AgentCall.started_at >= day_ago,
        AgentCall.status == "failed",
    ).scalar() or 0

    error_rate = round(calls_failed / calls_today * 100, 1) if calls_today > 0 else 0.0

    # Cost today (sum of all agent calls in last 24h)
    cost_today = db.query(func.sum(AgentCall.cost_usd)).filter(
        AgentCall.started_at >= day_ago
    ).scalar() or Decimal("0")

    # Cost this week
    cost_week = db.query(func.sum(AgentCall.cost_usd)).filter(
        AgentCall.started_at >= week_ago
    ).scalar() or Decimal("0")

    # Average latency (last 24h calls with duration)
    avg_latency = db.query(func.avg(AgentCall.duration_ms)).filter(
        AgentCall.started_at >= day_ago,
        AgentCall.duration_ms.isnot(None),
    ).scalar()

    # P95 latency approximation — get the 95th percentile duration
    p95_latency = None
    try:
        result = db.execute(text("""
            SELECT duration_ms FROM agent_calls
            WHERE started_at >= :since AND duration_ms IS NOT NULL
            ORDER BY duration_ms ASC
            OFFSET (SELECT GREATEST(0, COUNT(*) * 95 / 100 - 1) FROM agent_calls WHERE started_at >= :since AND duration_ms IS NOT NULL)
            LIMIT 1
        """), {"since": day_ago})
        row = result.fetchone()
        if row:
            p95_latency = row[0]
    except Exception:
        db.rollback()  # Clean up failed transaction

    # --- Run metrics ---
    runs_today = db.query(func.count(AgentRun.id)).filter(
        AgentRun.started_at >= day_ago
    ).scalar() or 0

    runs_failed = db.query(func.count(AgentRun.id)).filter(
        AgentRun.started_at >= day_ago,
        AgentRun.status == AgentRunStatus.FAILED,
    ).scalar() or 0

    # --- Job queue metrics ---
    jobs_pending = db.query(func.count(Job.id)).filter(
        Job.status == JobStatus.PENDING
    ).scalar() or 0

    jobs_running = db.query(func.count(Job.id)).filter(
        Job.status == JobStatus.RUNNING
    ).scalar() or 0

    jobs_failed_24h = db.query(func.count(Job.id)).filter(
        Job.status == JobStatus.FAILED,
        Job.created_at >= day_ago,
    ).scalar() or 0

    return {
        "period": "24h",
        "calls": {
            "total": calls_today,
            "failed": calls_failed,
            "error_rate_pct": error_rate,
        },
        "cost": {
            "today_usd": float(cost_today),
            "week_usd": float(cost_week),
        },
        "latency": {
            "avg_ms": round(float(avg_latency), 1) if avg_latency else None,
            "p95_ms": float(p95_latency) if p95_latency else None,
        },
        "runs": {
            "total": runs_today,
            "failed": runs_failed,
        },
        "queue": {
            "pending": jobs_pending,
            "running": jobs_running,
            "failed_24h": jobs_failed_24h,
        },
    }


@router.get("/alerts")
def get_alerts(db: Session = Depends(get_db)):
    """
    Return active alerts based on current system state.

    Checks for:
    - Cost cap approaching (>80% of daily or monthly limit)
    - Error rate spike (>10% in last hour)
    - Queue backup (>20 pending jobs)
    - Stale running jobs (started >10 minutes ago)
    """
    now = datetime.utcnow()
    hour_ago = now - timedelta(hours=1)
    day_ago = now - timedelta(hours=24)

    alerts = []

    # --- Cost cap alert ---
    daily_cap = float(os.environ.get("LLM_DAILY_CAP_USD", "10.0"))
    monthly_cap = float(os.environ.get("LLM_MONTHLY_CAP_USD", "300.0"))

    cost_today = float(db.query(func.sum(AgentCall.cost_usd)).filter(
        AgentCall.started_at >= day_ago
    ).scalar() or 0)

    cost_month = float(db.query(func.sum(AgentCall.cost_usd)).filter(
        AgentCall.started_at >= now.replace(day=1, hour=0, minute=0, second=0)
    ).scalar() or 0)

    if daily_cap > 0 and cost_today >= daily_cap * 0.8:
        pct = round(cost_today / daily_cap * 100, 1)
        alerts.append({
            "type": "cost",
            "severity": "critical" if cost_today >= daily_cap else "warning",
            "message": f"Daily cost at {pct}% of cap (${cost_today:.2f} / ${daily_cap:.2f})",
        })

    if monthly_cap > 0 and cost_month >= monthly_cap * 0.8:
        pct = round(cost_month / monthly_cap * 100, 1)
        alerts.append({
            "type": "cost",
            "severity": "critical" if cost_month >= monthly_cap else "warning",
            "message": f"Monthly cost at {pct}% of cap (${cost_month:.2f} / ${monthly_cap:.2f})",
        })

    # --- Error rate alert (last hour) ---
    calls_hour = db.query(func.count(AgentCall.id)).filter(
        AgentCall.started_at >= hour_ago
    ).scalar() or 0

    failed_hour = db.query(func.count(AgentCall.id)).filter(
        AgentCall.started_at >= hour_ago,
        AgentCall.status == "failed",
    ).scalar() or 0

    if calls_hour >= 5 and failed_hour / calls_hour > 0.1:
        rate = round(failed_hour / calls_hour * 100, 1)
        alerts.append({
            "type": "errors",
            "severity": "warning",
            "message": f"Error rate spike: {rate}% in the last hour ({failed_hour}/{calls_hour} calls failed)",
        })

    # --- Queue backup alert ---
    pending = db.query(func.count(Job.id)).filter(
        Job.status == JobStatus.PENDING
    ).scalar() or 0

    if pending > 20:
        alerts.append({
            "type": "queue",
            "severity": "warning",
            "message": f"Queue backup: {pending} jobs pending",
        })

    # --- Stale jobs alert ---
    stale_cutoff = now - timedelta(minutes=10)
    stale_count = db.query(func.count(Job.id)).filter(
        Job.status == JobStatus.RUNNING,
        Job.started_at < stale_cutoff,
    ).scalar() or 0

    if stale_count > 0:
        alerts.append({
            "type": "stale_jobs",
            "severity": "warning",
            "message": f"{stale_count} job(s) running for >10 minutes — may be stuck",
        })

    return {
        "alerts": alerts,
        "total": len(alerts),
        "checked_at": now.isoformat(),
    }
