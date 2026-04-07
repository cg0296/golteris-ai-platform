"""
backend/services/pricing.py — Pricing and markup engine (#35).

Applies markup rules to a selected carrier bid to generate a customer-facing
rate. The broker selects a carrier bid from the ranked list, the system
applies the configured margin, and produces a quoted amount for the customer.

Markup rules:
    1. Percentage margin (default 12%) — standard freight brokerage markup
    2. Minimum margin ($150) — ensures profitability on small loads
    3. Manual override — broker can set a custom rate with a reason (audited)

The quoted amount is stored on the RFQ record and used by the customer
quote generation agent (#36).

Called by:
    backend/api/carriers.py POST /api/rfqs/{id}/price
"""

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional

from sqlalchemy.orm import Session

from backend.db.models import (
    AuditEvent,
    CarrierBid,
    RFQ,
    RFQState,
)

logger = logging.getLogger("golteris.services.pricing")

# Default markup configuration — can be overridden per-customer in the future (#31)
DEFAULT_MARKUP_PERCENT = Decimal("0.12")   # 12% margin
MINIMUM_MARGIN_USD = Decimal("150.00")     # Floor: at least $150 profit per load


@dataclass
class PricingResult:
    """Result of applying markup to a carrier bid."""
    carrier_bid_id: int
    carrier_name: str
    carrier_rate: Decimal
    markup_percent: Decimal
    markup_amount: Decimal
    customer_rate: Decimal
    margin: Decimal
    is_manual_override: bool
    override_reason: Optional[str]


def calculate_customer_rate(
    db: Session,
    rfq_id: int,
    carrier_bid_id: int,
    manual_rate: Optional[Decimal] = None,
    override_reason: Optional[str] = None,
) -> PricingResult:
    """
    Apply markup to a carrier bid and produce a customer-facing rate.

    If manual_rate is provided, uses that instead of the calculated rate
    (broker override). The override is audited with the given reason.

    Args:
        db: SQLAlchemy session
        rfq_id: The RFQ being priced
        carrier_bid_id: The selected carrier bid to mark up
        manual_rate: Optional override — broker sets a custom price
        override_reason: Required if manual_rate is provided (audit trail)

    Returns:
        PricingResult with all pricing details.

    Raises:
        ValueError: If the RFQ or bid is not found.
    """
    rfq = db.query(RFQ).filter(RFQ.id == rfq_id).first()
    if not rfq:
        raise ValueError(f"RFQ {rfq_id} not found")

    bid = db.query(CarrierBid).filter(
        CarrierBid.id == carrier_bid_id,
        CarrierBid.rfq_id == rfq_id,
    ).first()
    if not bid or not bid.rate:
        raise ValueError(f"Carrier bid {carrier_bid_id} not found for RFQ {rfq_id}")

    carrier_rate = bid.rate
    is_override = manual_rate is not None

    if is_override:
        # Broker manually set the customer rate
        customer_rate = manual_rate
        margin = customer_rate - carrier_rate
        markup_amount = margin
        markup_percent = (margin / carrier_rate * 100) if carrier_rate > 0 else Decimal("0")
    else:
        # Apply standard markup rules
        markup_amount = carrier_rate * DEFAULT_MARKUP_PERCENT

        # Enforce minimum margin
        if markup_amount < MINIMUM_MARGIN_USD:
            markup_amount = MINIMUM_MARGIN_USD

        customer_rate = carrier_rate + markup_amount
        margin = markup_amount
        markup_percent = DEFAULT_MARKUP_PERCENT * 100

    # Round to 2 decimal places
    customer_rate = customer_rate.quantize(Decimal("0.01"))
    margin = margin.quantize(Decimal("0.01"))
    markup_amount = markup_amount.quantize(Decimal("0.01"))

    # Store the quoted amount on the RFQ
    rfq.quoted_amount = customer_rate
    rfq.updated_at = datetime.now(timezone.utc)

    # Transition to waiting_on_broker if appropriate
    if rfq.state == RFQState.QUOTES_RECEIVED:
        from backend.services.rfq_state_machine import transition_rfq
        try:
            transition_rfq(
                db, rfq.id, RFQState.WAITING_ON_BROKER,
                actor="pricing_engine",
                reason=f"Quote priced at ${customer_rate} (carrier: ${carrier_rate}, margin: ${margin})",
            )
        except Exception:
            pass

    # Audit event
    event_type = "pricing_override" if is_override else "pricing_calculated"
    description = (
        f"Customer rate set to ${customer_rate} "
        f"(carrier: ${carrier_rate}, margin: ${margin})"
    )
    if is_override and override_reason:
        description += f" — Override: {override_reason}"

    event = AuditEvent(
        rfq_id=rfq.id,
        event_type=event_type,
        actor="pricing_engine" if not is_override else "broker",
        description=description,
        event_data={
            "carrier_bid_id": carrier_bid_id,
            "carrier_name": bid.carrier_name,
            "carrier_rate": float(carrier_rate),
            "customer_rate": float(customer_rate),
            "margin": float(margin),
            "markup_percent": float(markup_percent),
            "is_override": is_override,
            "override_reason": override_reason,
        },
    )
    db.add(event)
    db.commit()

    return PricingResult(
        carrier_bid_id=carrier_bid_id,
        carrier_name=bid.carrier_name,
        carrier_rate=carrier_rate,
        markup_percent=markup_percent,
        markup_amount=markup_amount,
        customer_rate=customer_rate,
        margin=margin,
        is_manual_override=is_override,
        override_reason=override_reason,
    )
