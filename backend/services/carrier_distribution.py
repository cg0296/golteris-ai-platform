"""
backend/services/carrier_distribution.py — Carrier RFQ distribution (#32).

Handles selecting carriers for an RFQ and distributing personalized carrier
RFQ emails to each. Each carrier send goes through the C2 approval gate —
the broker approves the batch, then individual sends are enqueued.

Flow:
    1. Broker opens carrier selection on an RFQ
    2. System suggests matching carriers (equipment + lane)
    3. Broker selects carriers and clicks "Send RFQs"
    4. One Approval created per carrier (type=carrier_rfq, C2 gate)
    5. Broker approves the batch → individual send jobs enqueued
    6. Each send tracked in carrier_rfq_sends with delivery status

Cross-cutting constraints:
    C2 — Each carrier send requires explicit approval before sending
    C4 — Every send is audited (via email_send service)
"""

import logging
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import or_
from sqlalchemy.orm import Session

from backend.db.models import (
    Approval,
    ApprovalStatus,
    ApprovalType,
    AuditEvent,
    Carrier,
    CarrierRfqSend,
    CarrierSendStatus,
    RFQ,
)

logger = logging.getLogger("golteris.services.carrier_distribution")


def list_carriers(
    db: Session,
    active_only: bool = True,
) -> list[Carrier]:
    """
    Return all carriers, optionally filtered to active only.

    Used by the carrier selection UI to show available carriers.
    """
    query = db.query(Carrier)
    if active_only:
        query = query.filter(Carrier.active == True)
    return query.order_by(Carrier.preferred.desc(), Carrier.name.asc()).all()


def get_matching_carriers(
    db: Session,
    rfq: RFQ,
) -> list[Carrier]:
    """
    Return carriers that match an RFQ's equipment type and lane.

    Matching logic:
    1. Equipment type must be in the carrier's equipment_types array
    2. Lane matching is optional — carriers with matching lanes rank higher
    3. Preferred carriers always appear first

    This is a simple MVP matcher. Future versions could use historical
    bid data, carrier ratings, and machine learning for ranking.

    Args:
        rfq: The RFQ to match carriers for

    Returns:
        List of matching Carrier objects, preferred first.
    """
    carriers = list_carriers(db, active_only=True)

    # Filter by equipment type if the RFQ specifies one
    if rfq.equipment_type:
        equip = rfq.equipment_type.lower()
        carriers = [
            c for c in carriers
            if any(equip in e.lower() for e in (c.equipment_types or []))
        ]

    return carriers


