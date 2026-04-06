"""
backend/llm/cost_tracker.py — Tracks LLM spend against daily/monthly cost caps.

C5 enforcement: before every LLM call, `client.py` calls `check_cost_cap()`
to verify the daily and monthly spend limits haven't been exceeded. If they
have, `LLMCostCapExceeded` is raised and no call is made.

Cost caps are configured via environment variables:
    LLM_DAILY_COST_CAP  — max USD per day (default $20)
    LLM_MONTHLY_COST_CAP — max USD per month (default $100)

These apply across ALL providers combined (Anthropic + OpenAI + any others).
"""

import os
from datetime import datetime, timedelta
from decimal import Decimal

from sqlalchemy import func
from sqlalchemy.orm import Session

from backend.db.models import AgentCall
from backend.llm.provider import LLMCostCapExceeded


def get_daily_spend(db: Session) -> Decimal:
    """
    Sum of cost_usd for all agent_calls created today (UTC).

    Returns:
        Total spend today in USD as a Decimal.
    """
    today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    result = db.query(func.coalesce(func.sum(AgentCall.cost_usd), 0)).filter(
        AgentCall.started_at >= today_start
    ).scalar()
    return Decimal(str(result))


def get_monthly_spend(db: Session) -> Decimal:
    """
    Sum of cost_usd for all agent_calls created this calendar month (UTC).

    Returns:
        Total spend this month in USD as a Decimal.
    """
    month_start = datetime.utcnow().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    result = db.query(func.coalesce(func.sum(AgentCall.cost_usd), 0)).filter(
        AgentCall.started_at >= month_start
    ).scalar()
    return Decimal(str(result))


def get_cost_caps() -> tuple[Decimal, Decimal]:
    """
    Read cost caps from environment variables.

    Returns:
        (daily_cap, monthly_cap) as Decimals in USD.
        Falls back to $20/day and $100/month if not set.
    """
    # Support both old ANTHROPIC_ prefix and new LLM_ prefix for backwards compat
    daily = os.environ.get(
        "LLM_DAILY_COST_CAP",
        os.environ.get("ANTHROPIC_DAILY_COST_CAP", "20.00")
    )
    monthly = os.environ.get(
        "LLM_MONTHLY_COST_CAP",
        os.environ.get("ANTHROPIC_MONTHLY_COST_CAP", "100.00")
    )
    return Decimal(daily), Decimal(monthly)


def check_cost_cap(db: Session) -> None:
    """
    Check if the daily or monthly cost cap has been exceeded.

    C5 enforcement point — called before every LLM call in `client.py`.
    If either cap is exceeded, raises `LLMCostCapExceeded` and the call
    is not made.

    Args:
        db: SQLAlchemy session for querying agent_calls

    Raises:
        LLMCostCapExceeded: If daily or monthly cap is exceeded.
            The exception message includes the current spend and the cap,
            so operators can see exactly why the cap was hit.
    """
    daily_cap, monthly_cap = get_cost_caps()
    daily_spend = get_daily_spend(db)
    monthly_spend = get_monthly_spend(db)

    if daily_spend >= daily_cap:
        raise LLMCostCapExceeded(
            f"Daily LLM cost cap exceeded: ${daily_spend:.2f} spent today "
            f"(cap: ${daily_cap:.2f}). No further LLM calls until tomorrow."
        )

    if monthly_spend >= monthly_cap:
        raise LLMCostCapExceeded(
            f"Monthly LLM cost cap exceeded: ${monthly_spend:.2f} spent this month "
            f"(cap: ${monthly_cap:.2f}). No further LLM calls until next month."
        )
