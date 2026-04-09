"""
backend/services/org_profile.py — Organization profile service (#174).

Single source of truth for company branding — name, sign-off, ref prefix.
Replaces all hardcoded "Beltmann Logistics" references throughout the system.

Every agent, email template, and UI component that needs the company name
should call get_org_profile() instead of using a hardcoded string.

The profile is stored in the organizations table's settings JSONB column.
If no org exists, falls back to the ORG_NAME environment variable or a
generic default so the system never crashes on missing config.

Called by:
    backend/services/broker_identity.py — email signature fallback
    backend/services/carrier_distribution.py — carrier RFQ emails
    backend/services/customer_quote.py — customer quote emails
    backend/agents/validation.py — follow-up emails
    backend/agents/quote_response.py — confirmation/close-out emails
    backend/agents/quote_sheet.py — reference ID prefix
    backend/api/chat.py — system prompt
    frontend via GET /api/org/profile
"""

import logging
import os
from functools import lru_cache
from typing import Optional

from sqlalchemy.orm import Session

from backend.db.models import Organization

logger = logging.getLogger("golteris.services.org_profile")

# Default values when no org is configured
DEFAULTS = {
    "company_name": "Your Brokerage",
    "sign_off": "Your Brokerage",
    "ref_prefix": "RFQ",
    "tagline": "Freight Brokerage",
}


def get_org_profile(db: Session) -> dict:
    """
    Get the organization's company profile for branding and emails.

    Returns a dict with:
        company_name: Full company name (e.g., "Beltmann Logistics")
        sign_off: Name used in email signatures (e.g., "Beltmann Logistics")
        ref_prefix: Quote sheet reference prefix (e.g., "BLT")
        tagline: Short description (e.g., "Freight Brokerage")

    Resolution order:
        1. First active organization's settings JSONB
        2. ORG_NAME environment variable (for company_name and sign_off)
        3. Hardcoded defaults
    """
    # Try to get from the database
    try:
        org = db.query(Organization).filter(Organization.active == True).first()
        if org:
            settings = org.settings or {}
            return {
                "company_name": settings.get("company_name", org.name),
                "sign_off": settings.get("sign_off", org.name),
                "ref_prefix": settings.get("ref_prefix", _derive_prefix(org.name)),
                "tagline": settings.get("tagline", DEFAULTS["tagline"]),
                "org_id": org.id,
                "org_name": org.name,
            }
    except Exception as e:
        logger.warning("Could not load org profile from DB: %s", e)

    # Fallback to environment variable
    env_name = os.environ.get("ORG_NAME")
    if env_name:
        return {
            "company_name": env_name,
            "sign_off": env_name,
            "ref_prefix": _derive_prefix(env_name),
            "tagline": DEFAULTS["tagline"],
            "org_id": None,
            "org_name": env_name,
        }

    # Final fallback
    return {**DEFAULTS, "org_id": None, "org_name": DEFAULTS["company_name"]}


def get_company_name(db: Session) -> str:
    """Shortcut — just the company name string."""
    return get_org_profile(db)["company_name"]


def get_sign_off(db: Session) -> str:
    """Shortcut — just the email sign-off string."""
    return get_org_profile(db)["sign_off"]


def get_ref_prefix(db: Session) -> str:
    """Shortcut — just the quote sheet reference prefix."""
    return get_org_profile(db)["ref_prefix"]


def _derive_prefix(name: str) -> str:
    """
    Derive a 3-letter prefix from a company name.
    "Beltmann Logistics" → "BLT", "Golden Transport" → "GLT"
    """
    words = name.split()
    if len(words) >= 2:
        return (words[0][0] + words[0][1] + words[1][0]).upper()
    elif len(name) >= 3:
        return name[:3].upper()
    return "RFQ"
