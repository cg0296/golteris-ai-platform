"""
backend/agents/carrier_bid_parser.py — Carrier quote response parser (#33).

Parses inbound carrier reply emails into structured CarrierBid records using
LLM tool-use. When a carrier responds to a distributed RFQ with pricing,
this agent extracts the rate, terms, availability, and notes.

How it works:
    1. Reads a carrier reply message from the `messages` table
    2. Creates an agent_run via the run tracking service
    3. Calls the LLM with the parse_carrier_bid tool schema
    4. The LLM returns structured bid fields
    5. Persists a CarrierBid row linked to the RFQ
    6. Transitions the RFQ to quotes_received if this is the first bid
    7. Logs audit events for the timeline
    8. Flags ambiguous quotes for review if confidence is low

Called by:
    - The background worker via JOB_DISPATCH["parse_carrier_bid"]
    - Manually for testing: `parse_carrier_bid(db, message_id)`

Cross-cutting constraints:
    C4 — Every LLM call logged to agent_calls (automatic via call_llm)
    C5 — Cost caps enforced at call_llm level
"""

import json
import logging
from datetime import datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy.orm import Session

from backend.db.models import (
    AuditEvent,
    CarrierBid,
    Message,
    MessageDirection,
    RFQ,
    RFQState,
)
from backend.llm.client import call_llm
from backend.llm.provider import ToolDefinition
from backend.services.agent_runs import fail_run, finish_run, start_run

logger = logging.getLogger("golteris.agents.carrier_bid_parser")


# ---------------------------------------------------------------------------
# Tool-use schema — defines what structured data the LLM extracts from
# a carrier's reply email. Handles common formats: all-in rates,
# linehaul + FSC, per-mile, and flat rates.
# ---------------------------------------------------------------------------

PARSE_CARRIER_BID_TOOL = ToolDefinition(
    name="parse_carrier_bid",
    description=(
        "Extract structured bid information from a carrier's email reply to an RFQ. "
        "The carrier is responding to a freight quote request with their pricing. "
        "Extract the rate, currency, rate structure, terms, availability, and any notes."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "rate": {
                "type": ["number", "null"],
                "description": "The quoted rate amount (numeric, e.g., 2850.00). This is the total rate, not per-mile.",
            },
            "currency": {
                "type": "string",
                "description": "Currency code (default: USD)",
                "default": "USD",
            },
            "rate_type": {
                "type": ["string", "null"],
                "description": "Rate structure: 'all_in' (single price), 'linehaul_plus_fsc' (base + fuel surcharge), 'per_mile', or 'flat'",
                "enum": ["all_in", "linehaul_plus_fsc", "per_mile", "flat", None],
            },
            "terms": {
                "type": ["string", "null"],
                "description": "Payment terms or conditions mentioned (e.g., 'Net 30', 'quick pay available')",
            },
            "availability": {
                "type": ["string", "null"],
                "description": "When the carrier can pick up (e.g., 'Available Monday', 'Next week')",
            },
            "notes": {
                "type": ["string", "null"],
                "description": "Any additional notes, restrictions, or conditions from the carrier",
            },
            "confidence": {
                "type": "number",
                "minimum": 0,
                "maximum": 1,
                "description": "Overall confidence in the extraction (1.0 = clear quote, <0.7 = ambiguous)",
            },
        },
        "required": ["rate", "currency", "confidence"],
    },
)

# Confidence threshold — below this, the bid is flagged for human review
BID_CONFIDENCE_THRESHOLD = 0.7


