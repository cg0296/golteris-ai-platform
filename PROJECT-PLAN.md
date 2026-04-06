# Golteris — Implementation Workflow

A step-by-step build plan to go from zero to a Beltmann-demo-ready product. This is the workflow that turns [product-ux.md](product-ux.md) into shipped software.

Principle: **build the smallest thing that tells the story, in the order that lets you demo at every step.**

---

## Phase 0 — Foundations (Week 1)

Nothing runs yet. The goal is to have a working skeleton on a box with a database and a deployable app.

### Deliverables

- [ ] Git repo, CI, and a deployable environment (Render, Fly.io, Railway, or a $10 VPS)
- [ ] Postgres database provisioned
- [ ] Python backend scaffold (FastAPI) with a health endpoint
- [ ] Static frontend served from the same app (can be plain HTML/JS initially — the prototype in `product-ux.html` is a good starting point)
- [ ] Anthropic API key wired up and a single "hello Claude" test endpoint that proves tool-use works
- [ ] Basic auth (even hardcoded user for demo) so the UI has a logged-in state

### Core data model (first draft)

```
workflows           — id, name, enabled, config, created_at
rfqs                — id, customer_id, route, equipment, state, created_at, updated_at
messages            — id, rfq_id, direction (in/out), sender, subject, body, received_at
agent_runs          — id, rfq_id, agent_name, input, output, status, started_at, finished_at
approvals           — id, rfq_id, type, draft_body, status (pending/approved/rejected), created_at, resolved_at
audit_events        — id, rfq_id, event_type, actor (system/user), description, created_at
```

Keep it small. You can add tables later. These six cover the entire demo.

---

## Phase 1 — The Agent Core (Week 2)

Build the minimum agent pipeline that turns one email into one structured RFQ in the database. No UI yet. Just the engine.

### Deliverables

- [ ] **Mailbox poller** — a Python function that pulls messages from a connected inbox on a cron (or for dev, from a seeded folder of sample emails). Supports any email provider via the abstraction layer (IMAP, Gmail, Outlook). Writes to `messages` table.
- [ ] **Extraction agent** — Python function that reads a message, calls Claude with a structured tool-use schema, and writes extracted fields into `rfqs`. Logs the run to `agent_runs`.
- [ ] **Validation agent** — checks required fields, sets `state` to `needs_clarification` or `ready_to_quote`, drafts a follow-up if missing data.
- [ ] **Orchestrator loop** — a simple worker script that polls the database for RFQs in each state and dispatches the next agent.
- [ ] **Seed data** — 5-10 sample emails covering happy path, missing equipment, ambiguous destination, multi-truck project, and a noise message (not an RFQ).

### Acceptance test

Drop a sample email into the seed folder. Within 60 seconds, an RFQ row exists with extracted fields and an `audit_events` trail showing every step. No UI needed — just query Postgres.

**This is the "does the AI work at all" gate.** Do not build the UI until this passes.

---

## Phase 2 — The Home Screen (Week 3)

Now put a face on it. The goal is the three-column home screen from the prototype.

### Deliverables

- [ ] **API endpoints**:
  - `GET /api/rfqs/active` — all non-closed RFQs with state and next-action
  - `GET /api/approvals/pending` — Needs Review queue
  - `GET /api/activity/recent` — filtered event feed (last 20 meaningful events)
- [ ] **Home screen** — three columns (Needs Review, Active RFQs, Recent Activity). Can be plain HTML/JS/htmx/React — whatever ships fastest.
- [ ] **Live polling** — refresh every 10 seconds. No WebSockets yet.
- [ ] **Plain-English language layer** — a small helper that maps internal events (`extraction_completed`, `validation_failed`) to operator language (`Draft reply prepared`, `Load flagged`).

### Acceptance test

Open the home screen. Drop three sample emails into the test folder. Within 60 seconds, you see new RFQs appear in the Active column, a new draft reply in Needs Review, and three new lines in Recent Activity.

---

## Phase 3 — The HITL Approval Flow (Week 4)

This is the most-used interaction in the product. It has to feel fast.

### Deliverables

