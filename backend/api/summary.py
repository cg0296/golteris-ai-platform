"""
backend/api/summary.py — Daily summary API endpoints (#50).

Endpoints:
    GET  /api/summary/daily      — Preview today's summary as JSON
    POST /api/summary/daily/send — Trigger sending the summary email now

The daily summary is also triggered automatically by the worker scheduler
at 5 PM local time on weekdays (configurable in Settings).

Cross-cutting constraints:
    C2 — Summary email send uses the provider's send_message (audit trail)
    C3 — Summary text uses plain English, no agent jargon
"""

import logging

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from backend.db.database import get_db
from backend.services.daily_summary import generate_daily_summary, format_summary_email

logger = logging.getLogger("golteris.api.summary")

router = APIRouter(prefix="/api/summary", tags=["summary"])


@router.get("/daily")
def get_daily_summary(db: Session = Depends(get_db)):
    """
    Preview today's daily summary as JSON.

    Used by the frontend to show a preview before sending, and by
    tests to verify the summary numbers match the History tab.
    """
    summary = generate_daily_summary(db)
    subject, body = format_summary_email(summary)
    return {
        **summary,
        "email_preview": {
            "subject": subject,
            "body": body,
        },
    }


@router.post("/daily/send")
def send_daily_summary(db: Session = Depends(get_db)):
    """
    Trigger sending the daily summary email now.

    Sends to the broker's email address using the configured email provider.
    This is also called by the worker scheduler at 5 PM on weekdays.
    """
    summary = generate_daily_summary(db)
    subject, body = format_summary_email(summary)

    # Send via the configured email provider
    try:
        from backend.services.email_ingestion import get_provider_from_config
        provider = get_provider_from_config()

        # Send to the broker (Jillian) — in v2 this would come from user settings
        broker_email = "jillian@beltmann.com"
        result = provider.send_message(
            to=broker_email,
            subject=subject,
            body=body,
        )

        if result.get("success"):
            logger.info("Daily summary sent to %s", broker_email)
            return {"status": "ok", "message": f"Summary sent to {broker_email}"}
        else:
            error = result.get("error", "Unknown error")
            logger.error("Daily summary send failed: %s", error)
            return {"status": "error", "message": f"Send failed: {error}"}

    except Exception as e:
        logger.exception("Failed to send daily summary: %s", e)
        return {"status": "error", "message": str(e)}
