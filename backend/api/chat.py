"""
backend/api/chat.py — Ask Golteris chat endpoint (#99, #161).

The chat agent can both answer questions AND take actions. It uses tool-use
to create RFQs, trigger workflows, change statuses, and look up info.

Endpoint:
    POST /api/chat — Send a message, get a response (may include actions)

Actions go through existing backend services, respecting all constraints:
    C2 — Outbound emails go through approval or auto-send gates
    C4 — All actions audited with actor="chat_agent"
    C5 — LLM calls go through the provider abstraction (cost caps)

Called by:
    The ChatBubble component (bottom-right of every page).
"""

import json
import logging
import os
from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from backend.db.database import get_db
from backend.db.models import (
    Approval,
    ApprovalStatus,
    AuditEvent,
    CarrierBid,
    Message,
    RFQ,
    RFQState,
)

logger = logging.getLogger("golteris.api.chat")

router = APIRouter(tags=["chat"])


class ChatRequest(BaseModel):
    message: str


# ---------------------------------------------------------------------------
# Tool definitions — actions the chat agent can take
# ---------------------------------------------------------------------------

CHAT_TOOLS = [
    {
        "name": "create_rfq",
        "description": (
            "Create a new RFQ (request for quote) from a natural language description. "
            "Use when the broker says things like 'Create an RFQ for 2 flatbeds from Dallas to Atlanta'."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "customer_name": {"type": "string", "description": "Customer/shipper name"},
                "customer_email": {"type": ["string", "null"], "description": "Customer email if provided"},
                "origin": {"type": "string", "description": "Pickup city and state"},
                "destination": {"type": "string", "description": "Delivery city and state"},
                "equipment_type": {"type": "string", "description": "Truck type (flatbed, dry van, reefer, etc.)"},
                "truck_count": {"type": "integer", "description": "Number of trucks needed"},
                "commodity": {"type": ["string", "null"], "description": "What is being shipped"},
                "weight_lbs": {"type": ["integer", "null"], "description": "Weight in pounds"},
                "pickup_date": {"type": ["string", "null"], "description": "Pickup date (YYYY-MM-DD)"},
                "delivery_date": {"type": ["string", "null"], "description": "Delivery date (YYYY-MM-DD)"},
                "special_requirements": {"type": ["string", "null"], "description": "Any special requirements"},
            },
            "required": ["origin", "destination", "equipment_type", "truck_count"],
        },
    },
    {
        "name": "change_rfq_status",
        "description": (
            "Change an RFQ's status. Use for 'Mark RFQ 35 as won', 'Cancel RFQ 35', "
            "'Move RFQ 35 to ready to quote', etc."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "rfq_id": {"type": "integer", "description": "The RFQ ID number"},
                "new_status": {
                    "type": "string",
                    "enum": ["needs_clarification", "ready_to_quote", "waiting_on_carriers",
                             "quotes_received", "waiting_on_broker", "quote_sent", "won", "lost", "cancelled"],
                    "description": "The new status to set",
                },
                "reason": {"type": "string", "description": "Why the status is being changed"},
            },
            "required": ["rfq_id", "new_status", "reason"],
        },
    },
    {
        "name": "send_to_carriers",
        "description": (
            "Send an RFQ to carriers for pricing. Use when the broker says "
            "'Send RFQ 35 to carriers' or 'Distribute RFQ 35'."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "rfq_id": {"type": "integer", "description": "The RFQ ID to distribute"},
            },
            "required": ["rfq_id"],
        },
    },
    {
        "name": "request_clarification",
        "description": (
            "Ask the customer for clarification on an RFQ. Triggers a follow-up email. "
            "Use when the broker says 'Ask for clarification on RFQ 35'."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "rfq_id": {"type": "integer", "description": "The RFQ ID"},
            },
            "required": ["rfq_id"],
        },
    },
    {
        "name": "regenerate_quote_sheet",
        "description": (
            "Regenerate the quote sheet for an RFQ. Use when the broker says "
            "'Regenerate quote sheet for RFQ 35' or 'Redo the quote sheet'."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "rfq_id": {"type": "integer", "description": "The RFQ ID"},
            },
            "required": ["rfq_id"],
        },
    },
    {
        "name": "lookup_rfq",
        "description": (
            "Look up detailed information about a specific RFQ. Use when the broker asks "
            "'Show me RFQ 35', 'What's the status of RFQ 35?', 'Details on RFQ 35'."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "rfq_id": {"type": "integer", "description": "The RFQ ID to look up"},
            },
            "required": ["rfq_id"],
        },
    },
]


