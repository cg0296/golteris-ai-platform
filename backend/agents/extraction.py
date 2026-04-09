"""
backend/agents/extraction.py — RFQ extraction agent.

Turns an inbound shipper email into a structured RFQ record by calling the LLM
with a tool-use schema. This is the first agent in the pipeline and the primary
demo hero moment ("email arrives, structured RFQ appears").

How it works:
    1. Reads a message from the `messages` table
    2. Creates an agent_run via the run tracking service (#22)
    3. Calls the LLM with the extract_rfq tool schema
    4. The LLM returns structured fields + per-field confidence scores
    5. Persists the extracted fields to a new row in the `rfqs` table
    6. Logs an audit event for the RFQ detail timeline
    7. Finishes the agent run (rolls up cost/tokens)

Called by:
    - The background worker (backend/worker.py) when a new message arrives
    - Manually for testing: `extract_rfq(db, message_id)`

Cross-cutting constraints:
    C4 — Every LLM call is logged to agent_calls (automatic via call_llm)
    C5 — Cost caps enforced at call_llm level
    FR-AG-1 — Extraction uses tool-use / function calling for structured output
    FR-AG-2 — Every field has a confidence score (0.0-1.0)

See REQUIREMENTS.md §6.3 FR-AG-1 and FR-AG-2.
See .scratch/repo-wiki/Agent-Contracts.md for the full extraction contract.
"""

import json
import logging
from datetime import datetime
from decimal import Decimal
from typing import Any, Optional

from sqlalchemy.orm import Session

from backend.db.models import (
    AgentRun,
    AgentRunStatus,
    AuditEvent,
    Message,
    RFQ,
    RFQState,
)
from backend.llm.client import call_llm
from backend.llm.provider import ToolDefinition
from backend.services.agent_runs import fail_run, finish_run, start_run

logger = logging.getLogger("golteris.agents.extraction")


# ---------------------------------------------------------------------------
# Tool-use schema — defines what structured data the LLM must return.
#
# This is the core extraction contract. The LLM sees this schema and fills
# in each field from the email content. Fields it can't find are set to null.
# Confidence scores tell us how sure the LLM is about each extraction.
#
# The schema matches the `rfqs` table columns (see backend/db/models.py).
# FR-AG-1: tool-use for structured extraction
# FR-AG-2: per-field confidence scores
# ---------------------------------------------------------------------------

