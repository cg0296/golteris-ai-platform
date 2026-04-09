"""
backend/agents/validation.py — Missing-information detection and follow-up drafting.

This is the second agent in the pipeline, triggered after extraction when an
RFQ lands in needs_clarification state. It does two things:

    1. Identifies exactly which required fields are missing or low-confidence
    2. Calls the LLM to draft a professional follow-up email asking for those fields

The drafted follow-up is stored as an approval record (status=pending_approval)
so the broker can review, edit, or reject it before it's sent. This is the C2
enforcement point — nothing goes outbound without human approval.

Pipeline position:
    Extraction (#24) creates RFQ in needs_clarification
    -> This agent detects what's missing and drafts the follow-up
    -> Broker reviews in the HITL approval flow (#26)
    -> If approved, outbound email sends (#25)
    -> Customer replies with missing info (#07 in seed data)
    -> Matching service (#13) attaches reply to the RFQ
    -> State transitions to ready_to_quote (#14)

Called by:
    - The background worker after extraction creates a needs_clarification RFQ
    - Manually for testing: `validate_and_draft(db, rfq_id)`

Cross-cutting constraints:
    C2 — Draft persists as pending_approval; NEVER auto-sends
    C3 — Follow-up email uses professional broker language, not agent jargon
    C4 — LLM call logged via agent_calls, run tracked via agent_runs
    C5 — Cost caps enforced at call_llm level
"""

import logging
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
from backend.llm.client import call_llm
from backend.llm.provider import ToolDefinition
from backend.services.agent_runs import fail_run, finish_run, start_run

logger = logging.getLogger("golteris.agents.validation")


# ---------------------------------------------------------------------------
# Required fields — these must be present and high-confidence for an RFQ
# to be quotable. If any are missing or low-confidence, a follow-up is needed.
#
# This matches FR-AG-4 and the extraction agent's confidence threshold.
# ---------------------------------------------------------------------------

REQUIRED_FIELDS = {
    "origin": "pickup city/metro area",
    "destination": "delivery city/metro area",
    "equipment_type": "truck/trailer type (flatbed, van, reefer, etc.)",
    "truck_count": "number of trucks needed",
    "commodity": "what is being shipped",
}

# Weight is important for quoting but not strictly required — many initial
# RFQs don't include it and the broker can estimate. We flag it but don't
# block on it.
RECOMMENDED_FIELDS = {
    "weight_lbs": "approximate weight per truck in pounds",
    "pickup_date": "requested pickup date",
    "delivery_date": "requested delivery date",
}

from backend.services.escalation_policy import DEFAULT_THRESHOLD as CONFIDENCE_THRESHOLD


# ---------------------------------------------------------------------------
# Tool-use schema for follow-up email drafting
# ---------------------------------------------------------------------------

DRAFT_FOLLOWUP_TOOL = ToolDefinition(
    name="draft_followup_email",
    description=(
        "Draft a professional follow-up email to the customer asking for the "
        "specific missing information needed to complete their freight quote request. "
        "The email should be friendly, concise, and clearly list what's needed."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "subject": {
                "type": "string",
                "description": "Email subject line (e.g., 'Re: Quote Request — A few details needed')",
            },
            "body": {
                "type": "string",
                "description": "Full email body. Professional tone, references the customer by name if known, lists exactly what's missing, and offers to help.",
            },
        },
        "required": ["subject", "body"],
    },
)


FOLLOWUP_SYSTEM_PROMPT = """You are a freight broker drafting a follow-up email to a customer whose quote request is missing information.

CRITICAL TONE RULES:
- Write like a real person, not a corporate template. Short, casual, professional.
- If this is a FOLLOW-UP reply (the customer already responded once), keep it very short — 2-4 sentences max. No greeting fluff, no "thank you for reaching out", no sign-off block. Just ask the question like you're replying in a quick email thread.
- Only the FIRST email to a new customer should have a full greeting, context, and sign-off.
- Never pad with filler like "We'd love to help" or "feel free to reply here or give us a call" — the customer already knows they can reply.
- Ask for ONLY the specific missing items. Don't re-list what they already provided.
- Use plain language. "Where's the pickup?" not "Could you share the city and state where the load will be picked up?"

SIGNATURE: Sign off using the broker name provided in the prompt (e.g., "Thanks, Jillian" or "— Curt"). Do NOT say "The Beltmann Team" — use the real person's name.

FOLLOW-UP REPLY EXAMPLES (when only 1-2 fields missing):
  "Got it, thanks! Where's the pickup location? — Jillian"
  "Thanks Yonnas — just need the pickup city and we'll get quotes rolling. — Curt"
  "Perfect. What's the pickup city/state? We'll get on it."

FIRST EMAIL EXAMPLES (when 3+ fields missing):
  Keep it to one short paragraph + a bullet list of what's needed. Sign off with the broker's first name.

Use the draft_followup_email tool to return your draft."""