# ---------------------------------------------------------------------------
# Chat endpoint
# ---------------------------------------------------------------------------

@router.post("/api/chat")
def chat(body: ChatRequest, db: Session = Depends(get_db)):
    """
    Answer a broker's question or take an action using tool-use (#161).

    The LLM decides whether to answer with text or call a tool.
    Tool calls are executed against existing backend services, and
    the result is formatted as a natural language response.
    """
    import anthropic

    # Build context from live data
    context = _build_context(db)

    client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))

    # Call with tools enabled — the LLM can answer OR take action
    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=1024,
        system=(
            f"You are Golteris, an AI freight logistics assistant for {_get_company_name(db)}. "
            "You help the broker manage RFQs, carriers, and shipments.\n\n"
            "You can both ANSWER QUESTIONS and TAKE ACTIONS using the tools provided.\n\n"
            "Rules:\n"
            "- Be concise and use plain business language\n"
            "- When the broker asks you to do something (create, send, change status), use the appropriate tool\n"
            "- When asking about data, answer from the context below\n"
            "- If you need an RFQ ID and the broker didn't specify, ask which one\n"
            "- After taking an action, confirm what you did in plain language\n"
            "- If you don't have enough data to answer, say so\n\n"
            f"CURRENT DATA:\n{context}"
        ),
        messages=[{"role": "user", "content": body.message}],
        tools=CHAT_TOOLS,
    )

    # Handle the response — could be text, tool-use, or both
    reply_parts = []
    actions_taken = []

    for block in response.content:
        if block.type == "text":
            reply_parts.append(block.text)
        elif block.type == "tool_use":
            # Execute the tool and collect the result
            result = _execute_tool(db, block.name, block.input)
            actions_taken.append({
                "tool": block.name,
                "input": block.input,
                "result": result,
            })
            reply_parts.append(result["message"])

    reply = "\n\n".join(reply_parts) if reply_parts else "I couldn't generate a response."

    return {
        "reply": reply,
        "model": "claude-sonnet-4-6",
        "tokens": response.usage.input_tokens + response.usage.output_tokens,
        "actions": actions_taken if actions_taken else None,
    }


# ---------------------------------------------------------------------------
# Tool execution — maps tool calls to backend services
# ---------------------------------------------------------------------------

def _execute_tool(db: Session, tool_name: str, tool_input: dict) -> dict:
    """
    Execute a chat tool call against existing backend services.

    All actions are audited with actor="chat_agent" (C4).
    Returns a dict with status and a human-readable message.
    """
    try:
        if tool_name == "create_rfq":
            return _tool_create_rfq(db, tool_input)
        elif tool_name == "change_rfq_status":
            return _tool_change_status(db, tool_input)
        elif tool_name == "send_to_carriers":
            return _tool_send_to_carriers(db, tool_input)
        elif tool_name == "request_clarification":
            return _tool_request_clarification(db, tool_input)
        elif tool_name == "regenerate_quote_sheet":
            return _tool_regenerate_quote_sheet(db, tool_input)
        elif tool_name == "lookup_rfq":
            return _tool_lookup_rfq(db, tool_input)
        else:
            return {"status": "error", "message": f"Unknown tool: {tool_name}"}
    except Exception as e:
        logger.exception("Chat tool '%s' failed: %s", tool_name, e)
        return {"status": "error", "message": f"Action failed: {str(e)}"}


