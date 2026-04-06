# Golteris — Requirements

This is the single source of truth for **what Golteris must do**, the **rules it must obey**, and the **acceptance criteria** that determine "done."

Everything in this document is traceable to a GitHub issue in [cg0296/golteris-ai-platform](https://github.com/cg0296/golteris-ai-platform/issues). Issue numbers are cited inline as `#NN`.

Source material consolidated here:
- [README.md](README.md) — product thesis and agent model
- [PROJECT-PLAN.md](PROJECT-PLAN.md) — phased build plan with acceptance tests
- [planning/product-ux.md](planning/product-ux.md) — UX specification
- [planning/workflow.md](planning/workflow.md) — end-to-end freight quote workflow
- [planning/Beltmann Logistics Meeting Recap.md](planning/Beltmann%20Logistics%20Meeting%20Recap.md) — customer context
- GitHub issues #11–#63 — per-feature acceptance criteria

---

## 1. Context & Vision

**Golteris** is an operating console for freight brokers. It ingests inbound customer emails, runs a chain of focused AI agents to extract, validate, draft, distribute, and compare — and presents the broker with one coherent queue of decisions to approve.

**Thesis:** Brokers lose hours per day translating unstructured email into spreadsheets, clarifications, carrier RFQs, and final quotes. Golteris automates the translation layer while keeping the broker in control of every outbound action.

**Primary workflow (MVP):** Freight quote handling — customer email → structured RFQ → clarification loop → carrier distribution → bid comparison → marked-up customer quote.

**Key differentiator from a chatbot:** Golteris is operational execution with explicit state, not conversation. It maintains workflow state across messages, triggers actions, coordinates tools, and uses AI only where ambiguity requires interpretation.

---

## 2. Tech Stack

The following stack is locked in. AI dev agents must use these technologies — do not introduce alternatives without explicit human approval.

### 2.1 Backend
- **Python 3.12+** with **FastAPI** — async-native web framework and API server
- **Anthropic Python SDK** + **OpenAI Python SDK** — LLM calls go through a provider abstraction layer (`backend/llm/`), not directly. See §2.5 for the LLM-agnostic architecture.
- **APScheduler** or FastAPI background tasks — for the cron poller and delayed job timers (`#47`)
- **Postgres job queue** pattern — `SELECT ... FOR UPDATE SKIP LOCKED` on a jobs table; no external queue (Redis, RabbitMQ, Celery) unless the human approves

### 2.2 Database
- **PostgreSQL 15+** — single database, single tenant for v1
- **Alembic** — schema migrations, version-controlled in the repo
- **JSONB columns** for flexible agent outputs (extraction results, carrier bids, prompt/response logs)
- Schema documented in `#60`; migrations checked into `db/migrations/`

### 2.3 Frontend
- **React 18+** via **Vite** — single-page application, no SSR, no Next.js
- **TypeScript** — all frontend code is TypeScript, not plain JS
- **Tailwind CSS** + **shadcn/ui** — component library for tables, cards, badges, toasts, dialogs, modals, drawers
- **React Query (TanStack Query)** — handles 10-second API polling per endpoint in a declarative way
- **Single deploy** — `vite build` outputs static files; FastAPI serves them from a `/static` folder on the same Render service
- Keyboard shortcuts (`#26`) implemented via a lightweight hook (e.g., `useHotkeys`) — not a custom key listener

### 2.4 Infrastructure & deploy
- **Render** — single service hosting FastAPI (which serves both the API and the static React build) + managed Postgres
- **Auto-deploy from `main`** — every merged PR deploys to the staging environment
- **Custom subdomain** pointed at the Render service
- **Environment variables** managed via Render dashboard; documented in `.env.example` in the repo
- **Secrets** (LLM provider API keys, Gmail credentials) stored in Render's secret manager, never in source

### 2.5 AI / LLM
- **LLM-agnostic architecture** — the system must support swapping between LLM providers (Anthropic Claude, OpenAI GPT, Google Gemini, open-source models) without changing agent logic. All LLM calls go through a provider abstraction layer.
- **Default provider:** Anthropic Claude (Sonnet 4.6) — but this is a configuration choice, not a hard dependency
- **Supported providers (v1):** Anthropic (Claude), OpenAI (GPT-4o, GPT-4.1) — additional providers can be added by implementing the provider interface
- **Tool-use / function calling** for structured extraction — agents define JSON schemas, the provider returns structured data. Both Anthropic and OpenAI support this natively.
- **Provider abstraction layer** — a wrapper module (`backend/llm/`) that:
  - Exposes a single `call_llm(agent_name, system_prompt, user_prompt, tools, model)` function
  - Routes to the configured provider (Anthropic SDK, OpenAI SDK, etc.)
  - Logs every call to `agent_calls` table with prompt, model, provider, tokens, cost, duration
  - Enforces cost caps before making the call
  - Handles provider-specific error codes (rate limits, timeouts) uniformly
- Model is configurable **per-agent** and **per-provider** via Settings (`#44`)
- Every call wrapped with: prompt logging, token counting, cost calculation, duration timing → `agent_calls` table (`#21`)

### 2.6 Email (v1 / demo)
- **Seeded folder** of sample `.eml` or JSON files for the demo — no live Gmail integration required for April 8
- **Gmail API** (OAuth) as the post-demo replacement (`#48`)
- Outbound email via **Gmail API** or **SMTP** — gated by approval (`#25`)

### 2.7 Dev tooling
- **pytest** for backend tests
- **Vitest** or **React Testing Library** for frontend tests
- **Ruff** for Python linting/formatting
- **ESLint + Prettier** for TypeScript linting/formatting
- **GitHub Actions** for CI (lint, test, type-check on every PR)

---

## 3. AI-Driven Development — Operating Rules

**Golteris is being built primarily by AI coding agents, supervised by a human operator (Curt).** This is not incidental — it is a first-class constraint on how this document and the work it governs are structured.

**IMPORTANT — Workflow documents:** Two companion documents define the full lifecycle. Read the one that matches your role:
- **[DEVELOPMENT-WORKFLOW.md](DEVELOPMENT-WORKFLOW.md)** — For dev agents. How to find work (only `Agent Work` status), post your plan as a comment before coding, post completion comments with testing instructions, and move the issue to `Testing` when done.
- **[TESTING-WORKFLOW.md](TESTING-WORKFLOW.md)** — For testing agents. How to find work (only `Testing` status), verify acceptance criteria and cross-cutting constraints, check code quality and comments, report results, and move the issue to `Done` (pass) or `Human Work` (fail).

### 3.1 This document is the AI's context packet
- An AI dev agent starts each session with zero memory of prior work. **REQUIREMENTS.md, PROJECT-PLAN.md, and the relevant GitHub issue are the full briefing.** If a constraint is not captured in one of those three places, it will be forgotten.
- Every cross-cutting constraint in §4 is **repeated inline** in the affected FR/NFR sections. Do not rely on "the AI will remember" — state rules where the work happens.
- When scope or a requirement changes, the human operator (or a supervised dev agent) **must update this file in the same commit** that changes behavior. Requirements drift is the single biggest failure mode for AI-led development.

### 3.2 Work-unit sizing for AI agents
- Each GitHub issue should be **completable in one AI session** with REQUIREMENTS.md + the issue body + the existing repo as the only inputs. If an issue needs hidden tribal knowledge, the issue or this doc is incomplete — fix the doc, not the agent.
- Issues that require coordinated changes across many files should cite the files explicitly in their Scope section (e.g., `backend/agents/extraction.py`, `db/migrations/0003_confidence.sql`). AI agents should not have to guess.
- Prefer **many small issues with crisp contracts** over few large issues with implicit coupling.

### 3.3 Verification must be machine-checkable
- Every acceptance criterion should be verifiable by a command, a test, or a visible artifact — not by "it feels right." Examples of good/bad:
  - Bad: "The approval flow is fast."
  - Good: "`POST /api/approvals/:id/approve` returns 200 in under 200ms on the staging environment."
  - Bad: "Extraction works on messy emails."
  - Good: "`pytest tests/agents/test_extraction.py` passes against all 10 seed emails in `seed/beltmann/`."
- Every FR in §5 and NFR in §6 should, where possible, point at a test file, a curl command, or a UI path an operator can walk.
- **"Done" is defined as: passing acceptance tests + updated traceability matrix + passing CI + human-visible in the staging environment.** All four, not any three. (See §3.3.)

### 3.4 Dev-time human control (parallel to C1)
- **No AI dev agent merges to `main` without explicit human approval.** PRs, not direct pushes.
- **The human operator must always be able to see what dev agents are working on** and be able to stop them. This mirrors C1 for the product's runtime agents — the principle applies to the agents writing the code too.
- **One issue per branch, one branch per session.** No sprawling multi-feature branches. This keeps blast radius small and review tractable.
- **Every commit message references the issue** (`#24`) so the traceability matrix stays live.
- Dev agents must read REQUIREMENTS.md before starting and update it before finishing if scope changed.

### 3.5 Repeatable seed data is the test bed
- Because AI dev agents cannot run against live Gmail during development, the **seed dataset (`#45`) is the primary test fixture**, not an afterthought. Seed data must exist before the agents that consume it.
- Every extraction/parsing/comparison agent ships with its seed inputs and expected outputs checked into the repo.

### 3.6 Code commenting standard
- **All code written by AI dev agents must include detailed, thorough comments.** This is not optional — it is a hard requirement on every file, every function, every non-trivial block.
- Comments must explain **why**, not just **what**. `# Loop through carriers` is useless. `# Send RFQ to each carrier in the preferred list; skip any that declined this lane in the last 30 days` is useful.
- Every module/file must have a top-level docstring or comment block explaining: what this file does, where it fits in the system, and what calls it or what it calls.
- Every function must have a docstring explaining: purpose, parameters, return value, side effects (DB writes, API calls, emails enqueued), and which cross-cutting constraints (C1–C7) apply to it.
- Complex logic (state transitions, scoring algorithms, matching heuristics, prompt construction) must have inline comments explaining the reasoning step by step.
- Comments must use **operator/business language** where applicable, not just code jargon. Example: `# Flag for human review if confidence < 0.90 (see C2 — no auto-send without approval)` rather than `# threshold check`.
- **Rationale:** AI dev agents do not carry memory across sessions. The next agent to touch this code will have zero context beyond what is written in the code and REQUIREMENTS.md. Comments are the inline context that prevents regressions and misinterpretation.

### 3.7 Guardrails for AI dev
- Never commit secrets. Use `.env.example` only; real `.env` is git-ignored.
- Never weaken a cross-cutting constraint in §5 (C1–C7) to make an issue easier to ship. If a constraint blocks an issue, stop and raise it with the human.
- Never mark an issue "done" unless its acceptance criteria are machine-verified (§2.3).
- Never auto-send email, auto-approve drafts, or bypass HITL gates — not even in tests. Use `status=approved_for_test` with explicit test-harness code paths if needed.
- Prefer reading the existing code and reusing patterns over inventing new ones. New architectural patterns require a human decision.

---

## 3. Users & Stakeholders

| Role | Description | Primary surfaces |
|---|---|---|
| **Broker / operator** (Jillian @ Beltmann) | Daily user. Handles RFQs, approves drafts, monitors carriers. | Home, Needs Review, RFQs, Inbox, History |
| **Broker admin / owner** | Configures workflows, policies, mailboxes, cost caps. | Settings, Agent controls |
| **Customer** (shipper) | Sends RFQ, replies to clarifications, receives quote. | Email only — never touches the app |
| **Carriers** | Receive bid requests, return pricing. | Email only |
| **Internal engineer** | Implements, extends, and debugs agents and integrations. | Agent → Decisions, logs, runbooks |

---

## 4. Scope

### 4.1 In scope for MVP / Beltmann demo
- Inbound email ingestion (seeded folder acceptable for demo) — `#12`
- LLM-powered RFQ extraction with confidence scoring — `#23 #24`
- Message → RFQ matching — `#13`
- RFQ state machine with audit trail — `#14`
- Missing-info detection and clarification drafting — `#15`
- Structured quote sheet generation — `#16`
- HITL approval queue with keyboard-driven flow — `#26`
- Outbound email sending gated by approval — `#25`
- Broker home dashboard, RFQs list, detail drawer, inbox view, history — `#17 #27 #28 #29 #30`
- Settings with workflow toggles, approval policies, mailbox status — `#31`
- Agent observability (decisions, runs, queue, memory, schedule, guidance, controls) — `#37 #38 #39 #40 #41 #42 #43 #44`
- Worker process and scheduler — `#47`
- Deploy environment, LLM API credentials, cost caps, decision logging, run tracking — `#19 #20 #21 #22`
- Realistic Beltmann seed data and demo script — `#45 #46`
- Carrier RFQ distribution, parsing, comparison, pricing, customer quote — `#32 #33 #34 #35 #36`

### 4.2 Post-demo (still v1)
- Real Gmail OAuth integration — `#48`
- Agent memory / learning from approved drafts — `#49`
- Daily summary email (proof-of-value lever) — `#50`
- Error handling, retries, dead-letter queue — `#51`
- Observability: structured logs, metrics, alerts — `#52`
- Backup and disaster recovery — `#53`

### 4.3 v2 (deferred)
- User authentication (beyond hardcoded demo user) — `#54`
- Multi-tenant data isolation — `#55`
- Usage metering (per-mailbox, per-quote) — `#56 #57`
- Stripe billing — `#58`
- Self-serve customer onboarding — `#59`

### 4.4 Documentation (supporting, parallel to build)
- Data model DDL — `#60`
- API OpenAPI spec — `#61`
- Agent contracts — `#62`
- Environment setup runbook — `#63`

### 4.5 Explicitly NOT in scope (ever, or until re-evaluated)
- LangGraph, Temporal, or any heavyweight orchestration framework
- Real-time WebSocket updates (polling is the standard)
- Carrier scoring / market rate intelligence
- Reverse auction features
- Mobile app (mobile web is enough)
- Auto-send for any outbound (all outbound is HITL until operator explicitly opts in)
- MCP server or LLM desktop integration

---

## 5. Cross-Cutting Constraints

These govern every feature. They are non-negotiable and override any conflicting requirement below. **They are repeated inline in affected FR/NFR sections** so that an AI dev agent reading a single section sees the rule without needing to load the whole document.

### C1 — Human control over agents (CRITICAL)
- **No agent runs without a human explicitly enabling its workflow.** Toggling a workflow off in Settings stops the worker from dispatching that workflow within 30 seconds. — `#31 #47`
- **A global kill switch pauses all workflows instantly.** In-flight runs finish cleanly; no new runs start. — `#31`
- **Every running, queued, or scheduled agent task is visible to the operator** in real time, with the ability to cancel. — `#39 #41`
- **No background agent activity is hidden.** Even silent, routine activity is auditable in Agent → Decisions. — `#37`

### C2 — HITL gating on every outbound action
- **No email sends without `approved=true` on the draft record.** This applies to customer replies, carrier RFQs, and customer quotes. — `#25`
- Approval is a deliberate human action (click, keypress, or API call with user identity). It cannot be automated.
- Approvals are fully audited: who approved, when, what version of the draft they approved, and whether they edited before approving.

### C3 — Plain-English operator language
- The UI must never expose internal agent terminology (`extraction_completed`, `run_id`, `tool_use_result`). It must always translate to operator language (`Pulled 5 new quote requests`, `Draft ready for review`, `Load flagged for clarification`). — `#17 #27`
- Technical details (prompts, token counts, costs, durations) are available behind a "View system reasoning" disclosure, never on the main surface. — `#27 #37`

### C4 — Reversibility and visible reasoning
- Every action the system takes must be explainable in plain English from the RFQ detail timeline. — `#27`
- Every AI decision must be traceable to the prompt, model, tokens, cost, and duration that produced it. — `#21 #37`
- State changes happen through explicit transition rules, not ad-hoc updates. Manual overrides are allowed and logged. — `#14`

### C5 — Hard cost caps
- Daily and monthly LLM API cost caps enforced at the provider abstraction layer. Hitting the cap hard-stops further calls. Caps apply across all providers combined. — `#20 #44`
- Every LLM API call logs prompt, model, provider, tokens, cost, and duration. Total cost per run rolls up from individual calls. — `#21 #22`

### C6 — Single-tenant for v1
- Until multi-tenant work in `#55` lands, the system is single-tenant. Single customer (Beltmann), single organization, single mailbox. Do not prematurely add `org_id` scaffolding that will need rework.

### C7 — Human control over dev-time AI agents (parallel to C1)
- **AI coding agents never merge to `main` without an explicit human-approved PR.** Direct pushes to `main` are disallowed.
- **The human operator can see, pause, and stop any dev-agent session in progress.** This parallels C1 for product-time agents — if C1 applies to agents that talk to customers, it applies just as strongly to agents that write the code.
- **Every agent-authored commit references the GitHub issue** it implements so traceability is preserved automatically.
- **Dev agents must update REQUIREMENTS.md in the same commit** that changes scope or introduces a new constraint. Requirements drift is not allowed to accumulate.
- **Dev agents must never weaken a cross-cutting constraint (C1–C7) to make a task easier.** If a constraint blocks progress, stop and escalate to the human.

---

## 6. Functional Requirements

Each requirement is `FR-<area>-<n>` with the issue(s) that implement it.

### 6.1 Email ingestion & routing

| ID | Requirement | Issues |
|---|---|---|
| FR-EI-1 | Ingest messages from one mailbox provider; persist sender, recipients, subject, body, timestamps, thread metadata, and raw content. | `#12` |
| FR-EI-2 | For the demo, a seeded folder of sample emails is an acceptable source. Real Gmail OAuth is a post-demo replacement. | `#12 #48` |
| FR-EI-3 | Every inbound message is attached to an RFQ via deterministic thread/reply matching first, context scoring second. | `#13` |
| FR-EI-4 | Ambiguous matches do NOT auto-attach; they enter a "Needs review" routing queue visible in the Inbox view. | `#13 #28` |
| FR-EI-5 | Inbox view shows every routed message with a badge: `Attached to RFQ #N`, `New RFQ created`, `Needs review`, or `Ignored`. | `#28` |

### 6.2 RFQ data model & state

| ID | Requirement | Issues |
|---|---|---|
| FR-DM-1 | Schema covers: `rfqs`, inbound/outbound `messages`, `agent_runs`, `agent_calls`, `approvals`, state transition audit log, human review queue, carrier bids. | `#11 #21 #22` |
| FR-DM-2 | Every RFQ has a current state AND a full state transition history. | `#11 #14` |
| FR-DM-3 | RFQ states (MVP): `Needs clarification`, `Ready to quote`, `Waiting on carriers`, `Quotes received`, `Waiting on broker review`, `Quote sent`, `Won / Lost / Cancelled`. | `#14` |
| FR-DM-4 | State transitions happen through explicit rules. Manual override is supported and logged. | `#14` |
| FR-DM-5 | Historical (closed) RFQs are immutable. | `#30` |

### 6.3 Agent pipeline

| ID | Requirement | Issues |
|---|---|---|
| FR-AG-1 | Extraction agent turns inbound emails into structured RFQ fields (origin, destination, equipment, truck count, pickup/delivery, commodity, weight, special requirements, contact) using LLM tool-use / function calling. Provider-agnostic — works with any supported LLM. | `#24` |
| FR-AG-2 | Every extracted field has a confidence score (0.0–1.0). Default escalation threshold 0.90, configurable per workflow. | `#23` |
| FR-AG-3 | Low-confidence fields flag the whole RFQ into Needs Review with a human-readable reason. | `#23` |
| FR-AG-4 | Missing-information detection identifies required fields that are absent and drafts a clarification email. | `#15` |
| FR-AG-5 | A structured quote sheet can be generated from a complete RFQ, suitable for sending to carriers. | `#16` |
| FR-AG-6 | Carrier RFQ distribution sends personalized emails to 1–50 carriers in one approved action, with per-carrier delivery tracking and nudge-on-silence timers. | `#32` |
| FR-AG-7 | Carrier quote responses are parsed into structured bids (rate, currency, terms, notes, availability) regardless of format. Ambiguous quotes escalate to review. | `#33` |
| FR-AG-8 | Bid comparison ranks carriers by normalized total landed cost, surfaces top 3 with defensible reasons, and flags outliers. | `#34` |
| FR-AG-9 | Pricing engine applies configurable markup rules (percentage, flat, per-customer) with minimum margin enforcement and audited manual overrides. | `#35` |
| FR-AG-10 | Customer quote generator produces a branded quote, sends via the approved outbound pipeline, and routes customer replies back to the same RFQ. | `#36` |

### 6.4 Human-in-the-loop (HITL)

| ID | Requirement | Issues |
|---|---|---|
| FR-HI-1 | Every outbound email draft persists with `status=pending_approval` and does not send until explicitly approved. | `#25` |
| FR-HI-2 | Approval modal shows: original shipper message, drafted reply, reason flag, and four actions — Send As-Is, Edit, Reject, Skip. | `#26` |
| FR-HI-3 | Keyboard shortcuts: `Enter` = approve/send, `E` = edit, `R` = reject, `S` = skip, `J/K` = next/prev, `Esc` = close. The entire queue must be clearable without touching the mouse. | `#26` |
| FR-HI-4 | Any HITL item must be clearable in under 10 seconds. | `#26` |
| FR-HI-5 | Approval state updates propagate through the UI without a page reload. | `#26` |
| FR-HI-6 | Failed sends (bounces, auth errors) do NOT disappear — they create a review card. | `#25` |

### 6.5 Broker UI

| ID | Requirement | Issues |
|---|---|---|
| FR-UI-1 | Home dashboard renders three zones: Needs Review, Active RFQs, Recent Activity. Mobile stacks the same three zones. | `#17` |
| FR-UI-2 | Home zones populate from real backend data and poll every ~10 seconds (no WebSockets required in v1). | `#17` |
| FR-UI-3 | Active RFQs list is organized around business state, never agent internals ("Needs clarification", not "Extraction Agent running"). | `#17 #29` |
| FR-UI-4 | Recent Activity feed shows only business-level events; internal steps are hidden unless drilling in. | `#17` |
| FR-UI-5 | RFQ detail drawer has four sections: Summary, Messages (full thread), Current Status (state/why/missing/next), and Actions & History timeline. | `#27` |
| FR-UI-6 | Detail drawer is reachable from Home, RFQs list, Inbox, History, and any activity-feed item. | `#27` |
| FR-UI-7 | RFQs list view supports 500+ active RFQs with filter pills by state, live search on shipper/route/load, and instant filter count updates. | `#29` |
| FR-UI-8 | Inbox view supports filter pills (Shipper/Carrier/Review/Ignored) + live search. | `#28` |
| FR-UI-9 | History view has a stat strip (Completed Today, Avg Time to Quote, Approvals This Week, Time Saved) and filters (Won/Lost/Cancelled/Today/Week/Month). | `#30` |
| FR-UI-10 | Time-saved metric must be defensible against a manual baseline, not a fabricated number. | `#30` |

### 6.6 Agent observability

| ID | Requirement | Issues |
|---|---|---|
| FR-OB-1 | Decisions view lists every agent call (paginated) with expandable cards showing trigger, full prompt, model, cost breakdown, and action taken. Filter by agent, date, cost, status. | `#37` |
| FR-OB-2 | Run timeline view visualizes agent runs across 24h / 7d / 30d with per-run drilldown to individual calls. Long-running and expensive runs are highlighted. | `#38` |
| FR-OB-3 | Task queue view shows four live buckets — Running, Queued, Waiting HITL, Done — with auto-refresh every 5–10s and cancel/reorder controls. | `#39` |
| FR-OB-4 | Memory view shows facts, preferences, rules, and patterns the agent has learned; broker can audit, edit, delete, and add entries. | `#40` |
| FR-OB-5 | Schedule view lists cron jobs with next-run, last-run, and pause/resume controls. Pausing a job actually stops the worker. | `#41` |
| FR-OB-6 | Ask Golteris chat interface lets the broker issue ad-hoc instructions; every message logs as an `agent_call`. | `#42` |
| FR-OB-7 | Guidance editor lets the broker edit the system prompt and active rules; changes take effect on the next decision with edit history preserved. | `#43` |
| FR-OB-8 | Agent controls UI exposes permission toggles, cost caps, max tokens per decision, and model selector. Toggles are hard limits. | `#44` |

### 6.7 Settings & control surface

| ID | Requirement | Issues |
|---|---|---|
| FR-SE-1 | Settings page provides workflow on/off toggles that actually stop the backend worker within 30 seconds. | `#31 #47` |
| FR-SE-2 | Approval policy toggles define what requires HITL per workflow (customer reply, carrier RFQ, customer quote). | `#31` |
| FR-SE-3 | Mailbox connection status shows real health (green/red) and last-checked timestamp. | `#31` |
| FR-SE-4 | Cost caps are editable from Settings and enforced at the API wrapper. | `#20 #31 #44` |
| FR-SE-5 | Global kill switch pauses all workflows immediately. In-flight runs finish cleanly. | `#31` |

### 6.8 Worker & scheduling

| ID | Requirement | Issues |
|---|---|---|
| FR-WK-1 | A long-running worker polls the mailbox on a cron (every ~60s), processes queue jobs from a Postgres job table using `SELECT ... FOR UPDATE SKIP LOCKED`, and fires delayed jobs (nudge timers, reminders). | `#47` |
| FR-WK-2 | Worker survives crashes — all state lives in Postgres, nothing in memory. | `#47` |
| FR-WK-3 | Worker idle state is visible in the Tasks view. | `#39 #47` |

---

## 7. Non-Functional Requirements

### 7.1 Performance
| ID | Requirement | Issues |
|---|---|---|
| NFR-PE-1 | New email → RFQ visible in UI in under 60 seconds. | `#12 #17 #24 #47` |
| NFR-PE-2 | HITL approval modal clears in under 10 seconds for a typical item. | `#26` |
| NFR-PE-3 | RFQs list scales to 500+ active RFQs without UI degradation. | `#29` |
| NFR-PE-4 | Home screen polling interval ≤ 10 seconds. | `#17` |

### 7.2 Observability
| ID | Requirement | Issues |
|---|---|---|
| NFR-OB-1 | Every LLM API call logs prompt, model, provider, input tokens, output tokens, cost USD, and duration ms to `agent_calls`. Cost matches the provider's bill within 1%. | `#21` |
| NFR-OB-2 | Every workflow invocation creates an `agent_runs` row with start/end, status, total cost, total tokens, and links to its child calls. | `#22` |
| NFR-OB-3 | Structured JSON logs include `request_id`, `run_id`, and `rfq_id` on every line so any complaint traces to root cause. | `#52` |
| NFR-OB-4 | Metrics cover call count, error rate, p95 latency, and cost per day, with alerts for error spikes, cost caps, and queue backup. | `#52` |

### 7.3 Reliability & durability
| ID | Requirement | Issues |
|---|---|---|
| NFR-RE-1 | Transient failures retry with exponential backoff. Permanent failures go to a dead-letter queue that is reviewable and reprocessable. | `#51` |
| NFR-RE-2 | No silent failures. Every error surfaces as either a friendly review card or a structured log + alert. | `#51` |
| NFR-RE-3 | Postgres point-in-time recovery. RPO < 1 hour. RTO < 4 hours. Restore drill executed at least once before customer trial begins. | `#53` |

### 7.4 Cost & budget
| ID | Requirement | Issues |
|---|---|---|
| NFR-CO-1 | Daily and monthly LLM cost caps enforced at the provider abstraction layer with hard stop on breach. Caps apply across all providers combined. | `#20 #44` |
| NFR-CO-2 | Budget alarms fire before caps are reached. | `#20` |
| NFR-CO-3 | API keys never appear in source or logs. | `#20` |

### 7.5 Security
| ID | Requirement | Issues |
|---|---|---|
| NFR-SE-1 | Single-tenant isolated database for v1. | — |
| NFR-SE-2 | Secrets stored in a secret manager (not `.env` in source). | `#20` |
| NFR-SE-3 | Audit log on every inbound message, agent decision, approval, and outbound send. | `#11 #21 #22 #25` |
| NFR-SE-4 | Multi-tenant data isolation (`org_id` on every row, app-level or RLS enforcement, pen-tested) before v2 customer #2 lands. | `#55` |
| NFR-SE-5 | User authentication (email/password or Google OAuth, sessions, role model: owner/operator/viewer) before any non-demo customer has access. | `#54` |

### 7.6 Deployment
| ID | Requirement | Issues |
|---|---|---|
| NFR-DE-1 | Deployable staging environment with Postgres + worker + web server on a custom subdomain, auto-deployed from `main`. | `#19` |
| NFR-DE-2 | `.env.example` documents every environment variable. | `#19` |

---

## 8. Demo Requirements — Beltmann (Wednesday, April 8, 2026)

**Due date: 2026-04-08** — three days from today (2026-04-05). Issues `#18` and `#46`.

### 8.1 Demo scope (10-minute walkthrough)
1. Home screen shows work already in progress (2 min) — `#17`
2. Drop a new Beltmann-style email → watch it appear as an RFQ (2 min) — `#12 #24 #17`
3. Approve the drafted clarification in Needs Review (1 min) — `#26 #25`
4. Open the RFQ detail and walk the audit trail (2 min) — `#27`
5. Show RFQs tab with state filtering (1 min) — `#29`
6. Show History tab with time-saved stats (1 min) — `#30`
7. Show Settings — "nothing runs unless you turn it on" (1 min) — `#31`

### 8.2 Demo acceptance criteria
- [ ] Happy-path workflow works end-to-end on the deployed environment — `#18 #19`
- [ ] 10-15 realistic Beltmann-style seed emails loaded, covering happy path, missing info, ambiguous destination, multi-truck, special requirements, and noise — `#45`
- [ ] 5-10 sample carrier responses in varied formats loaded — `#45`
- [ ] Demo script documented step-by-step with fallback lines for every step — `#46`
- [ ] Dry-run executed at least 3 times before the meeting — `#46`
- [ ] What's live vs. mocked is explicitly identified and documented — `#18`
- [ ] Fallback plan documented (e.g., recorded backup screen capture) — `#18`
- [ ] No technical jargon leaks into the UI during the demo — `#17 #27`
- [ ] Mobile responsiveness verified (Jillian may pull it up on her phone) — `#17`

### 8.3 What Jillian must walk away believing
> *"I don't have to babysit an AI system. I can see what came in, what happened to it, what needs me, and what is moving. Nothing runs without my permission, and every minute it saves is on the screen."*

---

## 9. Definition of Done (v1 / MVP)

### 9.1 Product behavior
- [ ] A new email lands and appears as an RFQ in under 60 seconds
- [ ] A drafted reply can be approved in under 10 seconds with keyboard only
- [ ] The RFQ detail view explains every decision in plain English
- [ ] The RFQs tab shows all active work with state filtering
- [ ] The History tab shows time-saved stats
- [ ] Settings turns the whole thing off and back on — and the worker actually stops
- [ ] The full 10-minute demo runs without errors
- [ ] Nothing in the UI uses technical jargon
- [ ] No agent runs without a human-enabled workflow
- [ ] No outbound message sends without explicit approval
- [ ] Every LLM call is logged with prompt, model, provider, tokens, cost, and duration
- [ ] Cost caps enforce and alarm

### 9.2 AI-development hygiene (per §2 rules)
- [ ] Every closed issue has a corresponding entry in §10 traceability matrix pointing at real requirement sections
- [ ] Every closed issue has machine-verifiable acceptance criteria (test, command, or observable artifact)
- [ ] No commits on `main` that bypass PR review
- [ ] Every commit references its issue number (`#NN`)
- [ ] Every scope change is reflected in REQUIREMENTS.md in the same PR
- [ ] Seed data (`#45`) exists and is used as the test fixture for extraction, matching, and comparison agents
- [ ] No cross-cutting constraint (C1–C7) has been weakened to unblock an issue

---

## 10. Traceability Matrix

This section is the forward lookup from issue → requirement section. Use this when a new issue is created or an existing one changes scope — update the relevant FR/NFR and back-reference here.

| Issue | Title | Requirement sections |
|---|---|---|
| #11 | RFQ data model and persistence schema | §5.2 FR-DM-1..5, §4 C4, §6.5 NFR-SE-3 |
| #12 | Inbound email ingestion | §5.1 FR-EI-1..2, §6.1 NFR-PE-1 |
| #13 | Message-to-RFQ matching | §5.1 FR-EI-3..4 |
| #14 | RFQ state transition engine | §5.2 FR-DM-2..4, §4 C4 |
| #15 | Missing-info detection & follow-up drafting | §5.3 FR-AG-4 |
| #16 | Structured quote sheet generation | §5.3 FR-AG-5 |
| #17 | Broker home dashboard | §5.5 FR-UI-1..4, §7.1, §4 C3 |
| #18 | Beltmann demo prep | §7 |
| #19 | Staging environment deploy | §6.6 NFR-DE-1..2 |
| #20 | LLM API credentials & cost caps | §4 C5, §6.4 NFR-CO-1..3 |
| #21 | Agent decision logging | §4 C4, §6.2 NFR-OB-1 |
| #22 | Agent run tracking | §6.2 NFR-OB-2 |
| #23 | Confidence scoring & HITL escalation | §5.3 FR-AG-2..3 |
| #24 | RFQ extraction agent | §5.3 FR-AG-1 |
| #25 | Outbound email with approval gate | §4 C2, §5.4 FR-HI-1, FR-HI-6 |
| #26 | Approval modal & HITL flow | §5.4 FR-HI-2..5, §6.1 NFR-PE-2 |
| #27 | RFQ detail drawer | §5.5 FR-UI-5..6, §4 C3..C4 |
| #28 | Inbox view | §5.1 FR-EI-5, §5.5 FR-UI-8 |
| #29 | RFQs list view | §5.5 FR-UI-3, FR-UI-7, §6.1 NFR-PE-3 |
| #30 | History view | §5.5 FR-UI-9..10, §5.2 FR-DM-5 |
| #31 | Settings page | §5.7 FR-SE-1..5, §4 C1 |
| #32 | Carrier RFQ distribution | §5.3 FR-AG-6 |
| #33 | Carrier quote parser | §5.3 FR-AG-7 |
| #34 | Bid comparison & ranking | §5.3 FR-AG-8 |
| #35 | Pricing & markup engine | §5.3 FR-AG-9 |
| #36 | Customer quote generation & delivery | §5.3 FR-AG-10 |
| #37 | Agent decisions audit view | §4 C1, §5.6 FR-OB-1 |
| #38 | Agent run timeline view | §5.6 FR-OB-2 |
| #39 | Agent tasks queue view | §4 C1, §5.6 FR-OB-3, §5.8 FR-WK-3 |
| #40 | Agent memory view | §5.6 FR-OB-4 |
| #41 | Agent schedule view | §4 C1, §5.6 FR-OB-5 |
| #42 | Ask Golteris chat | §5.6 FR-OB-6 |
| #43 | Guidance editor | §5.6 FR-OB-7 |
| #44 | Agent controls UI | §5.6 FR-OB-8, §4 C5 |
| #45 | Beltmann seed dataset | §7.2 |
| #46 | Beltmann demo script | §7.2 |
| #47 | Worker & scheduler | §5.8 FR-WK-1..3, §4 C1 |
| #48 | Gmail OAuth integration | §5.1 FR-EI-2 (post-demo) |
| #49 | Agent memory / learning | §3.2 (post-demo) |
| #50 | Daily summary email | §3.2 (post-demo) |
| #51 | Error handling & DLQ | §6.3 NFR-RE-1..2 |
| #52 | Observability & alerts | §6.2 NFR-OB-3..4 |
| #53 | Backup & disaster recovery | §6.3 NFR-RE-3 |
| #54 | User authentication | §6.5 NFR-SE-5 |
| #55 | Multi-tenant isolation | §6.5 NFR-SE-4 |
| #56 | Per-mailbox usage metering | §3.3 (v2) |
| #57 | Per-quote usage metering | §3.3 (v2) |
| #58 | Stripe billing integration | §3.3 (v2) |
| #59 | Customer onboarding flow | §3.3 (v2) |
| #60 | Data model DDL docs | §3.4 |
| #61 | API OpenAPI spec | §3.4 |
| #62 | Agent contracts docs | §3.4 |
| #63 | Environment setup runbook | §3.4 |

---

## 11. Change Log

| Date | Change | Author |
|---|---|---|
| 2026-04-05 | Initial consolidation from README.md, PROJECT-PLAN.md, planning/product-ux.md, planning/workflow.md, Beltmann meeting recap, and GitHub issues #11–#63. | Curt |
