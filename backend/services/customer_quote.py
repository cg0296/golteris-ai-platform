"""
backend/services/customer_quote.py — Customer quote generation and delivery (#36).

Generates a professional customer-facing quote email from an RFQ's pricing
data and creates an Approval (type=customer_quote) for the broker to review
before sending. The outbound send pipeline (#25) handles actual delivery.

This is the final step in the freight quote workflow:
    Shipper email → extraction → validation → carrier distribution →
    bid parsing → bid ranking → pricing → **customer quote** → send

Cross-cutting constraints:
    C2 — Quote creates a pending approval; sends only after broker approves
    C3 — Quote uses professional business language, not agent jargon

Called by:
    backend/api/carriers.py POST /api/rfqs/{id}/generate-quote
"""

import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy.orm import Session

from backend.db.models import (
    Approval,
    ApprovalStatus,
    ApprovalType,
    AuditEvent,
    RFQ,
    RFQState,
)

logger = logging.getLogger("golteris.services.customer_quote")

# Quote validity period — how long the quoted price is valid
QUOTE_VALIDITY_DAYS = 5


def generate_customer_quote(
    db: Session,
    rfq_id: int,
) -> dict:
    """
    Generate a customer-facing quote email and create a pending approval.

    Reads the RFQ's quoted_amount (set by the pricing engine #35) and
    generates a professional email template. Creates an Approval with
    type=customer_quote so the broker reviews before sending (C2).

    Args:
        db: SQLAlchemy session
        rfq_id: The RFQ to generate a quote for

    Returns:
        Dict with approval_id and quote preview.

    Raises:
        ValueError: If RFQ not found, no quoted amount, or no customer email.
    """
    rfq = db.query(RFQ).filter(RFQ.id == rfq_id).first()
    if not rfq:
        raise ValueError(f"RFQ {rfq_id} not found")

    if not rfq.quoted_amount:
        raise ValueError(f"RFQ {rfq_id} has no quoted amount — run pricing first")

    if not rfq.customer_email:
        raise ValueError(f"RFQ {rfq_id} has no customer email address")

    # Get the broker's name for the email signature
    broker_name = _get_broker_name(db)

    # Generate the quote email
    subject = f"Quote: {rfq.origin} to {rfq.destination} — {rfq.equipment_type}"
    body = _generate_quote_body(rfq, broker_name)

    # Create the approval (C2 gate — broker must approve before sending)
    approval = Approval(
        rfq_id=rfq.id,
        approval_type=ApprovalType.CUSTOMER_QUOTE,
        draft_body=body,
        draft_subject=subject,
        draft_recipient=rfq.customer_email,
        reason=f"Customer quote at ${rfq.quoted_amount:,.2f} ready for review",
        status=ApprovalStatus.PENDING_APPROVAL,
    )
    db.add(approval)

    # Audit event
    event = AuditEvent(
        rfq_id=rfq.id,
        event_type="customer_quote_generated",
        actor="system",
        description=f"Customer quote prepared at ${rfq.quoted_amount:,.2f} for {rfq.customer_name}",
        event_data={
            "quoted_amount": float(rfq.quoted_amount),
            "customer_email": rfq.customer_email,
        },
    )
    db.add(event)
    db.flush()

    approval_id = approval.id
    db.commit()

    return {
        "approval_id": approval_id,
        "subject": subject,
        "recipient": rfq.customer_email,
        "quoted_amount": float(rfq.quoted_amount),
        "preview": body[:500],
    }


def _get_broker_name(db: Session) -> str:
    """Get the active broker's first name for email signatures."""
    try:
        from backend.db.models import User
        user = db.query(User).filter(User.active == True).order_by(User.id.desc()).first()
        if user and user.name:
            return user.name.split()[0]
    except Exception:
        pass
    return "Beltmann Logistics"


def _generate_quote_body(rfq: RFQ, broker_name: str = "Jillian") -> str:
    """
    Generate a professional customer-facing quote email (C3 — business language).

    The broker can edit this in the approval modal before sending.
    """
    validity_date = (datetime.now(timezone.utc) + timedelta(days=QUOTE_VALIDITY_DAYS)).strftime("%B %d, %Y")
    customer_name = rfq.customer_name or "Valued Customer"

    lines = [
        f"Dear {customer_name},",
        "",
        "Thank you for your freight quote request. We are pleased to provide the following quote:",
        "",
        "SHIPMENT DETAILS",
        f"  Origin:      {rfq.origin or 'TBD'}",
        f"  Destination: {rfq.destination or 'TBD'}",
        f"  Equipment:   {rfq.equipment_type or 'TBD'}",
        f"  Truck Count: {rfq.truck_count or 1}",
    ]

    if rfq.commodity:
        lines.append(f"  Commodity:   {rfq.commodity}")
    if rfq.weight_lbs:
        lines.append(f"  Weight:      {rfq.weight_lbs:,} lbs")

    lines.extend([
        "",
        "QUOTED RATE",
        f"  Total: ${rfq.quoted_amount:,.2f}",
        f"  Rate includes all applicable surcharges",
        "",
        f"This quote is valid through {validity_date}.",
        "",
        "To proceed, simply reply to this email confirming the shipment details above.",
        "We will coordinate pickup and delivery scheduling once confirmed.",
        "",
        "If you have any questions or need adjustments, please don't hesitate to reach out.",
        "",
        "Best regards,",
        f"{broker_name}",
        "Beltmann Logistics",
    ])

    return "\n".join(lines)