def _tool_create_rfq(db: Session, params: dict) -> dict:
    """
    Create a new RFQ from chat input.

    Parses dates, creates the RFQ record, enqueues quote sheet generation
    if all required fields are present, and logs an audit event.
    """
    from backend.agents.extraction import _parse_date
    from backend.worker import enqueue_job

    pickup_date = _parse_date(params.get("pickup_date"))
    delivery_date = _parse_date(params.get("delivery_date"))

    # Auto-swap dates if needed (#155)
    if pickup_date and delivery_date and delivery_date < pickup_date:
        pickup_date, delivery_date = delivery_date, pickup_date

    from backend.services.ref_number import generate_ref_number
    ref_number = generate_ref_number(db)

    rfq = RFQ(
        ref_number=ref_number,
        customer_name=params.get("customer_name"),
        customer_email=params.get("customer_email"),
        origin=params["origin"],
        destination=params["destination"],
        equipment_type=params["equipment_type"],
        truck_count=params.get("truck_count", 1),
        commodity=params.get("commodity"),
        weight_lbs=params.get("weight_lbs"),
        pickup_date=pickup_date,
        delivery_date=delivery_date,
        special_requirements=params.get("special_requirements"),
        confidence_scores={
            "origin": 1.0, "destination": 1.0,
            "equipment_type": 1.0, "truck_count": 1.0,
            "commodity": 1.0 if params.get("commodity") else 0.0,
        },
        state=RFQState.READY_TO_QUOTE,
    )
    db.add(rfq)
    db.flush()

    # Audit event (C4)
    db.add(AuditEvent(
        rfq_id=rfq.id,
        event_type="rfq_created",
        actor="chat_agent",
        description=f"RFQ created via chat — {rfq.origin} to {rfq.destination}, {rfq.truck_count} {rfq.equipment_type}(s)",
    ))
    db.commit()

    # Enqueue quote sheet generation
    enqueue_job(db, "quote_sheet", {"rfq_id": rfq.id}, rfq_id=rfq.id)

    return {
        "status": "ok",
        "message": f"Created RFQ #{rfq.id}: {rfq.truck_count} {rfq.equipment_type}(s), {rfq.origin} to {rfq.destination}. Quote sheet is being generated.",
        "rfq_id": rfq.id,
    }


def _tool_change_status(db: Session, params: dict) -> dict:
    """Change an RFQ's status using the state machine."""
    from backend.services.rfq_state_machine import transition_rfq

    rfq_id = params["rfq_id"]
    new_status = params["new_status"]
    reason = params.get("reason", "Changed via chat")

    rfq = db.query(RFQ).filter(RFQ.id == rfq_id).first()
    if not rfq:
        return {"status": "error", "message": f"RFQ #{rfq_id} not found."}

    try:
        transition_rfq(db, rfq_id, RFQState(new_status), actor="chat_agent", reason=reason)

        # Handle terminal states
        if new_status in ("won", "lost", "cancelled"):
            rfq.outcome = new_status
            rfq.closed_at = datetime.now(timezone.utc)
            db.commit()

        return {
            "status": "ok",
            "message": f"RFQ #{rfq_id} status changed to '{new_status.replace('_', ' ')}'.",
        }
    except Exception as e:
        return {"status": "error", "message": f"Couldn't change status: {str(e)}"}


