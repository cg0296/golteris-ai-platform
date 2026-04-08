"""
backend/services/memory_learning.py — Agent memory learning from approved drafts (#49).

When a broker edits a draft before approving, the system compares the
original draft_body to the resolved_body (edited version) and extracts
learned patterns. These are stored as AgentMemory entries and applied
to future draft generation.

Learning triggers:
    - After an approval is resolved with edits (draft_body != resolved_body)
    - Manually by the broker adding a memory via the Memory view

Pattern extraction (simple heuristic approach for v1):
    - Greeting changes → style memory
    - Sign-off changes → style memory
    - Tone shifts → preference memory
    - Price adjustments → pricing memory
    - New terms added → preference memory

Called by:
    The worker after processing an "approval_resolved" job
"""

import logging
from datetime import datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy.orm import Session

from backend.db.models import AgentMemory, Approval, ApprovalStatus

logger = logging.getLogger("golteris.services.memory_learning")


def learn_from_approval(db: Session, approval_id: int) -> list[AgentMemory]:
    """
    Extract learned patterns from a resolved approval by comparing the
    original draft to the broker's edited version.

    Only triggers if the broker actually edited the draft (resolved_body
    differs from draft_body). If approved as-is, no learning occurs.

    Args:
        db: SQLAlchemy session
        approval_id: The resolved approval to learn from

    Returns:
        List of newly created AgentMemory entries (may be empty)
    """
    approval = db.query(Approval).filter(Approval.id == approval_id).first()
    if not approval:
        logger.warning("Approval #%d not found — skipping learning", approval_id)
        return []

    # Only learn from approved drafts that were edited
    if approval.status != ApprovalStatus.APPROVED:
        return []

    original = (approval.draft_body or "").strip()
    edited = (approval.resolved_body or "").strip()

    # If not edited (approved as-is), nothing to learn
    if not edited or original == edited:
        return []

    logger.info("Learning from approval #%d — draft was edited before approval", approval_id)

    memories = []

    # --- Compare greeting ---
    original_greeting = _extract_greeting(original)
    edited_greeting = _extract_greeting(edited)
    if original_greeting != edited_greeting and edited_greeting:
        mem = AgentMemory(
            category="style",
            content=f"Use greeting: \"{edited_greeting}\" (changed from \"{original_greeting}\")",
            source=f"Approval #{approval_id} — broker edited greeting",
            approval_id=approval_id,
            confidence=Decimal("0.85"),
        )
        db.add(mem)
        memories.append(mem)

    # --- Compare sign-off ---
    original_signoff = _extract_signoff(original)
    edited_signoff = _extract_signoff(edited)
    if original_signoff != edited_signoff and edited_signoff:
        mem = AgentMemory(
            category="style",
            content=f"Use sign-off: \"{edited_signoff}\" (changed from \"{original_signoff}\")",
            source=f"Approval #{approval_id} — broker edited sign-off",
            approval_id=approval_id,
            confidence=Decimal("0.85"),
        )
        db.add(mem)
        memories.append(mem)

    # --- Detect added content (broker added details not in the original) ---
    original_lines = set(original.lower().splitlines())
    edited_lines = edited.splitlines()
    added_lines = [line for line in edited_lines if line.strip() and line.lower().strip() not in original_lines]

    if added_lines and len(added_lines) <= 5:
        added_content = "\n".join(added_lines[:3])
        mem = AgentMemory(
            category="preference",
            content=f"Broker tends to add: \"{added_content}\"",
            source=f"Approval #{approval_id} — broker added content to draft",
            approval_id=approval_id,
            confidence=Decimal("0.70"),
        )
        db.add(mem)
        memories.append(mem)

    # --- Detect removed content (broker removed things they don't want) ---
    edited_lines_set = set(edited.lower().splitlines())
    removed_lines = [line for line in original.splitlines() if line.strip() and line.lower().strip() not in edited_lines_set]

    if removed_lines and len(removed_lines) <= 5:
        removed_content = "\n".join(removed_lines[:3])
        mem = AgentMemory(
            category="preference",
            content=f"Broker removes: \"{removed_content}\" — don't include in future drafts",
            source=f"Approval #{approval_id} — broker removed content from draft",
            approval_id=approval_id,
            confidence=Decimal("0.70"),
        )
        db.add(mem)
        memories.append(mem)

    if memories:
        db.commit()
        logger.info("Learned %d patterns from approval #%d", len(memories), approval_id)

    return memories


def _extract_greeting(text: str) -> str:
    """Extract the greeting line from an email draft (first line if it looks like a greeting)."""
    lines = text.strip().splitlines()
    if not lines:
        return ""
    first = lines[0].strip()
    greeting_words = ("hi", "hello", "hey", "dear", "good morning", "good afternoon")
    if any(first.lower().startswith(w) for w in greeting_words):
        return first
    return ""


def _extract_signoff(text: str) -> str:
    """Extract the sign-off from an email draft (last few non-empty lines)."""
    lines = [l.strip() for l in text.strip().splitlines() if l.strip()]
    if len(lines) < 2:
        return ""
    signoff_words = ("best", "regards", "thanks", "thank you", "sincerely", "cheers")
    # Check last 3 lines for sign-off pattern
    for line in reversed(lines[-3:]):
        if any(line.lower().startswith(w) for w in signoff_words):
            return line
    return ""
