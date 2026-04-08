"""
backend/api/metering.py — Usage metering API (#56, #57).

Endpoints:
    GET /api/metering/mailboxes  — Per-mailbox usage metrics (#56)
    GET /api/metering/quotes     — Per-quote volume metrics (#57)

These power usage-based billing in v2. Each endpoint returns current
and historical usage data suitable for Stripe metered billing.

Cross-cutting constraints:
    NFR-SE-4 — Scoped to organization (when multi-tenant is active)
"""

import logging
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends
from sqlalchemy import func
from sqlalchemy.orm import Session

from backend.db.database import get_db
from backend.db.models import Message, MessageDirection, RFQ, RFQState

logger = logging.getLogger("golteris.api.metering")

router = APIRouter(prefix="/api/metering", tags=["metering"])


@router.get("/mailboxes")
def get_mailbox_usage(db: Session = Depends(get_db)):
    """
    Per-mailbox usage metrics for seat-based billing (#56).

    Returns:
    - Total inbound messages (all time and this month)
    - Total outbound messages sent
    - Last activity timestamp
    - Active vs inactive mailbox status
    """
    now = datetime.utcnow()
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

    # Inbound messages this month
    inbound_month = db.query(func.count(Message.id)).filter(
        Message.direction == MessageDirection.INBOUND,
        Message.received_at >= month_start,
    ).scalar() or 0

    # Inbound messages all time
    inbound_total = db.query(func.count(Message.id)).filter(
        Message.direction == MessageDirection.INBOUND,
    ).scalar() or 0

    # Outbound messages this month
    outbound_month = db.query(func.count(Message.id)).filter(
        Message.direction == MessageDirection.OUTBOUND,
        Message.created_at >= month_start,
    ).scalar() or 0

    # Last activity
    last_inbound = db.query(func.max(Message.received_at)).filter(
        Message.direction == MessageDirection.INBOUND,
    ).scalar()

    # Messages per day (last 30 days) for the usage chart
    day_ago_30 = now - timedelta(days=30)
    daily_counts = db.query(
        func.date_trunc("day", Message.received_at).label("day"),
        func.count(Message.id).label("count"),
    ).filter(
        Message.direction == MessageDirection.INBOUND,
        Message.received_at >= day_ago_30,
    ).group_by("day").order_by("day").all()

    return {
        "period": "current_month",
        "inbound": {
            "this_month": inbound_month,
            "all_time": inbound_total,
        },
        "outbound": {
            "this_month": outbound_month,
        },
        "last_activity": last_inbound.isoformat() if last_inbound else None,
        "daily_inbound": [
            {"date": d.isoformat() if d else None, "count": c}
            for d, c in daily_counts
        ],
    }


@router.get("/quotes")
def get_quote_usage(db: Session = Depends(get_db)):
    """
    Per-quote volume metrics for usage-based billing (#57).

    Counts RFQs that have progressed past extraction (i.e., real quotes,
    not just raw emails). This is the billable unit.

    Returns:
    - Quotes this month
    - Quotes all time
    - Quotes by state
    - Monthly trend
    """
    now = datetime.utcnow()
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

    # Billable states — RFQs that have progressed past initial extraction
    billable_states = [
        RFQState.READY_TO_QUOTE,
        RFQState.WAITING_ON_CARRIERS,
        RFQState.QUOTES_RECEIVED,
        RFQState.WAITING_ON_BROKER,
        RFQState.QUOTE_SENT,
        RFQState.WON,
        RFQState.LOST,
        RFQState.CANCELLED,
    ]

    # Quotes this month (all RFQs created this month)
    quotes_month = db.query(func.count(RFQ.id)).filter(
        RFQ.created_at >= month_start,
    ).scalar() or 0

    # Billable quotes this month (progressed past extraction)
    billable_month = db.query(func.count(RFQ.id)).filter(
        RFQ.created_at >= month_start,
        RFQ.state.in_(billable_states),
    ).scalar() or 0

    # All time
    quotes_total = db.query(func.count(RFQ.id)).scalar() or 0

    # By state
    state_counts = db.query(
        RFQ.state, func.count(RFQ.id)
    ).group_by(RFQ.state).all()

    # Won/lost this month
    won_month = db.query(func.count(RFQ.id)).filter(
        RFQ.state == RFQState.WON,
        RFQ.closed_at >= month_start,
    ).scalar() or 0

    lost_month = db.query(func.count(RFQ.id)).filter(
        RFQ.state == RFQState.LOST,
        RFQ.closed_at >= month_start,
    ).scalar() or 0

    return {
        "period": "current_month",
        "quotes": {
            "this_month": quotes_month,
            "billable_this_month": billable_month,
            "all_time": quotes_total,
        },
        "outcomes": {
            "won": won_month,
            "lost": lost_month,
        },
        "by_state": {
            s.value: c for s, c in state_counts
        },
    }
