"""
backend/services/daily_summary.py — End-of-day summary email (#50).

Generates a summary of what Golteris handled today and calculates time
saved versus the manual baseline. The broker forwards this to their boss
as proof of value.

Summary includes:
    - Emails ingested
    - RFQs created / extracted
    - Drafts approved and sent
    - Carriers contacted
    - Quotes generated
    - Items flagged for review
    - Estimated time saved (based on agent run durations vs manual baseline)

Called by:
    - The worker scheduler at 5 PM local time on weekdays
    - The /api/summary/daily/send endpoint for manual triggers
    - The /api/summary/daily endpoint for preview (JSON)

Cross-cutting constraints:
    C2 — Summary email send still goes through the approval-aware provider
    C3 — Plain English, no agent jargon
    FR-UI-10 — Time saved must be defensible against a manual baseline
"""

import logging
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Optional

from sqlalchemy import func
from sqlalchemy.orm import Session

from backend.db.models import (
    AgentRun,
    AgentRunStatus,
    Approval,
    ApprovalStatus,
    AuditEvent,
    CarrierRfqSend,
    Message,
    MessageDirection,
    RFQ,
    ReviewQueue,
)

logger = logging.getLogger("golteris.services.daily_summary")

# Manual baseline estimates (minutes per task) — used for time saved calculation.
# These are defensible industry averages for a freight broker doing this work manually.
# See REQUIREMENTS.md FR-UI-10.
MANUAL_BASELINE_MINUTES = {
    "email_read_and_classify": 3,      # Reading and routing an inbound email
    "rfq_extraction": 8,               # Manually entering RFQ fields from email
    "draft_clarification": 5,          # Writing a follow-up email for missing info
    "carrier_rfq_distribution": 10,    # Sending RFQ to carriers one by one
    "quote_comparison": 15,            # Comparing carrier bids in a spreadsheet
    "customer_quote": 10,              # Packaging and sending a customer quote
}


