"""
backend/tenant.py — Multi-tenant context and scoping (#55).

Provides the org_id context for the current request and a helper
to scope database queries to the current tenant.

The org_id is extracted from the authenticated user's organization
and stored in a contextvar. All business queries should use
`scope_to_org()` to filter by org_id.

Cross-cutting constraints:
    NFR-SE-4 — org_id on every row, app-level enforcement
    C6 → C6 says single-tenant for v1; this implements the v2 multi-tenant layer
"""

import logging
from contextvars import ContextVar
from typing import Optional

from sqlalchemy.orm import Session, Query

logger = logging.getLogger("golteris.tenant")

# Context variable holding the current request's org_id
current_org_id: ContextVar[Optional[int]] = ContextVar("current_org_id", default=None)


def set_current_org(org_id: Optional[int]) -> None:
    """Set the current organization context (called by auth middleware)."""
    current_org_id.set(org_id)


def get_current_org() -> Optional[int]:
    """Get the current organization ID from context."""
    return current_org_id.get(None)


def scope_to_org(query: Query, model_class) -> Query:
    """
    Filter a SQLAlchemy query to the current tenant's data.

    If org_id is set in the context and the model has an org_id column,
    adds a WHERE org_id = :current_org_id filter. If no org is set
    (single-tenant mode or system operations), returns the query unchanged.

    Usage:
        query = scope_to_org(db.query(RFQ), RFQ)

    Args:
        query: The SQLAlchemy query to scope
        model_class: The model class being queried (must have org_id column)

    Returns:
        The filtered query (or unchanged if no org context)
    """
    org_id = get_current_org()
    if org_id is not None and hasattr(model_class, "org_id"):
        return query.filter(model_class.org_id == org_id)
    return query
