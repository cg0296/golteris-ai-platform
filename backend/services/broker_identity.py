"""
backend/services/broker_identity.py — Shared broker name resolution (#172).

Single source of truth for determining the broker's name in outbound emails.
Replaces 5 duplicate _get_broker_name functions scattered across agents/services.

Resolution order:
1. If resolved_by is a user email → look up that user's name
2. Prefer admin/owner role users (the active operator)
3. Fall back to any active user
4. Fall back to "Beltmann Logistics"

Called by:
    backend/agents/validation.py — follow-up email signatures
    backend/agents/quote_response.py — acceptance/rejection email signatures
    backend/services/carrier_distribution.py — carrier RFQ signatures
    backend/services/customer_quote.py — customer quote signatures
    backend/services/email_send.py — outbound message sender field
"""

import logging
from typing import Optional

from sqlalchemy.orm import Session

logger = logging.getLogger("golteris.services.broker_identity")


def get_broker_name(db: Session, resolved_by: Optional[str] = None) -> str:
    """
    Get the broker's first name for outbound email signatures.

    Args:
        db: SQLAlchemy session.
        resolved_by: Optional user email from approval resolution (#159).
                     If provided and matches a user, that user's name is used.

    Returns:
        First name of the broker (e.g., "Curt"), or "Beltmann Logistics" as fallback.
    """
    from backend.db.models import User

    # 1. If resolved_by is a real user email, use that user's name
    if resolved_by and resolved_by not in ("broker", "auto_send"):
        try:
            user = db.query(User).filter(User.email == resolved_by).first()
            if user and user.name:
                return user.name.split()[0]
        except Exception:
            pass

    # 2. Prefer admin/owner — they're the active operator
    try:
        user = (
            db.query(User)
            .filter(User.active == True, User.role.in_(["admin", "owner"]))
            .order_by(User.id.desc())
            .first()
        )
        if user and user.name:
            return user.name.split()[0]
    except Exception:
        pass

    # 3. Any active user
    try:
        user = db.query(User).filter(User.active == True).order_by(User.id.desc()).first()
        if user and user.name:
            return user.name.split()[0]
    except Exception:
        pass

    # 4. Fallback — use org profile instead of hardcoded name (#174)
    try:
        from backend.services.org_profile import get_sign_off
        return get_sign_off(db)
    except Exception:
        return "Your Brokerage"