def generate_daily_summary(db: Session, date: Optional[datetime] = None) -> dict:
    """
    Generate the daily summary data for a given date (defaults to today).

    Returns a dict with all summary metrics, formatted for both the JSON
    API response and the email template. Numbers should match the History tab.

    Args:
        db: SQLAlchemy session
        date: The date to summarize (defaults to today)

    Returns:
        Dict with summary sections: activity, time_saved, highlights
    """
    if date is None:
        date = datetime.utcnow()

    # Define the day's boundaries (midnight to midnight UTC)
    day_start = date.replace(hour=0, minute=0, second=0, microsecond=0)
    day_end = day_start + timedelta(days=1)

    # --- Activity counts ---

    # Emails ingested (inbound messages received today)
    emails_ingested = db.query(func.count(Message.id)).filter(
        Message.direction == MessageDirection.INBOUND,
        Message.received_at >= day_start,
        Message.received_at < day_end,
    ).scalar() or 0

    # RFQs created today
    rfqs_created = db.query(func.count(RFQ.id)).filter(
        RFQ.created_at >= day_start,
        RFQ.created_at < day_end,
    ).scalar() or 0

    # Drafts approved and sent today
    drafts_approved = db.query(func.count(Approval.id)).filter(
        Approval.status == ApprovalStatus.APPROVED,
        Approval.resolved_at >= day_start,
        Approval.resolved_at < day_end,
    ).scalar() or 0

    # Emails sent (outbound messages today)
    emails_sent = db.query(func.count(Message.id)).filter(
        Message.direction == MessageDirection.OUTBOUND,
        Message.created_at >= day_start,
        Message.created_at < day_end,
    ).scalar() or 0

    # Carrier RFQs distributed today
    carriers_contacted = db.query(func.count(CarrierRfqSend.id)).filter(
        CarrierRfqSend.created_at >= day_start,
        CarrierRfqSend.created_at < day_end,
    ).scalar() or 0

    # Items flagged for review today
    items_flagged = db.query(func.count(ReviewQueue.id)).filter(
        ReviewQueue.created_at >= day_start,
        ReviewQueue.created_at < day_end,
    ).scalar() or 0

    # Agent runs completed today
    runs_completed = db.query(func.count(AgentRun.id)).filter(
        AgentRun.status == AgentRunStatus.COMPLETED,
        AgentRun.started_at >= day_start,
        AgentRun.started_at < day_end,
    ).scalar() or 0

    # Total agent run duration today (milliseconds)
    total_run_duration_ms = db.query(func.sum(AgentRun.duration_ms)).filter(
        AgentRun.status == AgentRunStatus.COMPLETED,
        AgentRun.started_at >= day_start,
        AgentRun.started_at < day_end,
    ).scalar() or 0

    # Total LLM cost today
    total_cost = db.query(func.sum(AgentRun.total_cost_usd)).filter(
        AgentRun.started_at >= day_start,
        AgentRun.started_at < day_end,
    ).scalar() or Decimal("0")

    # --- Time saved calculation (FR-UI-10 — defensible) ---
    # Each automated task displaces a known amount of manual work.
    manual_minutes = (
        emails_ingested * MANUAL_BASELINE_MINUTES["email_read_and_classify"]
        + rfqs_created * MANUAL_BASELINE_MINUTES["rfq_extraction"]
        + drafts_approved * MANUAL_BASELINE_MINUTES["draft_clarification"]
        + carriers_contacted * MANUAL_BASELINE_MINUTES["carrier_rfq_distribution"]
        + emails_sent * MANUAL_BASELINE_MINUTES["customer_quote"]
    )

    # Agent processing time in minutes
    agent_minutes = round(total_run_duration_ms / 60000, 1) if total_run_duration_ms else 0

    # Net time saved
    time_saved_minutes = max(0, manual_minutes - agent_minutes)
    time_saved_hours = round(time_saved_minutes / 60, 1)

    return {
        "date": day_start.strftime("%A, %B %d, %Y"),
        "date_iso": day_start.isoformat(),
        "activity": {
            "emails_ingested": emails_ingested,
            "rfqs_created": rfqs_created,
            "drafts_approved": drafts_approved,
            "emails_sent": emails_sent,
            "carriers_contacted": carriers_contacted,
            "items_flagged": items_flagged,
            "agent_runs": runs_completed,
        },
        "time_saved": {
            "manual_estimate_minutes": manual_minutes,
            "agent_processing_minutes": agent_minutes,
            "net_saved_minutes": time_saved_minutes,
            "net_saved_hours": time_saved_hours,
        },
        "cost": {
            "total_usd": float(total_cost),
        },
    }


def format_summary_email(summary: dict) -> tuple[str, str]:
    """
    Format the daily summary as a plain-text email body and subject.

    Uses plain English per C3. Designed to be forwarded by the broker
    to their boss as a proof-of-value artifact.

    Args:
        summary: The dict returned by generate_daily_summary()

    Returns:
        Tuple of (subject, body) for the email.
    """
    date_str = summary["date"]
    act = summary["activity"]
    ts = summary["time_saved"]
    cost = summary["cost"]

    subject = f"Golteris Daily Summary — {date_str}"

    body = f"""Daily Summary — {date_str}

What Golteris handled today:

  Emails received:        {act['emails_ingested']}
  New quote requests:     {act['rfqs_created']}
  Drafts reviewed & sent: {act['drafts_approved']}
  Carriers contacted:     {act['carriers_contacted']}
  Outbound emails:        {act['emails_sent']}
  Items flagged:          {act['items_flagged']}
  Agent tasks completed:  {act['agent_runs']}

Time saved:

  Manual estimate:   {ts['manual_estimate_minutes']} minutes
  Agent processing:  {ts['agent_processing_minutes']} minutes
  Net time saved:    {ts['net_saved_minutes']} minutes ({ts['net_saved_hours']} hours)

Cost: ${cost['total_usd']:.2f}

View full details at your Golteris dashboard.

---
This is an automated daily summary from Golteris.
"""

    return subject, body