EXTRACT_RFQ_TOOL = ToolDefinition(
    name="extract_rfq",
    description=(
        "Extract structured freight quote request (RFQ) fields from a shipper email. "
        "Fill in every field you can find. Set fields to null if the information is not "
        "present in the email. Provide a confidence score (0.0 to 1.0) for each key field "
        "indicating how certain you are about the extraction."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "customer_name": {
                "type": ["string", "null"],
                "description": "Contact person's name from the email signature or body",
            },
            "customer_company": {
                "type": ["string", "null"],
                "description": "Company name of the shipper/customer",
            },
            "customer_email": {
                "type": ["string", "null"],
                "description": "Email address of the contact person",
            },
            "origin": {
                "type": ["string", "null"],
                "description": "Pickup location — city/state or metro area is sufficient (e.g., 'Dallas, TX' or 'DFW area'). Do NOT require a street address.",
            },
            "destination": {
                "type": ["string", "null"],
                "description": "Delivery location — city/state or metro area is sufficient (e.g., 'Atlanta, GA' or 'Bay Area, CA'). Do NOT require a street address.",
            },
            "equipment_type": {
                "type": ["string", "null"],
                "description": "Truck/trailer type: flatbed, van, reefer, box truck, step deck, etc.",
            },
            "truck_count": {
                "type": ["integer", "null"],
                "description": "Number of trucks needed",
            },
            "commodity": {
                "type": ["string", "null"],
                "description": "What is being shipped (e.g., 'steel coils', 'lumber')",
            },
            "weight_lbs": {
                "type": ["integer", "null"],
                "description": "Approximate weight per truck in pounds",
            },
            "pickup_date": {
                "type": ["string", "null"],
                "description": "Requested pickup date in YYYY-MM-DD format. Convert relative dates (e.g., 'next Tuesday') to absolute dates.",
            },
            "delivery_date": {
                "type": ["string", "null"],
                "description": "Requested delivery date in YYYY-MM-DD format",
            },
            "special_requirements": {
                "type": ["string", "null"],
                "description": "Any special requirements: tarping, lift gate, driver unload, temperature control, permits, insurance minimums, hazmat, appointment times, etc.",
            },
            "confidence": {
                "type": "object",
                "description": "Confidence score (0.0 to 1.0) for each key field. 1.0 = explicitly stated, 0.0 = not found, 0.5-0.9 = inferred with varying certainty.",
                "properties": {
                    "origin": {"type": "number", "minimum": 0, "maximum": 1},
                    "destination": {"type": "number", "minimum": 0, "maximum": 1},
                    "equipment_type": {"type": "number", "minimum": 0, "maximum": 1},
                    "truck_count": {"type": "number", "minimum": 0, "maximum": 1},
                    "commodity": {"type": "number", "minimum": 0, "maximum": 1},
                    "weight_lbs": {"type": "number", "minimum": 0, "maximum": 1},
                },
                "required": ["origin", "destination", "equipment_type", "truck_count", "commodity", "weight_lbs"],
            },
        },
        "required": [
            "customer_name", "customer_company", "customer_email",
            "origin", "destination", "equipment_type", "truck_count",
            "commodity", "weight_lbs", "pickup_date", "delivery_date",
            "special_requirements", "confidence",
        ],
    },
)


SYSTEM_PROMPT = """You are a freight logistics assistant working for a freight broker. Your job is to extract structured quote request (RFQ) information from inbound shipper emails.

Instructions:
- Extract every field you can find from the email content.
- If a field is not mentioned or cannot be determined, set it to null.
- For dates, convert relative references (e.g., "next Tuesday", "tomorrow", "this Friday") to absolute YYYY-MM-DD format. Today's date will be provided.
- For weight, extract per-truck weight in pounds. If a total weight is given for multiple trucks, divide by truck count.
- For equipment, normalize to standard types: flatbed, van, reefer, step deck, box truck, tanker, etc.
- For origin and destination, city and state is sufficient — do NOT ask for or expect a street address. Metro area names (e.g., "DFW area", "Bay Area") are also acceptable with high confidence. If only a city is given without a state, include the city and set confidence to 0.8 (still usable).
- Capture ALL special requirements mentioned anywhere in the email: tarping, lift gate, driver unload/assist, inside delivery, temperature requirements, permits, insurance minimums, appointment windows, hazmat, etc.
- Set confidence scores honestly:
  - 1.0 = field explicitly stated in clear terms
  - 0.9 = field clearly stated but minor ambiguity (e.g., abbreviation)
  - 0.7-0.8 = field reasonably inferred from context
  - 0.4-0.6 = field guessed with significant uncertainty
  - 0.0 = field not found in the email at all

Use the extract_rfq tool to return your results."""


