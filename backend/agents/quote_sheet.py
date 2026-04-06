"""
backend/agents/quote_sheet.py — Structured quote sheet generator.

Takes a complete RFQ (state=ready_to_quote) and produces a structured,
carrier-facing quote sheet. This is the output artifact the broker reviews
before sending to carriers — it transforms messy email data into a clean,
professional format.

Pipeline position:
    Extraction (#24) creates RFQ -> Validation (#15) handles missing info
    -> This agent packages the complete RFQ into a carrier-ready sheet
    -> Carrier distribution (#32) sends it out

The quote sheet is NOT an email draft — it's a structured data format that
carrier distribution (#32) will use to compose personalized carrier emails.
It's also what the broker sees in the RFQ detail view as the "quote summary."

Called by:
    - The background worker when an RFQ transitions to ready_to_quote
    - Manually for testing: `generate_quote_sheet(db, rfq_id)`

Cross-cutting constraints:
    C3 — Sheet uses professional broker/carrier language
    C4 — LLM call logged via agent_calls, run tracked via agent_runs
    C5 — Cost caps enforced at call_llm level
    FR-AG-5 — A structured quote sheet can be generated from a complete RFQ
"""

import json
import logging
from datetime import datetime
from typing import Any, Optional

from sqlalchemy.orm import Session

from backend.db.models import AuditEvent, RFQ, RFQState
from backend.llm.client import call_llm
from backend.llm.provider import ToolDefinition
from backend.services.agent_runs import fail_run, finish_run, start_run

logger = logging.getLogger("golteris.agents.quote_sheet")


# ---------------------------------------------------------------------------
# Tool-use schema — the LLM returns a structured quote sheet
# ---------------------------------------------------------------------------

QUOTE_SHEET_TOOL = ToolDefinition(
    name="generate_quote_sheet",
    description=(
        "Generate a structured freight quote sheet from RFQ data. The sheet is "
        "formatted for carrier distribution — it's what carriers receive when "
        "the broker sends out a request for pricing."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "reference_id": {
                "type": "string",
                "description": "Quote reference number (e.g., 'BLT-2026-0042')",
            },
            "summary": {
                "type": "string",
                "description": "One-line summary of the load (e.g., '3 flatbeds, Dallas TX to Atlanta GA, steel coils')",
            },
            "lanes": {
                "type": "array",
                "description": "One entry per lane (origin-destination pair). Most RFQs have one lane.",
                "items": {
                    "type": "object",
                    "properties": {
                        "origin": {"type": "string", "description": "Pickup city, state"},
                        "destination": {"type": "string", "description": "Delivery city, state"},
                        "equipment": {"type": "string", "description": "Truck/trailer type"},
                        "truck_count": {"type": "integer", "description": "Number of trucks for this lane"},
                        "commodity": {"type": "string", "description": "What is being shipped"},
                        "weight_lbs": {"type": ["integer", "null"], "description": "Weight per truck in lbs"},
                        "pickup_date": {"type": ["string", "null"], "description": "Pickup date or window"},
                        "delivery_date": {"type": ["string", "null"], "description": "Delivery date or window"},
                    },
                    "required": ["origin", "destination", "equipment", "truck_count", "commodity"],
                },
            },
            "special_requirements": {
                "type": ["string", "null"],
                "description": "Any special requirements: tarping, permits, lift gate, temperature, insurance, etc.",
            },
            "notes": {
                "type": ["string", "null"],
                "description": "Additional notes for carriers (e.g., tight yard access, appointment required)",
            },
            "response_deadline": {
                "type": ["string", "null"],
                "description": "When the broker needs rates back by",
            },
        },
        "required": ["reference_id", "summary", "lanes"],
    },
)


SYSTEM_PROMPT = """You are a freight broker assistant creating a structured quote sheet from RFQ data. The quote sheet will be sent to carriers to request pricing.

Rules:
- Format the data clearly and professionally — this is what carriers see.
- Create a reference ID in the format BLT-YYYY-NNNN (year + RFQ ID zero-padded).
- Write a concise one-line summary: "[truck_count] [equipment], [origin] to [destination], [commodity]"
- Organize into lanes (one per origin-destination pair). Most RFQs are single-lane.
- Include all special requirements — carriers need this to quote accurately.
- Add practical notes that help carriers (yard access issues, appointment windows, etc.).
- If pickup is soon (within 3 days), note urgency in the response_deadline.
- Use standard freight industry terminology.

Use the generate_quote_sheet tool to return the structured sheet."""


