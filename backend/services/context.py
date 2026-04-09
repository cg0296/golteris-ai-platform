"""
backend/services/context.py — Agent context injection service (#171).

Retrieves approved context entries (agent_memories) and formats them
for injection into agent LLM prompts. This is the bridge that makes
the broker's preferences, rules, and knowledge actually influence
agent behavior.

Every LLM call in call_llm() calls build_context_for_prompt() to get
a formatted block of approved context. The block is appended to the
system prompt so the agent sees it before generating a response.

After a call completes, record_context_usage() increments times_applied
on each entry that was injected, so the broker can see which entries
are actually being used.

Called by:
    backend/llm/client.py — call_llm() uses this before every LLM call

Cross-cutting constraints:
    C4 — context entries are traceable (stored in agent_memories table)
"""

import logging
from typing import Optional

from sqlalchemy.orm import Session

from backend.db.models import AgentMemory

logger = logging.getLogger("golteris.services.context")

# Category labels for the context block — helps the LLM understand
# what kind of guidance each entry represents
CATEGORY_LABELS = {
    "style": "Writing Style",
    "preference": "Broker Preference",
    "customer": "Customer Knowledge",
    "lane": "Lane/Route Knowledge",
    "pricing": "Pricing Rule",
}


def get_relevant_context(
    db: Session,
    categories: Optional[list[str]] = None,
) -> list[dict]:
    """
    Retrieve approved context entries, optionally filtered by category.

    Only returns entries with status='approved'. The broker controls
    which entries are active by approving/rejecting them in the Context tab.

    Args:
        db: SQLAlchemy session.
        categories: Optional list of categories to filter by.
                    If None, returns all approved entries.

    Returns:
        List of {id, category, content} dicts ready for prompt injection.
    """
    query = db.query(AgentMemory).filter(AgentMemory.status == "approved")

    if categories:
        query = query.filter(AgentMemory.category.in_(categories))

    entries = query.order_by(AgentMemory.category, AgentMemory.created_at).all()

    return [
        {
            "id": e.id,
            "category": e.category,
            "content": e.content,
        }
        for e in entries
    ]


def build_context_for_prompt(
    db: Session,
    categories: Optional[list[str]] = None,
) -> tuple[str, list[int]]:
    """
    Build a formatted context block for injection into an agent's system prompt.

    Returns a tuple of (context_block, memory_ids):
    - context_block: formatted string to append to the system prompt
    - memory_ids: list of entry IDs that were included (for usage tracking)

    If no approved entries exist, returns ("", []).

    The format groups entries by category with clear labels so the LLM
    understands what kind of guidance each entry represents.
    """
    entries = get_relevant_context(db, categories)

    if not entries:
        return "", []

    memory_ids = [e["id"] for e in entries]

    # Group entries by category
    by_category: dict[str, list[str]] = {}
    for entry in entries:
        cat = entry["category"]
        if cat not in by_category:
            by_category[cat] = []
        by_category[cat].append(entry["content"])

    # Format as a clear context block
    lines = ["\n--- BROKER CONTEXT (follow these guidelines) ---"]
    for cat, contents in by_category.items():
        label = CATEGORY_LABELS.get(cat, cat.title())
        lines.append(f"\n{label}:")
        for content in contents:
            lines.append(f"  - {content}")
    lines.append("--- END BROKER CONTEXT ---\n")

    return "\n".join(lines), memory_ids


def record_context_usage(
    db: Session,
    memory_ids: list[int],
    run_id: Optional[int] = None,
) -> None:
    """
    Increment times_applied for each context entry that was injected.

    Called after an LLM call completes successfully. This lets the broker
    see which entries are actually being used in the Context tab.

    Args:
        db: SQLAlchemy session.
        memory_ids: IDs of entries that were injected into the prompt.
        run_id: Optional agent_run ID for future linking.
    """
    if not memory_ids:
        return

    db.query(AgentMemory).filter(AgentMemory.id.in_(memory_ids)).update(
        {AgentMemory.times_applied: AgentMemory.times_applied + 1},
        synchronize_session="fetch",
    )
    db.commit()

    logger.debug("Context usage recorded: %d entries for run %s", len(memory_ids), run_id)