def extract_rfq(
    db: Session,
    message_id: int,
    today_date: Optional[str] = None,
) -> Optional[RFQ]:
    """
    Extract structured RFQ fields from an inbound email message.

    This is the main entry point for the extraction agent. It reads the
    message, calls the LLM with the tool-use schema, and persists the
    extracted data as a new RFQ.

    Args:
        db: SQLAlchemy session.
        message_id: ID of the message to extract from (must exist in messages table).
        today_date: Today's date as YYYY-MM-DD string, used for resolving relative
                    dates in emails. Defaults to today if not provided.

    Returns:
        The newly created RFQ with extracted fields and confidence scores,
        or None if the message wasn't found.

    Side effects:
        - Creates an agent_run row (via run tracking service)
        - Creates agent_calls rows (via call_llm)
        - Creates a new rfqs row with extracted fields
        - Creates an audit_events row for the RFQ timeline
        - Sets message.rfq_id to link the message to the new RFQ
    """
    # Load the message
    message = db.query(Message).filter(Message.id == message_id).first()
    if not message:
        logger.error("Message %d not found — cannot extract", message_id)
        return None

    # Resolve today's date for the system prompt (helps LLM convert relative dates)
    if not today_date:
        today_date = datetime.utcnow().strftime("%Y-%m-%d")

    # Start an agent run to track this extraction (C4 — visible reasoning)
    run = start_run(
        db,
        workflow_name="RFQ Extraction",
        rfq_id=None,  # We don't have an RFQ yet — we're creating one
        trigger_source="new_email",
    )

    try:
        # Build the user prompt with the email content and today's date.
        # For re-extractions (reply to existing RFQ), include current RFQ
        # fields so the LLM knows what's already captured (#167).
        existing_rfq = None
        if message.rfq_id:
            existing_rfq = db.query(RFQ).filter(RFQ.id == message.rfq_id).first()
        user_prompt = _build_user_prompt(message, today_date, existing_rfq)

        # Call the LLM with the extraction tool schema.
        # call_llm handles: cost cap check (C5), provider selection, logging to
        # agent_calls (C4), and error handling.
        response = call_llm(
            db=db,
            run_id=run.id,
            agent_name="extraction",
            system_prompt=SYSTEM_PROMPT,
            user_prompt=user_prompt,
            tools=[EXTRACT_RFQ_TOOL],
            temperature=0.0,  # Deterministic for consistent extraction
        )

        # Parse the tool-use result — the LLM should have called extract_rfq
        extracted = _parse_tool_response(response)
        if not extracted:
            logger.warning("LLM did not call extract_rfq tool for message %d", message_id)
            fail_run(db, run.id, "LLM did not return tool-use result")
            return None

        # If the message is already linked to an RFQ (reply/clarification),
        # update the existing RFQ instead of creating a new one.
        if message.rfq_id:
            rfq = db.query(RFQ).filter(RFQ.id == message.rfq_id).first()
            if rfq:
                rfq = _update_rfq_from_extraction(db, rfq, extracted)
                logger.info("Updated existing RFQ %d with new details from message %d", rfq.id, message_id)
            else:
                rfq = _create_rfq_from_extraction(db, message, extracted)
                message.rfq_id = rfq.id
        else:
            # Create a brand new RFQ
            rfq = _create_rfq_from_extraction(db, message, extracted)
            message.rfq_id = rfq.id

        # Log an audit event for the RFQ detail timeline (C4)
        _log_audit_event(db, rfq, message, extracted)

        # Update the run with the RFQ ID now that we have one
        run.rfq_id = rfq.id
        db.commit()

        # Finish the run — rolls up cost and tokens from the LLM call
        finish_run(db, run.id)

        # Chain to the next agent based on the RFQ state.
        # All chaining goes through the job queue — agents never call
        # each other directly. The worker picks up and dispatches.
        from backend.worker import enqueue_job

        if rfq.state == RFQState.NEEDS_CLARIFICATION:
            # Missing or low-confidence fields — draft a follow-up email
            enqueue_job(db, "validation", {"rfq_id": rfq.id}, rfq_id=rfq.id)
            logger.info("RFQ %d needs clarification — validation job enqueued", rfq.id)
        elif rfq.state == RFQState.READY_TO_QUOTE:
            # All fields present and confident — generate quote sheet
            enqueue_job(db, "quote_sheet", {"rfq_id": rfq.id}, rfq_id=rfq.id)
            logger.info("RFQ %d ready to quote — quote sheet job enqueued", rfq.id)

        logger.info(
            "Extraction complete: message=%d -> rfq=%d origin=%s destination=%s confidence=%s",
            message_id, rfq.id, rfq.origin, rfq.destination,
            json.dumps(extracted.get("confidence", {})),
        )

        return rfq

    except Exception as e:
        logger.exception("Extraction failed for message %d: %s", message_id, e)
        fail_run(db, run.id, str(e))
        raise


