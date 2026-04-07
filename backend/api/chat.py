"""
backend/api/chat.py — Ask Golteris chat endpoint (#99).

Lets the broker ask questions about RFQs, carriers, and system status.
Claude answers using live data from the database as context.

Endpoint:
    POST /api/chat — Send a message, get a response from Claude

The chat is NOT an autonomous agent — it's a read-only assistant that
answers questions. It cannot take actions (no C2 bypass risk).
"""

import logging
import os
from datetime import datetime

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


@router.post("/api/chat")
def chat(body: ChatRequest, db: Session = Depends(get_db)):
    """
    Answer a broker's question using live RFQ data.

    Builds a context snapshot from the database and sends it to Claude
    along with the broker's question. Returns the response as text.
    """
    import anthropic

    # Build context from live data
    context = _build_context(db)

    client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))

    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=1024,
        system=(
            "You are Golteris, an AI freight logistics assistant for Beltmann Logistics. "
            "Jillian is the broker using you. Answer her questions about RFQs, carriers, "
            "shipments, and system status using the live data provided below. "
            "Be concise, helpful, and use plain business language. "
            "If you don't have enough data to answer, say so.\n\n"
            f"CURRENT DATA:\n{context}"
        ),
        messages=[{"role": "user", "content": body.message}],
    )

    reply = response.content[0].text if response.content else "I couldn't generate a response."

    return {
        "reply": reply,
        "model": "claude-sonnet-4-6",
        "tokens": response.usage.input_tokens + response.usage.output_tokens,
    }


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
