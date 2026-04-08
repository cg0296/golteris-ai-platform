"""
backend/api/memories.py — Agent memory CRUD API (#49).

Endpoints:
    GET    /api/agent/memories          — List all memories (with optional category filter)
    POST   /api/agent/memories          — Manually add a memory
    PATCH  /api/agent/memories/:id      — Update status (approve/reject) or content
    DELETE /api/agent/memories/:id      — Delete a memory

The broker uses these from the Agent → Memory view to review, approve,
reject, and manage what the agents have learned.
"""

import logging
from datetime import datetime
from decimal import Decimal
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import func
from sqlalchemy.orm import Session

from backend.db.database import get_db
from backend.db.models import AgentMemory

logger = logging.getLogger("golteris.api.memories")

router = APIRouter(prefix="/api/agent/memories", tags=["agent-memory"])


class CreateMemoryRequest(BaseModel):
    category: str
    content: str
    source: Optional[str] = "Manual entry by broker"


class UpdateMemoryRequest(BaseModel):
    status: Optional[str] = None  # "approved", "rejected", "pending"
    content: Optional[str] = None


@router.get("")
def list_memories(
    category: Optional[str] = None,
    status: Optional[str] = None,
    db: Session = Depends(get_db),
):
    """
    List agent memories with optional filters.

    Used by the Memory view to display what agents have learned,
    grouped by category, with counts per category.
    """
    query = db.query(AgentMemory).order_by(AgentMemory.created_at.desc())

    if category:
        query = query.filter(AgentMemory.category == category)
    if status:
        query = query.filter(AgentMemory.status == status)

    memories = query.all()

    # Category counts for the summary cards
    counts = {}
    all_mems = db.query(AgentMemory.category, func.count(AgentMemory.id)).group_by(AgentMemory.category).all()
    for cat, count in all_mems:
        counts[cat] = count

    return {
        "memories": [_serialize_memory(m) for m in memories],
        "total": len(memories),
        "counts": counts,
    }


@router.post("")
def create_memory(body: CreateMemoryRequest, db: Session = Depends(get_db)):
    """
    Manually add a memory entry.

    The broker can teach the agent directly by adding facts, preferences,
    or rules. Manually added memories are auto-approved.
    """
    mem = AgentMemory(
        category=body.category,
        content=body.content,
        source=body.source,
        status="approved",  # Manual entries are pre-approved
        confidence=Decimal("1.00"),  # Broker-entered = max confidence
    )
    db.add(mem)
    db.commit()
    db.refresh(mem)
    return _serialize_memory(mem)


@router.patch("/{memory_id}")
def update_memory(memory_id: int, body: UpdateMemoryRequest, db: Session = Depends(get_db)):
    """
    Update a memory's status (approve/reject) or content.

    The broker reviews pending memories and either approves them
    (agent keeps using this pattern) or rejects them (pattern discarded).
    """
    mem = db.query(AgentMemory).filter(AgentMemory.id == memory_id).first()
    if not mem:
        raise HTTPException(status_code=404, detail="Memory not found")

    if body.status is not None:
        mem.status = body.status
    if body.content is not None:
        mem.content = body.content

    mem.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(mem)
    return _serialize_memory(mem)


@router.delete("/{memory_id}")
def delete_memory(memory_id: int, db: Session = Depends(get_db)):
    """Delete a memory permanently."""
    mem = db.query(AgentMemory).filter(AgentMemory.id == memory_id).first()
    if not mem:
        raise HTTPException(status_code=404, detail="Memory not found")

    db.delete(mem)
    db.commit()
    return {"status": "ok", "message": "Memory deleted"}


def _serialize_memory(mem: AgentMemory) -> dict:
    return {
        "id": mem.id,
        "category": mem.category,
        "content": mem.content,
        "source": mem.source,
        "status": mem.status,
        "confidence": float(mem.confidence) if mem.confidence else None,
        "times_applied": mem.times_applied,
        "created_at": mem.created_at.isoformat() if mem.created_at else None,
        "updated_at": mem.updated_at.isoformat() if mem.updated_at else None,
    }
