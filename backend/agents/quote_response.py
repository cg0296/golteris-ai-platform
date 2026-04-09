"""
backend/agents/quote_response.py — Customer quote response classifier (#160).

When a customer replies to a sent quote, this agent classifies their response
as accepted, rejected, or question/negotiation, then takes the appropriate action:

    - accepted  → transition RFQ to won, draft confirmation email
    - rejected  → transition RFQ to lost, draft close-out email
    - question  → keep as waiting_on_broker, create approval for manual handling

Pipeline position:
    Customer quote sent → customer replies → message matching detects reply →
    This agent classifies and handles → confirmation/close-out or manual review

Cross-cutting constraints:
    C2 — Outbound emails go through approval or auto-send (#154)
    C3 — All emails use plain broker language
    C4 — Classification logged as agent_call for traceability
    C5 — Cost caps enforced at call_llm level
"""

import logging
from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy.orm import Session

from backend.db.models import (
    Approval,
    ApprovalStatus,
    ApprovalType,
    AuditEvent,
    Message,
    RFQ,
    RFQState,
)
from backend.llm.client import call_llm
from backend.llm.provider import ToolDefinition
from backend.services.agent_runs import fail_run, finish_run, start_run

logger = logging.getLogger("golteris.agents.quote_response")


# ---------------------------------------------------------------------------
# Tool-use schema — the LLM classifies the customer's response
# ---------------------------------------------------------------------------

CLASSIFY_RESPONSE_TOOL = ToolDefinition(
    name="classify_quote_response",
    description=(
        "Classify a customer's reply to a freight quote as accepted, rejected, "
        "or a question/negotiation that needs broker attention."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "classification": {
                "type": "string",
                "enum": ["accepted", "rejected", "question"],
                "description": (
                    "accepted — customer confirms they want to proceed with the quote. "
                    "rejected — customer declines the quote or says they're going elsewhere. "
                    "question — customer is asking a question, negotiating, or the intent is unclear."
                ),
            },
            "confidence": {
                "type": "number",
                "description": "How confident you are in this classification (0.0-1.0)",
            },
            "reason": {
                "type": "string",
                "description": "One-sentence explanation of why you classified it this way",
            },
        },
        "required": ["classification", "confidence", "reason"],
    },
)


SYSTEM_PROMPT = """You are a freight broker assistant analyzing a customer's reply to a quote we sent them.

Your job is to classify the customer's response:
- "accepted" — they want to proceed, confirm, approve, book, or say yes
- "rejected" — they decline, pass, found another carrier, say no, or are not interested
- "question" — they're asking about details, negotiating price, requesting changes, or it's unclear

Rules:
- Look at the actual intent, not just keywords. "Sounds good, let me check with my team" is a question, not acceptance.
- Clear confirmations like "Let's do it", "Go ahead", "Confirmed", "Book it" = accepted
- Clear rejections like "We'll pass", "Going with someone else", "Too expensive" = rejected
- Anything ambiguous or requesting changes = question (let the broker handle it)
- If confidence is below 0.7, classify as "question" to be safe — let the broker decide.

Use the classify_quote_response tool to return your classification."""


