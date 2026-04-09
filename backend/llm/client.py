"""
backend/llm/client.py — Main LLM call function. This is the only thing agents import.

`call_llm()` is the single entry point for every LLM interaction in the system.
It handles provider selection, cost cap enforcement (C5), API call delegation,
error handling, and logging every call to the `agent_calls` table (C4).

Usage by agents:
    from backend.llm import call_llm

    response = call_llm(
        db=db,
        run_id=current_run.id,
        agent_name="extraction",
        system_prompt="Extract freight RFQ fields from this email...",
        user_prompt=email_body,
        tools=[extract_rfq_tool],
    )
    # response.tool_calls[0]["input"] has the extracted fields

See REQUIREMENTS.md §2.5 for the architectural rationale.
See NFR-OB-1 for the cost accuracy requirement (within 1% of actual bill).
"""

import logging
import os
import time
from datetime import datetime
from decimal import Decimal

from sqlalchemy.orm import Session

from backend.db.models import AgentCall, AgentCallStatus
from backend.llm.anthropic_provider import AnthropicProvider
from backend.llm.cost_tracker import check_cost_cap
from backend.llm.openai_provider import OpenAIProvider
from backend.llm.pricing import calculate_cost
from backend.llm.provider import (
    LLMCostCapExceeded,
    LLMProvider,
    LLMProviderError,
    LLMRateLimitError,
    LLMResponse,
    LLMTimeoutError,
    ToolDefinition,
)

logger = logging.getLogger("golteris.llm")

# ---------------------------------------------------------------------------
# Provider registry — maps provider name to its class.
# Adding a new provider: implement LLMProvider, add it here.
# ---------------------------------------------------------------------------

PROVIDER_CLASSES: dict[str, type[LLMProvider]] = {
    "anthropic": AnthropicProvider,
    "openai": OpenAIProvider,
}

# Provider instances are cached after first use (one instance per provider).
# This avoids creating a new SDK client on every call.
_provider_instances: dict[str, LLMProvider] = {}


def _get_provider(provider_name: str) -> LLMProvider:
    """
    Get or create a provider instance by name.

    Caches instances so the SDK client is only initialized once per provider.
    Raises LLMProviderError if the provider name is unknown or if the
    provider's API key is not set.
    """
    if provider_name not in _provider_instances:
        if provider_name not in PROVIDER_CLASSES:
            raise LLMProviderError(
                f"Unknown LLM provider '{provider_name}'. "
                f"Available: {', '.join(sorted(PROVIDER_CLASSES.keys()))}"
            )
        # This will raise if the API key is missing — the provider __init__ checks
        _provider_instances[provider_name] = PROVIDER_CLASSES[provider_name]()
    return _provider_instances[provider_name]


def _get_default_provider() -> str:
    """Read the default provider from environment. Falls back to 'anthropic'."""
    return os.environ.get("LLM_DEFAULT_PROVIDER", "anthropic")


def _get_default_model() -> str:
    """Read the default model from environment. Falls back to 'claude-sonnet-4-6'."""
    return os.environ.get("LLM_DEFAULT_MODEL", "claude-sonnet-4-6")


