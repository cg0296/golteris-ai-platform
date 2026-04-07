"""
backend/services/bid_ranking.py — Carrier bid comparison and ranking (#34).

Takes all carrier bids for an RFQ, normalizes them to comparable total
landed costs, ranks them, identifies the best value, and flags outliers.

The broker sees the ranked list in the RFQ detail drawer with "Best Value",
"Runner Up", and "Outlier" badges to speed up decision-making.

Ranking logic:
    1. Normalize all bids to total USD amount (handle rate_type variations)
    2. Sort by normalized rate ascending (cheapest first)
    3. Tag #1 as "Best Value", #2-3 as "Runner Up"
    4. Flag bids >30% above median as "Outlier (high)"
    5. Flag bids >30% below median as "Outlier (low)" — suspiciously cheap

Called by:
    backend/api/carriers.py GET /api/rfqs/{id}/bids
"""

import logging
from dataclasses import dataclass
from decimal import Decimal
from statistics import median
from typing import Optional

from sqlalchemy.orm import Session

from backend.db.models import CarrierBid, RFQ

logger = logging.getLogger("golteris.services.bid_ranking")

# Outlier threshold — bids more than 30% above/below median are flagged
OUTLIER_THRESHOLD = 0.30


@dataclass
class RankedBid:
    """A carrier bid with its ranking metadata."""
    bid: CarrierBid
    rank: int
    normalized_rate: float
    tag: str  # "best_value", "runner_up", "outlier_high", "outlier_low", or ""
    reason: str  # Human-readable explanation of the tag


def rank_bids(db: Session, rfq_id: int) -> list[RankedBid]:
    """
    Rank all carrier bids for an RFQ by total landed cost.

    Returns a list of RankedBid objects sorted cheapest-first, with
    tags identifying best value, runner ups, and outliers.

    Args:
        db: SQLAlchemy session
        rfq_id: The RFQ to rank bids for

    Returns:
        List of RankedBid objects, sorted by normalized_rate ascending.
        Empty list if no bids exist.
    """
    bids = (
        db.query(CarrierBid)
        .filter(CarrierBid.rfq_id == rfq_id, CarrierBid.rate.isnot(None))
        .order_by(CarrierBid.rate.asc())
        .all()
    )

    if not bids:
        return []

    # Normalize rates to comparable USD totals
    normalized = [(bid, _normalize_rate(bid)) for bid in bids]

    # Sort by normalized rate
    normalized.sort(key=lambda x: x[1])

    # Calculate median for outlier detection
    rates = [n for _, n in normalized]
    med = median(rates) if rates else 0

    # Build ranked list with tags
    ranked = []
    for i, (bid, norm_rate) in enumerate(normalized):
        rank = i + 1
        tag, reason = _compute_tag(rank, norm_rate, med, len(normalized))
        ranked.append(RankedBid(
            bid=bid,
            rank=rank,
            normalized_rate=norm_rate,
            tag=tag,
            reason=reason,
        ))

    return ranked


def _normalize_rate(bid: CarrierBid) -> float:
    """
    Normalize a bid rate to a comparable total USD amount.

    Handles different rate structures:
    - all_in / flat: rate is the total → use as-is
    - linehaul_plus_fsc: rate is base, assume ~15% FSC surcharge
    - per_mile: would need distance data (not available yet, use as-is)

    Returns the normalized rate as a float.
    """
    rate = float(bid.rate) if bid.rate else 0.0

    if bid.rate_type == "linehaul_plus_fsc":
        # Estimate FSC at ~15% of linehaul — this is a rough industry average
        rate *= 1.15
    # per_mile would need route distance — for now treat as-is
    # all_in and flat are already total rates

    return rate


def _compute_tag(
    rank: int,
    rate: float,
    median_rate: float,
    total_bids: int,
) -> tuple[str, str]:
    """
    Determine the display tag and reason for a ranked bid.

    Returns:
        Tuple of (tag, reason) where tag is one of:
        "best_value", "runner_up", "outlier_high", "outlier_low", or ""
    """
    if median_rate == 0:
        return ("", "")

    deviation = (rate - median_rate) / median_rate

    # Check for outliers first
    if deviation > OUTLIER_THRESHOLD:
        pct = abs(deviation) * 100
        return ("outlier_high", f"{pct:.0f}% above median — verify terms")
    if deviation < -OUTLIER_THRESHOLD and total_bids > 2:
        pct = abs(deviation) * 100
        return ("outlier_low", f"{pct:.0f}% below median — verify scope")

    # Tags for top 3
    if rank == 1:
        if total_bids == 1:
            return ("best_value", "Only bid received")
        return ("best_value", "Lowest total landed cost")
    if rank <= 3:
        return ("runner_up", f"#{rank} by total cost")

    return ("", "")