def _build_user_prompt(message: Message, today_date: str, existing_rfq: Optional[RFQ] = None) -> str:
    """
    Build the user prompt from the email message.

    For new emails: includes sender, subject, body, and today's date.
    For replies to existing RFQs (#167): also includes the current RFQ fields
    so the LLM knows what's already captured and only needs to find new info.
    This prevents the LLM from returning 0.0 confidence for fields that simply
    aren't mentioned in a short reply like "2 vans, date is 5/1".
    """
    parts = [f"Today's date: {today_date}\n"]

    # For re-extractions, include existing RFQ context so the LLM preserves
    # confidence for fields already captured (#167)
    if existing_rfq:
        confidence = existing_rfq.confidence_scores or {}
        parts.append("EXISTING RFQ DATA (already captured — preserve these if the reply doesn't update them):")
        parts.append(f"  Origin: {existing_rfq.origin or 'NOT SET'} (confidence: {confidence.get('origin', 0):.2f})")
        parts.append(f"  Destination: {existing_rfq.destination or 'NOT SET'} (confidence: {confidence.get('destination', 0):.2f})")
        parts.append(f"  Equipment: {existing_rfq.equipment_type or 'NOT SET'} (confidence: {confidence.get('equipment_type', 0):.2f})")
        parts.append(f"  Truck count: {existing_rfq.truck_count or 'NOT SET'} (confidence: {confidence.get('truck_count', 0):.2f})")
        parts.append(f"  Commodity: {existing_rfq.commodity or 'NOT SET'} (confidence: {confidence.get('commodity', 0):.2f})")
        parts.append(f"  Weight: {existing_rfq.weight_lbs or 'NOT SET'} lbs (confidence: {confidence.get('weight_lbs', 0):.2f})")
        parts.append(f"  Pickup date: {existing_rfq.pickup_date.strftime('%Y-%m-%d') if existing_rfq.pickup_date else 'NOT SET'}")
        parts.append(f"  Delivery date: {existing_rfq.delivery_date.strftime('%Y-%m-%d') if existing_rfq.delivery_date else 'NOT SET'}")
        if existing_rfq.special_requirements:
            parts.append(f"  Special requirements: {existing_rfq.special_requirements}")
        parts.append("")
        parts.append("CUSTOMER REPLY (extract any NEW or UPDATED information — keep existing field values and confidence for anything not mentioned):")
        parts.append("")

    parts.append(f"From: {message.sender}")
    parts.append(f"Subject: {message.subject or '(no subject)'}")
    parts.append("")
    parts.append(message.body or "")

    return "\n".join(parts)


def _parse_tool_response(response) -> Optional[dict[str, Any]]:
    """
    Extract the structured data from the LLM's tool-use response.

    The LLM should have called the extract_rfq tool exactly once.
    Returns the tool's input dict (the extracted fields), or None
    if the tool wasn't called.
    """
    if not response.tool_calls:
        return None

    # Find the extract_rfq tool call (there should be exactly one)
    for tool_call in response.tool_calls:
        if tool_call.get("name") == "extract_rfq":
            return tool_call.get("input", {})

    return None