def detect_missing_info(db: Session, rfq_id: int) -> dict:
    """
    Analyze an RFQ and identify which required fields are missing or low-confidence.

    Returns a dict with:
        - missing_required: list of (field_name, human_label) for null required fields
        - low_confidence: list of (field_name, human_label, score) for below-threshold fields
        - missing_recommended: list of (field_name, human_label) for null recommended fields
        - needs_followup: bool — True if any required fields are missing or low-confidence

    Args:
        db: SQLAlchemy session.
        rfq_id: The RFQ to analyze.

    Returns:
        Analysis dict, or None if the RFQ doesn't exist.
    """
    rfq = db.query(RFQ).filter(RFQ.id == rfq_id).first()
    if not rfq:
        return None

    confidence = rfq.confidence_scores or {}

    missing_required = []
    low_confidence = []
    missing_recommended = []

    # Check required fields — these block quoting
    for field_name, human_label in REQUIRED_FIELDS.items():
        value = getattr(rfq, field_name, None)
        if value is None:
            missing_required.append((field_name, human_label))
        else:
            score = confidence.get(field_name, 1.0)
            if score < CONFIDENCE_THRESHOLD:
                low_confidence.append((field_name, human_label, score))

    # Check recommended fields — nice to have but don't block
    for field_name, human_label in RECOMMENDED_FIELDS.items():
        value = getattr(rfq, field_name, None)
        if value is None:
            missing_recommended.append((field_name, human_label))

    return {
        "missing_required": missing_required,
        "low_confidence": low_confidence,
        "missing_recommended": missing_recommended,
        "needs_followup": len(missing_required) > 0 or len(low_confidence) > 0,
    }