def _tool_send_to_carriers(db: Session, params: dict) -> dict:
    """Send an RFQ to all matching active carriers."""
    from backend.services.carrier_distribution import distribute_to_carriers, get_matching_carriers

    rfq_id = params["rfq_id"]
    rfq = db.query(RFQ).filter(RFQ.id == rfq_id).first()
    if not rfq:
        return {"status": "error", "message": f"RFQ #{rfq_id} not found."}

    # Get matching carriers
    carriers = get_matching_carriers(db, rfq)
    if not carriers:
        return {"status": "error", "message": f"No matching carriers found for RFQ #{rfq_id}."}

    carrier_ids = [c.id for c in carriers]
    result = distribute_to_carriers(db, rfq_id, carrier_ids)

    carrier_names = ", ".join(c.name for c in carriers)
    auto_sent = result.get("auto_sent", False)

    if auto_sent:
        return {
            "status": "ok",
            "message": f"RFQ #{rfq_id} auto-sent to {len(carriers)} carrier(s): {carrier_names}.",
        }
    else:
        return {
            "status": "ok",
            "message": f"RFQ #{rfq_id} prepared for {len(carriers)} carrier(s): {carrier_names}. Waiting for your approval in the queue.",
        }


def _tool_request_clarification(db: Session, params: dict) -> dict:
    """Trigger a clarification follow-up for an RFQ."""
    from backend.worker import enqueue_job

    rfq_id = params["rfq_id"]
    rfq = db.query(RFQ).filter(RFQ.id == rfq_id).first()
    if not rfq:
        return {"status": "error", "message": f"RFQ #{rfq_id} not found."}

    if rfq.state in (RFQState.WON, RFQState.LOST, RFQState.CANCELLED):
        return {"status": "error", "message": f"RFQ #{rfq_id} is closed ({rfq.state.value})."}

    # Set to needs_clarification so the validation agent will draft
    if rfq.state != RFQState.NEEDS_CLARIFICATION:
        rfq.state = RFQState.NEEDS_CLARIFICATION
        db.commit()

    enqueue_job(db, "validation", {"rfq_id": rfq_id}, rfq_id=rfq_id)

    db.add(AuditEvent(
        rfq_id=rfq_id,
        event_type="clarification_requested",
        actor="chat_agent",
        description="Clarification follow-up requested via chat",
    ))
    db.commit()

    return {
        "status": "ok",
        "message": f"Clarification follow-up enqueued for RFQ #{rfq_id}. A draft email will be prepared.",
    }


def _tool_regenerate_quote_sheet(db: Session, params: dict) -> dict:
    """Regenerate the quote sheet for an RFQ."""
    from backend.agents.quote_sheet import generate_quote_sheet

    rfq_id = params["rfq_id"]
    rfq = db.query(RFQ).filter(RFQ.id == rfq_id).first()
    if not rfq:
        return {"status": "error", "message": f"RFQ #{rfq_id} not found."}

    # Temporarily set to ready_to_quote if needed
    original_state = rfq.state
    if rfq.state != RFQState.READY_TO_QUOTE:
        rfq.state = RFQState.READY_TO_QUOTE
        db.commit()

    try:
        sheet = generate_quote_sheet(db, rfq_id)
    finally:
        if rfq.state != original_state:
            rfq.state = original_state
            db.commit()

    if not sheet:
        return {"status": "error", "message": f"Quote sheet generation failed for RFQ #{rfq_id}."}

    db.add(AuditEvent(
        rfq_id=rfq_id,
        event_type="quote_sheet_regenerated",
        actor="chat_agent",
        description="Quote sheet regenerated via chat",
    ))
    db.commit()

    summary = sheet.get("summary", "")
    return {
        "status": "ok",
        "message": f"Quote sheet regenerated for RFQ #{rfq_id}: {summary}",
    }