def distribute_to_carriers(
    db: Session,
    rfq_id: int,
    carrier_ids: list[int],
    attach_quote_sheet: bool = False,
) -> dict:
    """
    Create carrier RFQ sends and a batch approval for distribution.

    For each selected carrier:
    1. Generates a personalized RFQ email (subject + body)
    2. Creates a CarrierRfqSend tracking row
    3. Creates one Approval (type=carrier_rfq) for the batch

    The broker then approves the batch in the approval modal. On approval,
    individual send jobs are enqueued for each carrier.

    Args:
        rfq_id: The RFQ to distribute
        carrier_ids: List of carrier IDs to send to

    Returns:
        Dict with approval_id, carrier_count, and send tracking IDs
    """
    rfq = db.query(RFQ).filter(RFQ.id == rfq_id).first()
    if not rfq:
        raise ValueError(f"RFQ {rfq_id} not found")

    carriers = (
        db.query(Carrier)
        .filter(Carrier.id.in_(carrier_ids), Carrier.active == True)
        .all()
    )
    if not carriers:
        raise ValueError("No valid carriers selected")

    # Get the broker's name for the email signature
    broker_name = _get_broker_name(db)

    # Generate the carrier RFQ email template
    carrier_names = ", ".join(c.name for c in carriers)
    subject = f"RFQ: {rfq.origin} to {rfq.destination} — {rfq.equipment_type}"
    body_template = _generate_carrier_rfq_body(rfq, broker_name)

    # Check if auto-send is enabled for carrier distribution (#154).
    from backend.worker import is_auto_send_enabled, enqueue_job
    auto_send = is_auto_send_enabled(db, "Carrier Distribution")

    # Create one approval PER carrier with the carrier's actual email address.
    # When auto-send is off, each approval gates one outbound send (C2).
    # When auto-send is on, approvals are created as pre-approved and sends enqueue immediately.
    approval_ids = []
    send_ids = []
    for carrier in carriers:
        reason = f"Carrier RFQ to {carrier.name}"
        if attach_quote_sheet:
            reason += " [ATTACH_QUOTE_SHEET]"
        approval = Approval(
            rfq_id=rfq.id,
            approval_type=ApprovalType.CARRIER_RFQ,
            draft_body=body_template,
            draft_subject=subject,
            draft_recipient=carrier.email,
            reason=reason,
            status=ApprovalStatus.APPROVED if auto_send else ApprovalStatus.PENDING_APPROVAL,
        )
        if auto_send:
            from datetime import datetime
            approval.resolved_by = "auto_send"
            approval.resolved_at = datetime.utcnow()
        db.add(approval)
        db.flush()
        approval_ids.append(approval.id)

        send = CarrierRfqSend(
            rfq_id=rfq.id,
            carrier_id=carrier.id,
            approval_id=approval.id,
            status=CarrierSendStatus.PENDING_APPROVAL if not auto_send else CarrierSendStatus.SENT,
            email_subject=subject,
            email_body=body_template,
        )
        db.add(send)
        db.flush()
        send_ids.append(send.id)

    # Transition RFQ to "Waiting on carriers" since carrier RFQs are being sent out
    from backend.services.rfq_state_machine import transition_rfq, RFQState as SM_RFQState
    try:
        transition_rfq(db, rfq.id, SM_RFQState.WAITING_ON_CARRIERS, actor="system",
                        reason=f"Carrier RFQ distributed to {len(carriers)} carrier(s)")
    except Exception:
        # If already in waiting_on_carriers or transition not allowed, continue anyway
        pass

    # Audit event
    event = AuditEvent(
        rfq_id=rfq.id,
        event_type="carrier_distribution_created",
        actor="auto_send" if auto_send else "system",
        description=f"Carrier RFQ {'auto-sent' if auto_send else 'prepared'} for {len(carriers)} carrier(s): {carrier_names}",
        event_data={
            "approval_ids": approval_ids,
            "carrier_ids": carrier_ids,
            "carrier_names": [c.name for c in carriers],
            "auto_send": auto_send,
        },
    )
    db.add(event)
    db.commit()

    # If auto-send, enqueue all outbound sends immediately
    if auto_send:
        for aid in approval_ids:
            enqueue_job(
                db,
                job_type="send_outbound_email",
                payload={"approval_id": aid},
                rfq_id=rfq.id,
            )
        logger.info("RFQ %d: carrier RFQs auto-sent to %d carriers", rfq_id, len(carriers))

    return {
        "approval_ids": approval_ids,
        "carrier_count": len(carriers),
        "send_ids": send_ids,
        "auto_sent": auto_send,
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


def _generate_carrier_rfq_body(rfq: RFQ, broker_name: str = "Beltmann Logistics") -> str:
    """
    Generate a carrier RFQ email body from RFQ fields.

    Uses plain-English business language (C3). The broker can edit
    this in the approval modal before sending.
    """
    lines = [
        "Carrier RFQ",
        "",
        "We have a shipment that matches your capabilities:",
        "",
        f"  Origin:      {rfq.origin or 'TBD'}",
        f"  Destination: {rfq.destination or 'TBD'}",
        f"  Equipment:   {rfq.equipment_type or 'TBD'}",
        f"  Truck Count: {rfq.truck_count or 1}",
    ]
    if rfq.commodity:
        lines.append(f"  Commodity:   {rfq.commodity}")
    if rfq.weight_lbs:
        lines.append(f"  Weight:      {rfq.weight_lbs:,} lbs")
    if rfq.pickup_date:
        lines.append(f"  Pickup:      {rfq.pickup_date.strftime('%B %d, %Y')}")
    if rfq.delivery_date:
        lines.append(f"  Delivery:    {rfq.delivery_date.strftime('%B %d, %Y')}")
    if rfq.special_requirements:
        lines.append(f"  Special:     {rfq.special_requirements}")

    lines.extend([
        "",
        "Please reply with your best rate and availability.",
        "",
        f"Thank you,",
        f"{broker_name}",
        "Beltmann Logistics",
    ])
    return "\n".join(lines)