def draft_followup(
    db: Session,
    rfq_id: int,
) -> Optional[Approval]:
    """
    Draft a follow-up email for an RFQ that needs clarification.

    Detects missing/low-confidence fields, then calls the LLM to generate
    a professional follow-up email. The draft is stored as an approval record
    with status=pending_approval so the broker reviews it before sending (C2).

    Args:
        db: SQLAlchemy session.
        rfq_id: The RFQ to draft a follow-up for.

    Returns:
        The Approval record containing the draft, or None if no follow-up
        is needed (all required fields are present and high-confidence).

    Side effects:
        - Creates an agent_run (via run tracking service)
        - Creates agent_calls (via call_llm)
        - Creates an approvals row with status=pending_approval (C2)
        - Creates an audit_events row for the RFQ timeline
    """
    rfq = db.query(RFQ).filter(RFQ.id == rfq_id).first()
    if not rfq:
        logger.error("RFQ %d not found — cannot draft follow-up", rfq_id)
        return None

    # Detect what's missing
    analysis = detect_missing_info(db, rfq_id)
    if not analysis["needs_followup"]:
        logger.info("RFQ %d has all required fields — no follow-up needed", rfq_id)
        # If the RFQ is still in needs_clarification, promote it and enqueue quote sheet
        if rfq.state == RFQState.NEEDS_CLARIFICATION:
            from backend.services.rfq_state_machine import transition_rfq
            from backend.worker import enqueue_job
            try:
                transition_rfq(db, rfq.id, RFQState.READY_TO_QUOTE, actor="validation_agent",
                              reason="All required fields now present")
                enqueue_job(db, "quote_sheet", {"rfq_id": rfq.id}, rfq_id=rfq.id)
                logger.info("RFQ %d promoted to ready_to_quote — quote sheet enqueued", rfq_id)
            except Exception as e:
                logger.warning("Could not promote RFQ %d: %s", rfq_id, e)
        return None

    # Start an agent run
    run = start_run(
        db,
        workflow_name="Missing Info Follow-up",
        rfq_id=rfq_id,
        trigger_source="validation",
    )

    try:
        # Check if we've already emailed this customer (follow-up vs first contact).
        # Follow-ups should be short and conversational, not a full formal email.
        from backend.db.models import Message, MessageDirection
        prior_outbound = (
            db.query(Message)
            .filter(
                Message.rfq_id == rfq_id,
                Message.direction == MessageDirection.OUTBOUND,
            )
            .count()
        )
        is_followup = prior_outbound > 0

        # Get the broker's name for the email signature — pulled from the
        # most recently active user account so emails sign off as a real person
        broker_name = _get_broker_name(db)

        # Build the prompt describing what's missing
        user_prompt = _build_followup_prompt(rfq, analysis, is_followup, broker_name)

        # Call the LLM to draft the email
        response = call_llm(
            db=db,
            run_id=run.id,
            agent_name="validation",
            system_prompt=FOLLOWUP_SYSTEM_PROMPT,
            user_prompt=user_prompt,
            tools=[DRAFT_FOLLOWUP_TOOL],
            temperature=0.3,  # Slightly creative for natural email tone
        )

        # Parse the tool response
        draft = _parse_draft_response(response)
        if not draft:
            logger.warning("LLM did not call draft_followup_email tool for RFQ %d", rfq_id)
            fail_run(db, run.id, "LLM did not return tool-use result")
            return None

        # Check if auto-send is enabled for follow-ups (#154).
        # When enabled, the email sends immediately. When disabled,
        # the draft goes to the approval queue for broker review (C2).
        from backend.worker import is_auto_send_enabled, enqueue_job
        auto_send = is_auto_send_enabled(db, "Follow-up Automation")

        approval = Approval(
            rfq_id=rfq_id,
            approval_type=ApprovalType.CUSTOMER_REPLY,
            draft_subject=draft["subject"],
            draft_body=draft["body"],
            draft_recipient=rfq.customer_email,
            reason=_build_reason_text(analysis),
            status=ApprovalStatus.APPROVED if auto_send else ApprovalStatus.PENDING_APPROVAL,
        )
        if auto_send:
            from datetime import datetime
            approval.resolved_by = "auto_send"
            approval.resolved_at = datetime.utcnow()
        db.add(approval)

        # Log audit event — plain English per C3
        _log_audit_event(db, rfq, analysis)

        db.commit()
        db.refresh(approval)

        # If auto-send, enqueue the outbound email immediately
        if auto_send:
            enqueue_job(
                db,
                job_type="send_outbound_email",
                payload={"approval_id": approval.id},
                rfq_id=rfq_id,
            )
            db.add(AuditEvent(
                rfq_id=rfq_id,
                event_type="auto_send",
                actor="auto_send",
                description=f"Clarification email auto-sent to {rfq.customer_email} (Follow-up Automation enabled)",
            ))
            db.commit()
            logger.info("RFQ %d: follow-up auto-sent to %s", rfq_id, rfq.customer_email)

        finish_run(db, run.id)

        logger.info(
            "Follow-up drafted for RFQ %d: %d missing required, %d low confidence",
            rfq_id, len(analysis["missing_required"]), len(analysis["low_confidence"]),
        )

        return approval

    except Exception as e:
        logger.exception("Follow-up drafting failed for RFQ %d: %s", rfq_id, e)
        fail_run(db, run.id, str(e))
        raise


def _get_broker_name(db: Session) -> str:
    """
    Get the name of the active broker user for email signatures.

    Pulls from the users table so emails sign off as a real person
    (e.g., "— Curt") instead of "The Beltmann Team".
    """
    try:
        from backend.db.models import User
        user = (
            db.query(User)
            .filter(User.active == True)
            .order_by(User.id.desc())
            .first()
        )
        if user and user.name:
            # Use first name only for casual sign-off
            return user.name.split()[0]
    except Exception:
        pass
    return "Beltmann Team"


