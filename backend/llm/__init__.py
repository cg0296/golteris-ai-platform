"""
backend/llm/ — LLM provider abstraction layer.

This package provides a single interface for calling any supported LLM provider
(Anthropic Claude, OpenAI GPT, etc.) without the agent code knowing or caring
which provider is being used.

Architecture (see REQUIREMENTS.md §2.5):
    Agents call `call_llm()` from `backend.llm.client`. That function:
    1. Selects the provider based on config (default or per-agent override)
    2. Checks daily/monthly cost caps before making the call (C5)
    3. Delegates to the provider-specific implementation
    4. Logs the call to the `agent_calls` table (C4 — full traceability)
    5. Returns a unified response object

Supported providers:
    - Anthropic (Claude Sonnet 4.6, etc.) via `anthropic_provider.py`
    - OpenAI (GPT-4o, GPT-4.1, etc.) via `openai_provider.py`

Adding a new provider:
    1. Create `backend/llm/new_provider.py` implementing `LLMProvider`
    2. Add its pricing to `pricing.py`
    3. Register it in `client.py` PROVIDERS dict
    No agent code changes needed.

Key modules:
    provider.py            — Abstract base class `LLMProvider`
    anthropic_provider.py  — Anthropic implementation
    openai_provider.py     — OpenAI implementation
    client.py              — Main `call_llm()` function (the only thing agents import)
    pricing.py             — Per-model cost-per-token lookup
    cost_tracker.py        — Queries agent_calls for daily/monthly spend
"""

from backend.llm.client import call_llm  # noqa: F401 — public API

__all__ = ["call_llm"]
