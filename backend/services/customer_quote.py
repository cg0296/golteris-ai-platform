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
    from backend.services.broker_identity import get_broker_name
    broker_name = get_broker_name(db)

    # Generate the quote email
    subject = f"Quote: {rfq.origin} to {rfq.destination} — {rfq.equipment_type}"
    from backend.services.org_profile import get_sign_off
    company_name = get_sign_off(db)
    body = _generate_quote_body(rfq, broker_name, company_name)

    # Check if auto-send is enabled for customer quotes (#154).
    from backend.worker import is_auto_send_enabled, enqueue_job
    auto_send = is_auto_send_enabled(db, "Inbound Quote Processing")

    approval = Approval(
        rfq_id=rfq.id,
        approval_type=ApprovalType.CUSTOMER_QUOTE,
        draft_body=body,
        draft_subject=subject,
        draft_recipient=rfq.customer_email,
        reason=f"Customer quote at ${rfq.quoted_amount:,.2f} ready for review",
        status=ApprovalStatus.APPROVED if auto_send else ApprovalStatus.PENDING_APPROVAL,
    )
    if auto_send:
        from datetime import datetime
        approval.resolved_by = "auto_send"
        approval.resolved_at = datetime.utcnow()
    db.add(approval)

    # Audit event
    event = AuditEvent(
        rfq_id=rfq.id,
        event_type="customer_quote_generated",
        actor="auto_send" if auto_send else "system",
        description=f"Customer quote {'auto-sent' if auto_send else 'prepared'} at ${rfq.quoted_amount:,.2f} for {rfq.customer_name}",
        event_data={
            "quoted_amount": float(rfq.quoted_amount),
            "customer_email": rfq.customer_email,
            "auto_send": auto_send,
        },
    )
    db.add(event)
    db.flush()

    approval_id = approval.id
    db.commit()

    # If auto-send, enqueue the outbound email immediately
    if auto_send:
        enqueue_job(
            db,
            job_type="send_outbound_email",
            payload={"approval_id": approval_id},
            rfq_id=rfq.id,
        )
        logger.info("RFQ %d: customer quote auto-sent to %s", rfq_id, rfq.customer_email)

    return {
        "approval_id": approval_id,
        "subject": subject,
        "recipient": rfq.customer_email,
        "quoted_amount": float(rfq.quoted_amount),
        "preview": body[:500],
        "auto_sent": auto_send,
    }


## _get_broker_name removed — use backend.services.broker_identity.get_broker_name (#172)


def _generate_quote_body(rfq: RFQ, broker_name: str = "Broker", company_name: str = "Your Brokerage") -> str:
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
        "A complete quote sheet is attached for your records, including carrier",
        "availability and any notes we received during sourcing.",
        "",
        "To proceed, simply reply to this email confirming the shipment details above.",
        "We will coordinate pickup and delivery scheduling once confirmed.",
        "",
        "If you have any questions or need adjustments, please don't hesitate to reach out.",
        "",
        "Best regards,",
        f"{broker_name}",
        f"{company_name}",
    ])

    return "\n".join(lines)