def _build_followup_prompt(rfq: RFQ, analysis: dict, is_followup: bool = False, broker_name: str = "Beltmann Team") -> str:
    """
    Build the user prompt describing the RFQ and what's missing.

    Gives the LLM enough context about the original request to draft
    a relevant, personalized follow-up — not a generic template.
    """
    lines = []

    if is_followup:
        lines.append("THIS IS A FOLLOW-UP REPLY — the customer already responded to a previous email.")
        lines.append("Keep it SHORT (2-4 sentences). No formal greeting or sign-off block. Just ask what's still needed.")
        lines.append("")

    lines.append(f"Broker name for signature: {broker_name}")
    lines.append("")
    lines.append(f"Customer: {rfq.customer_name or 'Unknown'} ({rfq.customer_email or 'no email'})")
    lines.append(f"Company: {rfq.customer_company or 'Unknown'}")
    lines.append("")
    lines.append("What we know so far from their request:")
    if rfq.origin:
        lines.append(f"  - Origin: {rfq.origin}")
    if rfq.destination:
        lines.append(f"  - Destination: {rfq.destination}")
    if rfq.equipment_type:
        lines.append(f"  - Equipment: {rfq.equipment_type}")
    if rfq.truck_count:
        lines.append(f"  - Trucks: {rfq.truck_count}")
    if rfq.commodity:
        lines.append(f"  - Commodity: {rfq.commodity}")
    if rfq.weight_lbs:
        lines.append(f"  - Weight: {rfq.weight_lbs} lbs")

    lines.append("")
    lines.append("MISSING INFORMATION (must ask for):")
    for field_name, human_label in analysis["missing_required"]:
        lines.append(f"  - {human_label}")

    if analysis["low_confidence"]:
        lines.append("")
        lines.append("UNCLEAR / NEEDS CLARIFICATION:")
        for field_name, human_label, score in analysis["low_confidence"]:
            value = getattr(rfq, field_name, None)
            lines.append(f"  - {human_label}: they said \"{value}\" but this is ambiguous")

    if analysis["missing_recommended"]:
        lines.append("")
        lines.append("OPTIONAL (nice to have, ask if natural):")
        for field_name, human_label in analysis["missing_recommended"]:
            lines.append(f"  - {human_label}")

    return "\n".join(lines)


def _parse_draft_response(response) -> Optional[dict]:
    """Extract the draft email from the LLM's tool-use response."""
    if not response.tool_calls:
        return None

    for tool_call in response.tool_calls:
        if tool_call.get("name") == "draft_followup_email":
            return tool_call.get("input", {})

    return None


def _build_reason_text(analysis: dict) -> str:
    """
    Build a human-readable reason for why this follow-up was flagged.

    Shown in the approval modal as the "reason" badge so the broker
    understands why this draft was created. Uses plain English per C3.
    """
    parts = []
    if analysis["missing_required"]:
        fields = [label for _, label in analysis["missing_required"]]
        parts.append(f"Missing: {', '.join(fields)}")
    if analysis["low_confidence"]:
        fields = [label for _, label, _ in analysis["low_confidence"]]
        parts.append(f"Unclear: {', '.join(fields)}")
    return "; ".join(parts) or "Review needed"


def _log_audit_event(db: Session, rfq: RFQ, analysis: dict) -> None:
    """
    Create an audit event for the RFQ timeline.

    Uses plain English per C3 — the broker sees "Draft follow-up prepared"
    not "validation_agent_completed" or "missing_info_detected."
    """
    missing_labels = [label for _, label in analysis["missing_required"]]
    unclear_labels = [label for _, label, _ in analysis["low_confidence"]]
    all_items = missing_labels + unclear_labels

    description = f"Draft follow-up prepared — asking for: {', '.join(all_items)}"

    event = AuditEvent(
        rfq_id=rfq.id,
        event_type="followup_drafted",
        actor="validation_agent",
        description=description,
        event_data={
            "missing_required": [f for f, _ in analysis["missing_required"]],
            "low_confidence": [f for f, _, _ in analysis["low_confidence"]],
            "missing_recommended": [f for f, _ in analysis["missing_recommended"]],
        },
    )
    db.add(event)
