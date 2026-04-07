"""
backend/api/agent_controls.py — Agent permissions and cost cap controls (#44).

Returns and updates per-agent configuration: which agents are enabled,
which LLM model each uses, and cost cap settings.

Endpoints:
    GET  /api/settings/agents — List agent configs
    PUT  /api/settings/agents — Update agent configs

The agent configs are stored in-memory for the MVP (not persisted to DB).
A future issue will add a settings table for persistence.
"""

import logging
import os

from fastapi import APIRouter
from pydantic import BaseModel

logger = logging.getLogger("golteris.api.agent_controls")

router = APIRouter(tags=["settings"])

# In-memory agent configuration — MVP approach.
# Production would store this in a settings table.
AGENT_CONFIGS = {
    "extraction": {
        "name": "RFQ Extraction",
        "description": "Extracts structured fields from shipper emails",
        "enabled": True,
        "model": "claude-sonnet-4-6",
    },
    "validation": {
        "name": "Missing Info Detection",
        "description": "Identifies missing fields and drafts follow-up questions",
        "enabled": True,
        "model": "claude-sonnet-4-6",
    },
    "carrier_bid_parser": {
        "name": "Carrier Bid Parser",
        "description": "Parses carrier reply emails into structured bids",
        "enabled": True,
        "model": "claude-sonnet-4-6",
    },
    "quote_sheet": {
        "name": "Quote Sheet Generator",
        "description": "Generates structured quote sheets from RFQ data",
        "enabled": True,
        "model": "claude-sonnet-4-6",
    },
}

MODEL_OPTIONS = [
    {"id": "claude-sonnet-4-6", "name": "Claude Sonnet 4.6", "provider": "anthropic"},
    {"id": "claude-haiku-4-5-20251001", "name": "Claude Haiku 4.5", "provider": "anthropic"},
    {"id": "gpt-4o", "name": "GPT-4o", "provider": "openai"},
    {"id": "gpt-4.1", "name": "GPT-4.1", "provider": "openai"},
]


@router.get("/api/settings/agents")
def get_agent_controls():
    """
    Return per-agent configurations and available models.

    Each agent has: enabled toggle, model selector, description.
    Cost caps come from environment variables.
    """
    daily_cap = float(os.environ.get("LLM_DAILY_COST_CAP", "20.00"))
    monthly_cap = float(os.environ.get("LLM_MONTHLY_COST_CAP", "100.00"))

    return {
        "agents": AGENT_CONFIGS,
        "models": MODEL_OPTIONS,
        "cost_caps": {
            "daily": daily_cap,
            "monthly": monthly_cap,
        },
    }


class AgentUpdateRequest(BaseModel):
    """Update a single agent's configuration."""
    agent_id: str
    enabled: bool | None = None
    model: str | None = None


@router.put("/api/settings/agents")
def update_agent_control(body: AgentUpdateRequest):
    """
    Update an agent's enabled status or model selection.

    Changes take effect immediately — the next LLM call by that agent
    will use the new model.
    """
    if body.agent_id not in AGENT_CONFIGS:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail=f"Agent '{body.agent_id}' not found")

    config = AGENT_CONFIGS[body.agent_id]
    if body.enabled is not None:
        config["enabled"] = body.enabled
    if body.model is not None:
        config["model"] = body.model

    return {"agent_id": body.agent_id, **config}
