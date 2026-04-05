# backend/db/__init__.py
# Database package — contains SQLAlchemy models, Alembic migrations, and
# connection setup for the Golteris PostgreSQL database.
#
# Schema overview (see backend/db/models.py for full definitions):
#   workflows     — workflow definitions with on/off toggle (C1 kill switch)
#   rfqs          — core RFQ records with extracted fields and state
#   messages      — inbound/outbound email records linked to RFQs
#   agent_runs    — per-workflow-invocation tracking (duration, cost rollup)
#   agent_calls   — per-Claude-API-call logging (prompt, tokens, cost, duration)
#   approvals     — HITL review queue (C2 — nothing sends without approval)
#   audit_events  — every state change and action for the RFQ detail timeline
#   carrier_bids  — carrier quote responses for bid comparison
#   review_queue  — ambiguous message matching needing human review