def _create_rfq_from_extraction(
    db: Session,
    message: Message,
    extracted: dict[str, Any],
) -> RFQ:
    """
    Create a new RFQ record from the extracted fields.

    Maps the LLM's tool-use output to the rfqs table columns. Sets the
    initial state based on whether required fields are present:
    - All required fields present with high confidence -> ready_to_quote
    - Missing required fields or low confidence -> needs_clarification

    The confidence scores are stored as JSONB for the HITL escalation
    policy (#23) to use when deciding whether to flag for review.
    """
    confidence = extracted.get("confidence", {})

    # Parse dates — they come as strings from the LLM tool output.
    # Auto-swap if delivery is before pickup (#155).
    pickup_date = _parse_date(extracted.get("pickup_date"))
    delivery_date = _parse_date(extracted.get("delivery_date"))
    if pickup_date and delivery_date and delivery_date < pickup_date:
        logger.info("Swapping pickup/delivery dates — delivery %s was before pickup %s", delivery_date, pickup_date)
        pickup_date, delivery_date = delivery_date, pickup_date

    # Generate smart reference number (#176)
    from backend.services.ref_number import generate_ref_number
    ref_number = generate_ref_number(db)

    rfq = RFQ(
        ref_number=ref_number,
        customer_name=extracted.get("customer_name"),
        customer_email=extracted.get("customer_email") or message.sender,
        customer_company=extracted.get("customer_company"),
        origin=extracted.get("origin"),
        destination=extracted.get("destination"),
        equipment_type=extracted.get("equipment_type"),
        truck_count=extracted.get("truck_count"),
        commodity=extracted.get("commodity"),
        weight_lbs=extracted.get("weight_lbs"),
        pickup_date=pickup_date,
        delivery_date=delivery_date,
        special_requirements=extracted.get("special_requirements"),
        confidence_scores=confidence,
        # Determine initial state based on completeness and confidence
        state=_determine_initial_state(extracted, confidence),
    )

    db.add(rfq)
    db.flush()  # Get the ID before committing

    return rfq


def _update_rfq_from_extraction(
    db: Session,
    rfq: RFQ,
    extracted: dict[str, Any],
) -> RFQ:
    """
    Update an existing RFQ with newly extracted fields from a reply/clarification.

    Only fills in fields that were previously null or had low confidence.
    Re-evaluates the state after updating — may promote from needs_clarification
    to ready_to_quote if the reply filled in the missing details.
    """
    confidence = extracted.get("confidence", {})

    # Update fields that are currently null or were low confidence
    field_map = {
        "customer_name": "customer_name",
        "customer_company": "customer_company",
        "origin": "origin",
        "destination": "destination",
        "equipment_type": "equipment_type",
        "truck_count": "truck_count",
        "commodity": "commodity",
        "weight_lbs": "weight_lbs",
        "special_requirements": "special_requirements",
    }

    for extract_key, rfq_attr in field_map.items():
        new_val = extracted.get(extract_key)
        old_val = getattr(rfq, rfq_attr)
        if new_val and (not old_val):
            setattr(rfq, rfq_attr, new_val)

    # Update dates — auto-swap if delivery is before pickup (#155)
    pickup = _parse_date(extracted.get("pickup_date"))
    delivery = _parse_date(extracted.get("delivery_date"))
    if pickup and not rfq.pickup_date:
        rfq.pickup_date = pickup
    if delivery and not rfq.delivery_date:
        rfq.delivery_date = delivery
    if rfq.pickup_date and rfq.delivery_date and rfq.delivery_date < rfq.pickup_date:
        rfq.pickup_date, rfq.delivery_date = rfq.delivery_date, rfq.pickup_date

    # Merge confidence scores — only UPGRADE, never downgrade.
    # When re-extracting from a short reply like "yea 1 truck", the LLM
    # can't find origin/destination in that text and returns 0.0 confidence.
    # Without this guard, those 0.0 scores overwrite the original good scores
    # from the first extraction, trapping the RFQ in a clarification loop.
    if rfq.confidence_scores and confidence:
        merged = dict(rfq.confidence_scores)
        for field_name, new_score in confidence.items():
            old_score = merged.get(field_name, 0.0)
            merged[field_name] = max(old_score, new_score)
        rfq.confidence_scores = merged
    elif confidence:
        rfq.confidence_scores = confidence

    # Re-evaluate state using the MERGED confidence (not just the new extraction's)
    merged_confidence = rfq.confidence_scores or confidence or {}
    # Build a merged extracted dict that reflects what the RFQ actually has
    merged_extracted = {}
    for key in ["origin", "destination", "equipment_type", "truck_count", "commodity", "weight_lbs"]:
        merged_extracted[key] = getattr(rfq, key, None)
    merged_extracted["confidence"] = merged_confidence

    new_state = _determine_initial_state(merged_extracted, merged_confidence)
    if new_state == RFQState.READY_TO_QUOTE and rfq.state == RFQState.NEEDS_CLARIFICATION:
        from backend.services.rfq_state_machine import transition_rfq
        try:
            transition_rfq(db, rfq.id, RFQState.READY_TO_QUOTE, actor="extraction_agent",
                          reason="Clarification reply filled in missing details")
            # Refresh the ORM object so the chaining code in extract_rfq()
            # sees the updated state and enqueues quote_sheet (not validation)
            db.refresh(rfq)
        except Exception:
            pass

    db.flush()
    return rfq


