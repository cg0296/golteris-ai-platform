"""
backend/agents/ — AI agent implementations for the Golteris pipeline.

Each agent is a focused module that performs one step in the RFQ workflow.
Agents call the LLM via `backend.llm.call_llm()` (never directly via SDK)
and track their work via `backend.services.agent_runs`.

Agent pipeline order:
    1. Extraction (#24) — email -> structured RFQ fields
    2. Validation (#15) — checks required fields, drafts clarifications
    3. Matching (#13) — attaches messages to existing RFQs
    4. Quote Sheet (#16) — complete RFQ -> structured carrier format
    5. Carrier Distribution (#32) — sends to carriers
    6. Bid Comparison (#34) — ranks carrier responses

Cross-cutting constraints:
    C2 — No agent sends outbound email without HITL approval
    C4 — Every agent decision logged via agent_calls (automatic through call_llm)
    C5 — Cost caps enforced at call_llm level
"""