def call_llm(
    db: Session,
    run_id: int,
    agent_name: str,
    user_prompt: str,
    system_prompt: str | None = None,
    tools: list[ToolDefinition] | None = None,
    provider: str | None = None,
    model: str | None = None,
    max_tokens: int = 4096,
    temperature: float = 0.0,
) -> LLMResponse:
    """
    Make an LLM API call with full logging and cost cap enforcement.

    This is the ONLY function agents should use to call an LLM. It:
    1. Checks cost caps (C5) — raises LLMCostCapExceeded if exceeded
    2. Calls the selected provider
    3. Calculates cost from token usage
    4. Logs the call to `agent_calls` table (C4 — full traceability)
    5. Returns a unified LLMResponse

    Args:
        db: SQLAlchemy session (for cost cap check and logging)
        run_id: The parent agent_run ID (links this call to its workflow run)
        agent_name: Which agent is making this call (e.g., "extraction", "validation")
        user_prompt: The user message / input to process
        system_prompt: System-level instructions (optional)
        tools: Optional list of tools for structured extraction
        provider: Provider name override (default: LLM_DEFAULT_PROVIDER env var)
        model: Model override (default: LLM_DEFAULT_MODEL env var)
        max_tokens: Maximum output tokens (default 4096)
        temperature: Sampling temperature (default 0.0 for deterministic)

    Returns:
        LLMResponse with content, tool_calls, token counts, and raw response

    Raises:
        LLMCostCapExceeded: Daily or monthly cap exceeded (C5)
        LLMTimeoutError: API call timed out
        LLMRateLimitError: Provider rate limit hit
        LLMProviderError: Any other provider-side error
    """
    # Resolve provider and model — use defaults if not overridden
    provider_name = provider or _get_default_provider()
    model_name = model or _get_default_model()

    # C5: Check cost caps before making the call.
    # This queries agent_calls for today's and this month's total spend.
    check_cost_cap(db)

    # Inject approved broker context into the system prompt (#171).
    # This is what makes the broker's preferences, rules, and knowledge
    # actually influence agent behavior. Only approved entries are included.
    context_memory_ids: list[int] = []
    try:
        from backend.services.context import build_context_for_prompt
        context_block, context_memory_ids = build_context_for_prompt(db)
        if context_block and system_prompt:
            system_prompt = system_prompt + context_block
        elif context_block:
            system_prompt = context_block
    except Exception as e:
        # Don't fail the LLM call if context injection fails — just log it
        logger.warning("Context injection failed: %s", e)

    # Get the provider instance (cached after first use)
    llm_provider = _get_provider(provider_name)

    # Record the start time for duration tracking
    started_at = datetime.utcnow()
    start_time = time.monotonic()

    # Pre-create the agent_calls row with status=running so it's visible
    # in the Agent → Decisions view even while the call is in progress.
    # We'll update it with the result when the call completes.
    call_record = AgentCall(
        run_id=run_id,
        agent_name=agent_name,
        provider=provider_name,
        model=model_name,
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        input_tokens=0,
        output_tokens=0,
        cost_usd=Decimal("0"),
        started_at=started_at,
        status=AgentCallStatus.SUCCESS,  # optimistic — updated on failure
    )
    db.add(call_record)
    db.flush()  # get the ID without committing

    try:
        # Make the actual LLM call via the provider
        response = llm_provider.call(
            model=model_name,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            tools=tools,
            max_tokens=max_tokens,
            temperature=temperature,
        )

        # Calculate duration
        duration_ms = int((time.monotonic() - start_time) * 1000)
        finished_at = datetime.utcnow()

        # Calculate cost (NFR-OB-1 — must match actual bill within 1%)
        cost_usd = calculate_cost(model_name, response.input_tokens, response.output_tokens)

        # Update the call record with results
        call_record.input_tokens = response.input_tokens
        call_record.output_tokens = response.output_tokens
        call_record.cost_usd = Decimal(str(round(cost_usd, 6)))
        call_record.finished_at = finished_at
        call_record.duration_ms = duration_ms
        call_record.status = AgentCallStatus.SUCCESS
        # Store the response as text for the "View system reasoning" disclosure.
        # For tool-use, this is the JSON representation of the tool calls.
        call_record.response = str(response.raw_response)

        db.commit()

        # Record which context entries were used (#171)
        if context_memory_ids:
            try:
                from backend.services.context import record_context_usage
                record_context_usage(db, context_memory_ids, run_id=run_id)
            except Exception:
                logger.warning("Failed to record context usage", exc_info=True)

        logger.info(
            "LLM call: agent=%s provider=%s model=%s tokens=%d/%d cost=$%.4f duration=%dms context=%d",
            agent_name, provider_name, model_name,
            response.input_tokens, response.output_tokens,
            cost_usd, duration_ms, len(context_memory_ids),
        )

        return response

    except LLMTimeoutError as e:
        # Log the timeout in the call record
        _record_failure(db, call_record, start_time, AgentCallStatus.TIMEOUT, str(e))
        raise

    except LLMRateLimitError as e:
        # Log the rate limit in the call record
        _record_failure(db, call_record, start_time, AgentCallStatus.RATE_LIMITED, str(e))
        raise

    except (LLMProviderError, Exception) as e:
        # Log any other failure in the call record
        _record_failure(db, call_record, start_time, AgentCallStatus.FAILED, str(e))
        if isinstance(e, LLMProviderError):
            raise
        raise LLMProviderError(f"Unexpected error in LLM call: {e}") from e


def _record_failure(
    db: Session,
    call_record: AgentCall,
    start_time: float,
    status: AgentCallStatus,
    error_message: str,
) -> None:
    """
    Update an agent_calls record with failure details and commit.

    Called when the LLM call fails for any reason (timeout, rate limit, error).
    Ensures the failure is recorded in the database for the Agent → Decisions view
    and for error monitoring.
    """
    duration_ms = int((time.monotonic() - start_time) * 1000)
    call_record.finished_at = datetime.utcnow()
    call_record.duration_ms = duration_ms
    call_record.status = status
    call_record.error_message = error_message

    try:
        db.commit()
    except Exception:
        # If the commit fails (e.g., DB connection lost), log and swallow —
        # we don't want a logging failure to mask the original LLM error.
        logger.exception("Failed to record LLM call failure to database")
        db.rollback()

    logger.error(
        "LLM call failed: agent=%s status=%s duration=%dms error=%s",
        call_record.agent_name, status.value, duration_ms, error_message,
    )
