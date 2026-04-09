"""
backend/services/ref_number.py — Smart RFQ reference number generator (#176).

Generates reference numbers in the format YYYYMMDD-HHMM-NNN where:
    YYYYMMDD = creation date
    HHMM = creation time (hour + minute)
    NNN = daily sequence number (001, 002, etc.)

Example: 20260409-1433-001

Called by:
    backend/agents/extraction.py — when creating a new RFQ
    backend/api/chat.py — when chat agent creates an RFQ
    backend/api/dev.py — when reseeding demo data
"""

import logging
from datetime import datetime

from sqlalchemy import func
from sqlalchemy.orm import Session

from backend.db.models import RFQ

logger = logging.getLogger("golteris.services.ref_number")


def generate_ref_number(db: Session, created_at: datetime | None = None) -> str:
    """
    Generate a smart reference number for a new RFQ.

    Format: YYYYMMDD-HHMM-NNN
    - Date and time from created_at (defaults to now)
    - NNN is the daily sequence: count of RFQs created today + 1

    Args:
        db: SQLAlchemy session.
        created_at: Optional timestamp (defaults to utcnow).

    Returns:
        Reference number string like "20260409-1433-001".
    """
    now = created_at or datetime.utcnow()
    date_str = now.strftime("%Y%m%d")
    time_str = now.strftime("%H%M")

    # Count RFQs created today to get the daily sequence number
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    today_count = (
        db.query(func.count(RFQ.id))
        .filter(RFQ.created_at >= today_start)
        .scalar()
    ) or 0

    seq = today_count + 1
    ref = f"{date_str}-{time_str}-{seq:03d}"

    logger.debug("Generated ref number: %s (daily seq %d)", ref, seq)
    return ref