def handle_quote_response(
    db: Session,
    message_id: int,
) -> Optional[dict[str, Any]]:
    """
    Classify a customer's reply to a sent quote and take appropriate action.

    Args:
        db: SQLAlchemy session.
        message_id: The inbound message from the customer.

    Returns:
        Dict with classification result and action taken, or None on failure.
    """
    message = db.query(Message).filter(Message.id == message_id).first()
    if not message:
        logger.error("Message %d not found", message_id)
        return None

    if not message.rfq_id:
        logger.error("Message %d has no RFQ — cannot classify", message_id)
        return None

    rfq = db.query(RFQ).filter(RFQ.id == message.rfq_id).first()
    if not rfq:
        logger.error("RFQ %d not found for message %d", message.rfq_id, message_id)
        return None

    run = start_run(
        db,
        workflow_name="Quote Response Classification",
        rfq_id=rfq.id,
        trigger_source="customer_reply",
    )

    try:
        # Build the prompt with the customer's reply and the quote context
        user_prompt = _build_prompt(rfq, message)

        response = call_llm(
            db=db,
            run_id=run.id,
            agent_name="quote_response",
            system_prompt=SYSTEM_PROMPT,
            user_prompt=user_prompt,
            tools=[CLASSIFY_RESPONSE_TOOL],
            temperature=0.0,
        )

        # Parse the classification
        classification = _parse_classification(response)
        if not classification:
            logger.warning("LLM did not classify message %d — falling back to manual", message_id)
            _handle_question(db, rfq, message)
            fail_run(db, run.id, "LLM did not return classification")
            return None

        label = classification["classification"]
        confidence = classification.get("confidence", 0.0)
        reason = classification.get("reason", "")

        logger.info(
            "RFQ %d: customer response classified as '%s' (%.0f%%) — %s",
            rfq.id, label, confidence * 100, reason,
        )

        # Low confidence → treat as question for safety
        if confidence < 0.7:
            logger.info("RFQ %d: low confidence (%.0f%%) — routing to broker", rfq.id, confidence * 100)
            _handle_question(db, rfq, message)
        elif label == "accepted":
            _handle_accepted(db, rfq, message, reason)
        elif label == "rejected":
            _handle_rejected(db, rfq, message, reason)
        else:
            _handle_question(db, rfq, message)

        # Log the classification as an audit event
        db.add(AuditEvent(
            rfq_id=rfq.id,
            event_type="quote_response_classified",
            actor="quote_response_agent",
            description=f"Customer response classified as '{label}' ({confidence:.0%}) — {reason}",
            event_data={
                "classification": label,
                "confidence": confidence,
                "reason": reason,
                "message_id": message_id,
            },
        ))
        db.commit()

        finish_run(db, run.id)

        return {
            "classification": label,
            "confidence": confidence,
            "reason": reason,
            "rfq_id": rfq.id,
        }

    except Exception as e:
        logger.exception("Quote response classification failed for message %d: %s", message_id, e)
        # Fall back to manual handling on any error
        try:
            _handle_question(db, rfq, message)
        except Exception:
            pass
        fail_run(db, run.id, str(e))
        return None


def _build_prompt(rfq: RFQ, message: Message) -> str:
    """Build the user prompt with quote context and customer reply."""
    lines = [
        "QUOTE CONTEXT:",
        f"  RFQ #{rfq.id} for {rfq.customer_name} ({rfq.customer_company or 'N/A'})",
        f"  Route: {rfq.origin} to {rfq.destination}",
        f"  Equipment: {rfq.equipment_type}, {rfq.truck_count} truck(s)",
        f"  Quoted amount: ${rfq.quoted_amount:,.2f}" if rfq.quoted_amount else "  Quoted amount: not set",
        "",
        "CUSTOMER'S REPLY:",
        f"  From: {message.sender}",
        f"  Subject: {message.subject}",
        f"  Body: {message.body or '(empty)'}",
    ]
    return "\n".join(lines)


def _parse_classification(response) -> Optional[dict]:
    """Extract the classification from the LLM's tool-use response."""
    if not response.tool_calls:
        return None
    for tool_call in response.tool_calls:
        if tool_call.get("name") == "classify_quote_response":
            return tool_call.get("input", {})
    return None


def _handle_accepted(db: Session, rfq: RFQ, message: Message, reason: str) -> None:
    """
    Customer accepted the quote — mark as won and draft confirmation.
    """
    from backend.services.rfq_state_machine import transition_rfq
    from backend.worker import enqueue_job, is_auto_send_enabled

    # Transition to won
    try:
        transition_rfq(
            db, rfq.id, RFQState.WON,
            actor="quote_response_agent",
            reason=f"Customer accepted quote — {reason}",
        )
        rfq.outcome = "won"
        rfq.closed_at = datetime.now(timezone.utc)
        db.commit()
    except Exception as e:
        logger.warning("Could not transition RFQ %d to won: %s", rfq.id, e)

    # Draft confirmation email
    broker_name = _get_broker_name(db)
    customer_name = rfq.customer_name or "there"
    body = (
        f"Hi {customer_name},\n\n"
        f"Thank you for confirming! We're moving forward with your shipment:\n\n"
        f"  {rfq.origin} to {rfq.destination}\n"
        f"  {rfq.truck_count} {rfq.equipment_type}(s)\n\n"
        f"We'll coordinate pickup scheduling and be in touch with details shortly.\n\n"
        f"Thanks,\n{broker_name}\nBeltmann Logistics"
    )

    auto_send = is_auto_send_enabled(db, "Inbound Quote Processing")
    approval = Approval(
        rfq_id=rfq.id,
        approval_type=ApprovalType.CUSTOMER_REPLY,
        draft_subject=f"Re: {message.subject or 'Quote Confirmation'}",
        draft_body=body,
        draft_recipient=_extract_email(message.sender) or rfq.customer_email,
        reason="Quote accepted — confirmation email",
        status=ApprovalStatus.APPROVED if auto_send else ApprovalStatus.PENDING_APPROVAL,
    )
    if auto_send:
        approval.resolved_by = "auto_send"
        approval.resolved_at = datetime.now(timezone.utc)
    db.add(approval)
    db.commit()
    db.refresh(approval)

    if auto_send:
        enqueue_job(db, "send_outbound_email", {"approval_id": approval.id}, rfq_id=rfq.id)
        logger.info("RFQ %d: acceptance confirmation auto-sent", rfq.id)