def parse_carrier_bid(db: Session, message_id: int) -> Optional[CarrierBid]:
    """
    Parse a carrier reply email into a structured CarrierBid record.

    This is the main entry point called by the worker. It:
    1. Loads the message and validates it's a carrier reply
    2. Calls the LLM to extract bid details
    3. Creates a CarrierBid row
    4. Transitions the RFQ state if appropriate
    5. Creates audit events

    Args:
        db: SQLAlchemy session
        message_id: ID of the carrier's reply message

    Returns:
        The created CarrierBid, or None if parsing failed.
    """
    message = db.query(Message).filter(Message.id == message_id).first()
    if not message:
        logger.error("Carrier bid parser: message %d not found", message_id)
        return None

    if not message.rfq_id:
        logger.warning("Carrier bid parser: message %d has no RFQ attached", message_id)
        return None

    rfq = db.query(RFQ).filter(RFQ.id == message.rfq_id).first()
    if not rfq:
        logger.error("Carrier bid parser: RFQ %d not found for message %d", message.rfq_id, message_id)
        return None

    # Start an agent run for tracking (C4, C5)
    run = start_run(db, workflow_name="carrier_bid_parser", rfq_id=rfq.id)

    try:
        # Build the prompt with the carrier's email content
        system_prompt = (
            "You are a freight logistics assistant. A carrier has replied to a Rate "
            "Request (RFQ) with their pricing. Extract the bid details from their email. "
            "If the quote is unclear or ambiguous, set confidence below 0.7."
        )
        user_prompt = (
            f"Parse this carrier reply into a structured bid:\n\n"
            f"From: {message.sender}\n"
            f"Subject: {message.subject or '(no subject)'}\n\n"
            f"{message.body}"
        )

        # Call the LLM with tool-use to extract structured bid data
        result = call_llm(
            agent_name="carrier_bid_parser",
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            tools=[PARSE_CARRIER_BID_TOOL],
            run_id=run.id,
            db=db,
        )

        if not result or not result.tool_calls:
            logger.warning("Carrier bid parser: LLM returned no tool calls for message %d", message_id)
            fail_run(db, run.id, "LLM returned no tool calls")
            return None

        # Extract the parsed bid data from the tool call
        bid_data = result.tool_calls[0].get("input", {})
        confidence = bid_data.get("confidence", 0)

        # Create the CarrierBid record — resolve carrier name from DB or sender (#174)
        carrier_bid = CarrierBid(
            rfq_id=rfq.id,
            carrier_name=_resolve_carrier_name(db, message.sender),
            carrier_email=message.sender,
            rate=Decimal(str(bid_data["rate"])) if bid_data.get("rate") else None,
            currency=bid_data.get("currency", "USD"),
            rate_type=bid_data.get("rate_type"),
            terms=bid_data.get("terms"),
            availability=bid_data.get("availability"),
            notes=bid_data.get("notes"),
            raw_response=bid_data,
            message_id=message.id,
            received_at=message.received_at or datetime.utcnow(),
        )
        db.add(carrier_bid)
        db.flush()

        # Create audit event — the broker sees "Carrier quoted $X" in the timeline
        rate_str = f"${bid_data['rate']:,.2f}" if bid_data.get("rate") else "unknown amount"
        event = AuditEvent(
            rfq_id=rfq.id,
            event_type="carrier_bid_received",
            actor="carrier_bid_parser",
            description=f"{carrier_bid.carrier_name} quoted {rate_str} for {rfq.origin} to {rfq.destination}",
            event_data={
                "carrier_bid_id": carrier_bid.id,
                "carrier_name": carrier_bid.carrier_name,
                "rate": float(carrier_bid.rate) if carrier_bid.rate else None,
                "confidence": confidence,
            },
        )
        db.add(event)

        # Flag ambiguous bids for human review
        if confidence < BID_CONFIDENCE_THRESHOLD:
            review_event = AuditEvent(
                rfq_id=rfq.id,
                event_type="escalated_for_review",
                actor="carrier_bid_parser",
                description=f"Carrier bid from {carrier_bid.carrier_name} flagged — low confidence ({confidence:.0%})",
                event_data={
                    "carrier_bid_id": carrier_bid.id,
                    "confidence": confidence,
                    "reason": "Ambiguous quote — needs human review",
                },
            )
            db.add(review_event)

        # Transition RFQ to quotes_received if this is the first bid
        # and the RFQ is in waiting_on_carriers state
        if rfq.state == RFQState.WAITING_ON_CARRIERS:
            from backend.services.rfq_state_machine import transition_rfq
            try:
                transition_rfq(
                    db, rfq.id, RFQState.QUOTES_RECEIVED,
                    actor="carrier_bid_parser",
                    reason=f"First carrier bid received from {carrier_bid.carrier_name}",
                )
            except Exception:
                pass  # Already transitioned or not allowed — fine

        db.commit()

        # Finish the agent run with success
        finish_run(db, run.id, status="completed")

        logger.info(
            "Parsed carrier bid: rfq=%d carrier=%s rate=%s confidence=%.2f",
            rfq.id, carrier_bid.carrier_name, rate_str, confidence,
        )
        return carrier_bid

    except Exception as e:
        logger.exception("Carrier bid parser failed for message %d: %s", message_id, e)
        fail_run(db, run.id, str(e))
        db.rollback()
        return None


def _resolve_carrier_name(db, sender: str) -> str:
    """
    Resolve a human-readable carrier name from the sender field.

    Resolution order:
    1. Display name from "Name <email>" format (e.g., "Eugene" from "Eugene <e@gmail.com>")
    2. Carrier name from the carriers table matched by email
    3. Domain-based fallback (e.g., "gmail.com" → "Gmail")

    This prevents carriers showing up as "Gmail" when their email is @gmail.com.
    """
    from backend.db.models import Carrier

    # 1. Try display name from sender field
    if "<" in (sender or ""):
        display_name = sender.split("<")[0].strip()
        if display_name and display_name.lower() not in ("", "unknown"):
            return display_name

    # 2. Try matching email to a known carrier in the DB
    email_addr = sender
    if "<" in (sender or "") and ">" in (sender or ""):
        email_addr = sender.split("<")[1].split(">")[0]
    try:
        carrier = db.query(Carrier).filter(Carrier.email == email_addr).first()
        if carrier:
            return carrier.name
    except Exception:
        pass

    # 3. Fallback: extract from domain
    try:
        domain = email_addr.split("@")[1].split(".")[0]
        name = ""
        for char in domain:
            if char.isupper() and name and not name.endswith(" "):
                name += " "
            name += char
        return name.replace("-", " ").replace("_", " ").title()
    except (IndexError, AttributeError):
        return sender or "Unknown Carrier"