- [ ] **Approval modal** — customer message, drafted reply, reason flag, four buttons (Send / Edit / Reject / Skip)
- [ ] **API endpoints**:
  - `GET /api/approvals/:id`
  - `POST /api/approvals/:id/approve` — marks approved, enqueues send
  - `POST /api/approvals/:id/reject`
  - `POST /api/approvals/:id/edit` — accepts an edited body
- [ ] **Send agent** — consumes approved items, sends via the configured email provider (or mock outbox for demo), writes outbound `messages` row and `audit_events`
- [ ] **Keyboard shortcuts** — Enter = approve, E = edit, R = reject, S = skip, J/K = next/prev
- [ ] **Confirmation toasts** — "Sent to Tom @ Beltmann"

### Acceptance test

Clear the entire Needs Review queue (3-5 items) in under 60 seconds using only the keyboard. Every outbound message appears in the Recent Activity feed.

---

## Phase 4 — The RFQ Detail View (Week 5)

This is the trust surface. When Jillian asks *"why did it do that?"* this is where you answer.

### Deliverables

- [ ] **RFQ detail drawer** with four sections:
  - Summary (route, equipment, dates, customer, special requirements)
  - Current Status (state, why, missing, recommended)
  - Messages (full inbound/outbound thread attached to this RFQ)
  - Actions & History (timeline of every agent action and human decision)
- [ ] **API endpoint** — `GET /api/rfqs/:id` returns the full record with messages, timeline, and reasoning
- [ ] **Raw-data disclosure** — a collapsible "View system reasoning" section that shows the Claude prompt/response for each agent run (for debugging, not for brokers)
- [ ] **Deep links** — clicking an activity item or RFQ card opens the drawer directly to that RFQ

### Acceptance test

From any Active RFQ card, open the drawer and explain in plain English exactly what happened to that load, from email arrival to current state, without looking at the database.

---

## Phase 5 — RFQs Tab & History Tab (Week 6)

Now the daily-operations views beyond the home screen.

### RFQs tab

- [ ] Full paginated table of all active RFQs
- [ ] Filter pills by state (Needs clarification, Ready to quote, Waiting on carriers, Quotes received, Waiting on broker, Quote sent)
- [ ] Search by customer / route / load #
- [ ] Same RFQ detail drawer on click

### History tab

- [ ] Stat strip at top: Completed Today, Avg Time to Quote, Approvals This Week, Time Saved This Week
- [ ] Filters: Won / Lost / Cancelled / Today / This Week / This Month
- [ ] Full table of closed RFQs with outcome pill, cycle time, and close time
- [ ] Data model addition: `rfqs.outcome` (won/lost/cancelled), `rfqs.closed_at`, `rfqs.quoted_amount`

### Acceptance test

Filter to "Won this week" and read the total revenue and average cycle time at a glance. Click into any historical RFQ and see the full audit trail.

---

## Phase 6 — Settings & Workflow Controls (Week 7)

The "I am in control" surface. Quick, but essential for the demo.

### Deliverables

- [ ] Workflow on/off toggles (with real effect — flipping off stops the cron poller)
- [ ] Approval policy toggles (require approval before customer reply, before carrier RFQ, etc.)
- [ ] Mailbox connection status (green dot = healthy, last checked timestamp)
- [ ] Per-workflow scope: which mailbox, which senders, which actions allowed
- [ ] Kill switch — pause all workflows instantly, in-flight runs finish cleanly

### Acceptance test

Toggle a workflow off. Confirm the poller stops within 30 seconds. Toggle it back on. Confirm a new email gets processed.

---

## Phase 7 — Polish for the Beltmann Demo (Week 8)

The deltas that turn a working product into a convincing demo.

### Deliverables

- [ ] **Realistic seed data** — 20-30 sample emails that mirror Beltmann's actual project quoting pattern (multiple truck types, special equipment, unload requirements, storage variables — exactly what the meeting recap said Jillian deals with)
- [ ] **Demo script** — 10-minute walkthrough:
  1. Show home screen with work already in progress (2 min)
  2. Drop a new Beltmann-style email → watch it appear as an RFQ (2 min)
  3. Approve the drafted clarification in the Needs Review queue (1 min)
  4. Open the RFQ detail and walk through the audit trail (2 min)
  5. Show the RFQs tab with filtering by state (1 min)
  6. Show the History tab with time-saved stats (1 min)
  7. Show Settings — "nothing runs unless you turn it on" (1 min)