def _handle_rejected(db: Session, rfq: RFQ, message: Message, reason: str) -> None:
    """
    Customer rejected the quote — mark as lost and draft close-out.
    """
    from backend.services.rfq_state_machine import transition_rfq
    from backend.worker import enqueue_job, is_auto_send_enabled

    # Transition to lost
    try:
        transition_rfq(
            db, rfq.id, RFQState.LOST,
            actor="quote_response_agent",
            reason=f"Customer declined quote — {reason}",
        )
        rfq.outcome = "lost"
        rfq.closed_at = datetime.now(timezone.utc)
        db.commit()
    except Exception as e:
        logger.warning("Could not transition RFQ %d to lost: %s", rfq.id, e)

    # Draft close-out email
    broker_name = _get_broker_name(db)
    customer_name = rfq.customer_name or "there"
    body = (
        f"Hi {customer_name},\n\n"
        f"Thank you for considering us for your {rfq.origin} to {rfq.destination} shipment. "
        f"We understand this one didn't work out, and we appreciate you letting us know.\n\n"
        f"We'd love to help with future shipments — don't hesitate to reach out anytime.\n\n"
        f"Best,\n{broker_name}\nBeltmann Logistics"
    )

    auto_send = is_auto_send_enabled(db, "Inbound Quote Processing")
    approval = Approval(
        rfq_id=rfq.id,
        approval_type=ApprovalType.CUSTOMER_REPLY,
        draft_subject=f"Re: {message.subject or 'Quote Response'}",
        draft_body=body,
        draft_recipient=_extract_email(message.sender) or rfq.customer_email,
        reason="Quote declined — close-out email",
        status=ApprovalStatus.APPROVED if auto_send else ApprovalStatus.PENDING_APPROVAL,
    )
    if auto_send:
        approval.resolved_by = "auto_send"
        approval.resolved_at = datetime.now(timezone.utc)
    db.add(approval)
    db.commit()
    db.refresh(approval)

    if auto_send:
        enqueue_job(db, "send_outbound_email", {"approval_id": approval.id}, rfq_id=rfq.id)
        logger.info("RFQ %d: rejection close-out auto-sent", rfq.id)


def _handle_question(db: Session, rfq: RFQ, message: Message) -> None:
    """
    Customer asked a question or intent is unclear — route to broker.

    This is the fallback: create an approval in Urgent Actions so the
    broker can read the reply and decide (current behavior from #145).
    """
    from backend.services.rfq_state_machine import transition_rfq

    # Transition to waiting_on_broker
    try:
        if rfq.state != RFQState.WAITING_ON_BROKER:
            transition_rfq(
                db, rfq.id, RFQState.WAITING_ON_BROKER,
                actor="quote_response_agent",
                reason="Customer response needs broker review",
            )
    except Exception as e:
        logger.warning("Could not transition RFQ %d to waiting_on_broker: %s", rfq.id, e)

    reply_preview = (message.body or "")[:500]
    approval = Approval(
        rfq_id=rfq.id,
        approval_type=ApprovalType.CUSTOMER_REPLY,
        draft_body=reply_preview,
        draft_subject=message.subject or "Customer response",
        draft_recipient=_extract_email(message.sender) or rfq.customer_email or "",
        reason="Customer responded to your quote — review and take action",
        status=ApprovalStatus.PENDING_APPROVAL,
    )
    db.add(approval)
    db.commit()


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


def _extract_email(sender: str) -> Optional[str]:
    """Extract email address from 'Name <email>' format."""
    if not sender:
        return None
    if "<" in sender and ">" in sender:
        return sender.split("<")[1].split(">")[0]
    return sender