def _determine_initial_state(
    extracted: dict[str, Any],
    confidence: dict[str, float],
    policy=None,
) -> RFQState:
    """
    Decide the initial RFQ state based on field completeness and confidence.

    Uses the escalation policy (#23) to check per-field thresholds. If no
    policy is provided, uses the default (0.90 for all fields).

    Required fields (per FR-AG-2): origin, destination, equipment_type,
    truck_count, commodity. If any is null or below threshold -> needs_clarification.
    """
    from backend.services.escalation_policy import (
        EscalationPolicy,
        REQUIRED_FIELDS,
    )

    if policy is None:
        policy = EscalationPolicy()

    for field_name in REQUIRED_FIELDS:
        threshold = policy.get_threshold(field_name)

        if extracted.get(field_name) is None:
            logger.info("Field '%s' is null — RFQ needs clarification", field_name)
            return RFQState.NEEDS_CLARIFICATION

        field_confidence = confidence.get(field_name, 0.0)
        if field_confidence < threshold:
            logger.info(
                "Field '%s' confidence %.2f < %.2f — RFQ needs clarification",
                field_name, field_confidence, threshold,
            )
            return RFQState.NEEDS_CLARIFICATION

    return RFQState.READY_TO_QUOTE


def _log_audit_event(
    db: Session,
    rfq: RFQ,
    message: Message,
    extracted: dict[str, Any],
) -> None:
    """
    Create an audit event for the RFQ detail timeline.

    Uses plain English per C3 — the broker sees "Pulled quote request from
    email" in the timeline, not "extraction_completed" or "agent_call_success".
    Technical details are in the event_data JSONB for drill-down.
    """
    from backend.services.escalation_policy import DEFAULT_THRESHOLD

    confidence = extracted.get("confidence", {})
    low_confidence_fields = [
        k for k, v in confidence.items() if v < DEFAULT_THRESHOLD
    ]

    # Build a human-readable description (C3 — plain English)
    if rfq.state == RFQState.NEEDS_CLARIFICATION:
        description = (
            f"Pulled quote request from {message.sender} — "
            f"needs clarification on: {', '.join(low_confidence_fields) or 'missing fields'}"
        )
    else:
        description = (
            f"Pulled quote request from {message.sender} — "
            f"{rfq.origin} to {rfq.destination}, "
            f"{rfq.truck_count} {rfq.equipment_type or 'truck'}(s)"
        )

    event = AuditEvent(
        rfq_id=rfq.id,
        event_type="rfq_extracted",
        actor="extraction_agent",
        description=description,
        event_data={
            "message_id": message.id,
            "confidence_scores": confidence,
            "low_confidence_fields": low_confidence_fields,
            "initial_state": rfq.state.value,
        },
    )
    db.add(event)


def _parse_date(date_str: Optional[str]) -> Optional[datetime]:
    """
    Parse a date string from the LLM output (expected YYYY-MM-DD format).

    Returns None if the string is null, empty, or unparseable.
    The LLM is instructed to return dates in YYYY-MM-DD format, but
    we handle failures gracefully rather than crashing.
    """
    if not date_str:
        return None
    try:
        return datetime.strptime(date_str, "%Y-%m-%d")
    except ValueError:
        logger.warning("Could not parse date '%s' — expected YYYY-MM-DD", date_str)
        return None