- [ ] **Mobile responsiveness verified** — Jillian may pull it up on her phone
- [ ] **Daily summary mock** — a static example of the end-of-day proof-of-value message
- [ ] **Error states handled** — if something fails, show a friendly "flagged for your review" card, never a stack trace
- [ ] **Loading states** — no blank screens while data fetches

### Acceptance test

Deliver the full 10-minute demo without touching code, without any broken states, and without any technical jargon leaking into the UI.

---

## Build Order Rationale

Why this sequence:

1. **Foundations first** — you need a box that can deploy and a database before anything else matters.
2. **Engine before UI** — if the agent pipeline doesn't work in the database, no UI will save it. Prove extraction works end-to-end before you paint screens.
3. **Home screen before detail screens** — the home screen is the highest-value surface. Build it first so you can demo it even if nothing else is done.
4. **Approvals next** — this is the most frequent interaction and the biggest trust lever. Nail it early.
5. **Detail view next** — only matters once you have something to drill into.
6. **List and history views last** — they're lower-value until there's real data to fill them.
7. **Settings last** — important conceptually, but the demo can exist with settings that are "built in" at the code level. Real UI controls can wait until v2 if needed.

---

## Risks and Mitigations

| Risk | Mitigation |
|---|---|
| Claude extraction is unreliable on messy emails | Start with a tight JSON schema, strong examples in the prompt, and low-confidence flagging. Log every extraction for review. |
| Email provider auth takes longer than expected | For the demo, use a seeded folder of sample emails instead of a live inbox. Connect real email provider as v2. |
| The orchestrator loop becomes complex | Keep it boring — a Python worker that `SELECT ... FOR UPDATE SKIP LOCKED` on a jobs table. No frameworks. |
| Jillian asks about auth/security/compliance | Have a one-pager ready. Real answer: single-tenant, isolated DB, audit log on every action, human approval before any outbound. |
| Demo environment dies mid-demo | Record a backup screen capture. Always demo against a stable deployed environment, never localhost. |

---

## What's Explicitly Deferred to v2

Things to *not* build before the Beltmann demo, even though they're on the roadmap:

- LangGraph, Temporal, or any heavyweight orchestration framework
- Multi-tenant / org management
- Real-time WebSocket updates (polling is fine)
- Carrier scoring / market rate intelligence
- Reverse auction features
- Mobile app (mobile web is enough)
- MCP server for Claude Desktop integration
- Notification / email / Slack digests
- Advanced scope rules per customer
- Auto-send on high-confidence items (everything is HITL until a user explicitly opts in)

Every one of these is a good idea. None of them matters for the first demo.

---

## Definition of Done for the Demo

You can say "ready" when all of these are true:

- [ ] A new email can land in the system and appear as an RFQ in under 60 seconds
- [ ] A drafted reply can be approved in under 10 seconds with keyboard
- [ ] The RFQ detail view explains every decision in plain English
- [ ] The RFQs tab shows all active work with state filtering
- [ ] The History tab shows time-saved stats
- [ ] Settings lets you turn the whole thing off and back on
- [ ] The full 10-minute demo script runs without errors
- [ ] Nothing in the UI uses technical jargon
- [ ] No agent runs without a human-enabled workflow
- [ ] No outbound message sends without explicit approval

When all ten boxes are checked, you're ready for Jillian.

---

## After the Demo

Post-Beltmann priorities depend on how the meeting goes, but the likely order:

1. **Real email provider integration** — Gmail, Outlook, or IMAP (if not already done)
2. **Customer-specific configuration** — Beltmann will want their quote sheet format, their carrier list, their language
3. **Carrier RFQ outbound flow** — the other half of the workflow that wasn't in the demo
4. **Carrier quote inbound + comparison view** — closing the loop
5. **Daily summary emails** — the renewal lever
6. **Multi-user / team support** — so more than just Jillian can use it

That sequence is driven by the commercial note from the meeting recap: *"custom implementation first, then ongoing subscription once the workflow is understood and configured."* The first 30 days of the trial should feel like the product is being shaped around Beltmann, not like they're being fit into a template.