def _tool_lookup_rfq(db: Session, params: dict) -> dict:
    """Look up detailed info about a specific RFQ."""
    rfq_id = params["rfq_id"]
    rfq = db.query(RFQ).filter(RFQ.id == rfq_id).first()
    if not rfq:
        return {"status": "error", "message": f"RFQ #{rfq_id} not found."}

    # Gather related data
    messages = db.query(Message).filter(Message.rfq_id == rfq_id).count()
    bids = db.query(CarrierBid).filter(CarrierBid.rfq_id == rfq_id).all()
    approvals = db.query(Approval).filter(
        Approval.rfq_id == rfq_id,
        Approval.status == ApprovalStatus.PENDING_APPROVAL,
    ).count()

    lines = [
        f"**RFQ #{rfq.id}** — {rfq.state.value.replace('_', ' ').title()}",
        f"Customer: {rfq.customer_name or 'Unknown'} ({rfq.customer_email or 'no email'})",
        f"Route: {rfq.origin or '?'} → {rfq.destination or '?'}",
        f"Equipment: {rfq.truck_count or 1} {rfq.equipment_type or 'TBD'}(s)",
    ]
    if rfq.commodity:
        lines.append(f"Commodity: {rfq.commodity}")
    if rfq.weight_lbs:
        lines.append(f"Weight: {rfq.weight_lbs:,} lbs")
    if rfq.pickup_date:
        lines.append(f"Pickup: {rfq.pickup_date.strftime('%m/%d/%Y')}")
    if rfq.quoted_amount:
        lines.append(f"Quoted: ${rfq.quoted_amount:,.2f}")
    lines.append(f"Messages: {messages} | Pending approvals: {approvals}")
    if bids:
        bid_lines = [f"  {b.carrier_name}: ${b.rate:,.2f}" for b in bids]
        lines.append(f"Carrier bids ({len(bids)}):")
        lines.extend(bid_lines)

    return {
        "status": "ok",
        "message": "\n".join(lines),
    }


# ---------------------------------------------------------------------------
# Context builder — live data snapshot for the LLM
# ---------------------------------------------------------------------------

def _get_company_name(db: Session) -> str:
    """Get company name from org profile for the chat system prompt (#174)."""
    try:
        from backend.services.org_profile import get_company_name
        return get_company_name(db)
    except Exception:
        return "Your Brokerage"


def _build_context(db: Session) -> str:
    """
    Build a text snapshot of current system state for the chat context.

    Includes: active RFQs, pending approvals, recent activity, carrier bids.
    Kept under ~2000 tokens to leave room for the conversation.
    """
    lines = []

    # Active RFQs
    rfqs = (
        db.query(RFQ)
        .filter(RFQ.state.notin_([RFQState.WON, RFQState.LOST, RFQState.CANCELLED]))
        .order_by(RFQ.updated_at.desc())
        .limit(10)
        .all()
    )
    lines.append(f"ACTIVE RFQs ({len(rfqs)}):")
    for r in rfqs:
        lines.append(
            f"  #{r.id} {r.customer_name} ({r.customer_company}) — "
            f"{r.origin} to {r.destination}, {r.equipment_type}, "
            f"state: {r.state.value}, updated: {r.updated_at}"
        )

    # Pending approvals
    approvals = (
        db.query(Approval)
        .filter(Approval.status == ApprovalStatus.PENDING_APPROVAL)
        .limit(5)
        .all()
    )
    lines.append(f"\nPENDING APPROVALS ({len(approvals)}):")
    for a in approvals:
        lines.append(f"  #{a.id} type={a.approval_type.value} for RFQ #{a.rfq_id}: {a.reason}")

    # Recent carrier bids
    bids = db.query(CarrierBid).order_by(CarrierBid.received_at.desc()).limit(5).all()
    lines.append(f"\nRECENT CARRIER BIDS ({len(bids)}):")
    for b in bids:
        lines.append(f"  {b.carrier_name}: ${b.rate} for RFQ #{b.rfq_id}")

    # Recent activity
    events = db.query(AuditEvent).order_by(AuditEvent.created_at.desc()).limit(10).all()
    lines.append(f"\nRECENT ACTIVITY:")
    for e in events:
        lines.append(f"  [{e.created_at}] {e.description}")

    # Closed RFQs summary
    closed = db.query(RFQ).filter(RFQ.state.in_([RFQState.WON, RFQState.LOST, RFQState.CANCELLED])).count()
    lines.append(f"\nCLOSED RFQs: {closed}")

    return "\n".join(lines)