def generate_quote_sheet(
    db: Session,
    rfq_id: int,
) -> Optional[dict[str, Any]]:
    """
    Generate a structured quote sheet from a complete RFQ.

    Only works for RFQs in ready_to_quote state — if the RFQ still needs
    clarification, the quote sheet would be incomplete and misleading.

    Args:
        db: SQLAlchemy session.
        rfq_id: The RFQ to generate a sheet for.

    Returns:
        The structured quote sheet as a dict (matches QUOTE_SHEET_TOOL schema),
        or None if the RFQ doesn't exist or isn't ready.

    Side effects:
        - Creates an agent_run and agent_calls for traceability (C4)
        - Creates an audit event for the RFQ timeline
    """
    rfq = db.query(RFQ).filter(RFQ.id == rfq_id).first()
    if not rfq:
        logger.error("RFQ %d not found", rfq_id)
        return None

    # Only generate sheets for RFQs that are ready to quote
    if rfq.state != RFQState.READY_TO_QUOTE:
        logger.warning(
            "RFQ %d is in %s state, not ready_to_quote — cannot generate quote sheet",
            rfq_id, rfq.state.value,
        )
        return None

    run = start_run(
        db,
        workflow_name="Quote Sheet Generation",
        rfq_id=rfq_id,
        trigger_source="state_ready_to_quote",
    )

    try:
        user_prompt = _build_user_prompt(rfq)

        response = call_llm(
            db=db,
            run_id=run.id,
            agent_name="quote_sheet",
            system_prompt=SYSTEM_PROMPT,
            user_prompt=user_prompt,
            tools=[QUOTE_SHEET_TOOL],
            temperature=0.0,
        )

        sheet = _parse_tool_response(response)
        if not sheet:
            logger.warning("LLM did not call generate_quote_sheet tool for RFQ %d", rfq_id)
            fail_run(db, run.id, "LLM did not return tool-use result")
            return None

        # Log audit event — plain English per C3
        _log_audit_event(db, rfq, sheet)

        db.commit()
        finish_run(db, run.id)

        logger.info(
            "Quote sheet generated for RFQ %d: %s",
            rfq_id, sheet.get("summary", ""),
        )

        return sheet

    except Exception as e:
        logger.exception("Quote sheet generation failed for RFQ %d: %s", rfq_id, e)
        fail_run(db, run.id, str(e))
        raise


def _build_user_prompt(rfq: RFQ) -> str:
    """
    Build the user prompt from the RFQ data.

    Provides all extracted fields so the LLM can structure them into
    a professional carrier-facing format.
    """
    lines = [
        f"RFQ ID: {rfq.id}",
        f"Customer: {rfq.customer_name or 'Unknown'} at {rfq.customer_company or 'Unknown'}",
        f"Origin: {rfq.origin or 'Not specified'}",
        f"Destination: {rfq.destination or 'Not specified'}",
        f"Equipment: {rfq.equipment_type or 'Not specified'}",
        f"Truck count: {rfq.truck_count or 'Not specified'}",
        f"Commodity: {rfq.commodity or 'Not specified'}",
        f"Weight: {rfq.weight_lbs} lbs" if rfq.weight_lbs else "Weight: Not specified",
        f"Pickup date: {rfq.pickup_date.strftime('%Y-%m-%d') if rfq.pickup_date else 'Not specified'}",
        f"Delivery date: {rfq.delivery_date.strftime('%Y-%m-%d') if rfq.delivery_date else 'Not specified'}",
        f"Special requirements: {rfq.special_requirements or 'None'}",
        f"Today's date: {datetime.utcnow().strftime('%Y-%m-%d')}",
    ]
    return "\n".join(lines)


def _parse_tool_response(response) -> Optional[dict[str, Any]]:
    """Extract the structured quote sheet from the LLM's tool-use response."""
    if not response.tool_calls:
        return None

    for tool_call in response.tool_calls:
        if tool_call.get("name") == "generate_quote_sheet":
            return tool_call.get("input", {})

    return None


def _log_audit_event(db: Session, rfq: RFQ, sheet: dict) -> None:
    """
    Create an audit event for the RFQ timeline (C3 — plain English).

    The broker sees "Quote sheet prepared — ready for carrier distribution"
    not "quote_sheet_agent_completed."
    """
    lane_count = len(sheet.get("lanes", []))
    summary = sheet.get("summary", "")

    event = AuditEvent(
        rfq_id=rfq.id,
        event_type="quote_sheet_generated",
        actor="quote_sheet_agent",
        description=f"Quote sheet prepared — {summary}",
        event_data={
            "reference_id": sheet.get("reference_id"),
            "lane_count": lane_count,
            "has_special_requirements": bool(sheet.get("special_requirements")),
        },
    )
    db.add(event)
