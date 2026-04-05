# Architecture Decisions — Claude's Perspective

Technology and architecture recommendations for the Golteris AI Platform, with reasoning. These are Claude's recommendations based on the project context, constraints, and goals.

---

## 1. Email Integration Layer: EmailEngine

**Decision:** Use [EmailEngine](https://github.com/postalsys/emailengine) as the email connectivity layer.

**What it does:**
- Self-hosted REST API gateway that sits in front of IMAP/SMTP/Microsoft Graph accounts
- Monitors inboxes and fires webhooks when new emails arrive
- Groups emails into threads/conversations automatically
- Exposes a REST API for sending replies, reading messages, handling attachments
- Supports Microsoft Graph accounts (Beltmann is a Microsoft shop — Teams meeting setup confirmed this)

**Why EmailEngine:**
- Handles all the email plumbing we don't want to build: IMAP IDLE, thread correlation, attachment parsing, send-as
- We build our AI agents and state machine on top of its webhook events
- It's infrastructure, not a helpdesk — no opinionated UI or workflow model forced on us
- Node.js, so it fits cleanly with our TypeScript/Next.js stack

**Alternatives considered:**
- **Microsoft Graph API directly** — would work but means building our own thread grouping, polling/webhook infrastructure, and email send abstraction. EmailEngine wraps all of this.
- **Chatwoot** (28k stars, Ruby/Rails) — battle-tested conversation state machine with email channel support, but it's a full customer support monolith. Too heavy. We'd be fighting its opinions more than building our product.
- **Inbox Zero** (10k stars, TypeScript/Next.js) — closest codebase match with AI email processing already built in, but Gmail-only. No Microsoft Graph support. Would require significant modification.
- **FreeScout / Zammad / UVDesk** — full helpdesk apps in PHP or Ruby. Wrong language, wrong abstraction level.

---

## 2. Orchestration: Custom State Machine (Not n8n)

**Decision:** Build a custom TypeScript state machine. Do not use n8n, Temporal, or any external orchestration platform for the MVP.

**Why not n8n:**
- n8n is a visual workflow builder designed for connecting APIs and triggering actions. It works well for linear automations (webhook → transform → send email).
- Our workflow is not linear. It has:
  - **AI confidence branching** — the next step depends on whether the LLM is confident enough in its extraction, which is a runtime decision, not a drag-and-drop branch.
  - **Multi-day email threads** — a workflow starts, waits days for a carrier reply, then resumes. n8n's execution model is not designed for workflows that pause for days and resume on an external event.
  - **HITL approval gates** — the workflow pauses until a human clicks Approve on a dashboard. n8n can do this with workarounds (webhooks + wait nodes) but it's clunky and hard to debug.
  - **Re-entry loops** — when a customer replies to a clarification email, the workflow needs to re-parse and potentially loop back. This is natural in a state machine but awkward in n8n's flow canvas.
- n8n would add a deployment dependency (self-hosted n8n instance) and a second programming model to learn, for a workflow that's simple enough to express in ~30 lines of TypeScript.
- We would spend more time fighting n8n's model than building the workflow.

**Why a custom state machine works here:**
- We have exactly 10 well-defined states (documented in README)
- Transitions are clear and already mapped
- The logic is simple: check current state → run the appropriate agent → persist new state → log to audit trail
- Full control over HITL gates, confidence thresholds, retry logic, and escalation
- Easy to test, easy to debug, easy to modify during the 30-day trial
- No external dependency to manage

**The 10 states:**
1. `new_request_received`
2. `needs_clarification`
3. `awaiting_customer_reply`
4. `ready_for_sheet_generation`
5. `sent_to_carriers`
6. `awaiting_carrier_quotes`
7. `quotes_received`
8. `quote_comparison_complete`
9. `final_quote_sent`
10. `won_lost_or_closed`

**Future consideration:** If the platform grows beyond a single customer and workflow complexity increases significantly, migrate to **Temporal** for production-grade durable workflow orchestration. Temporal is the correct long-term answer but overkill for a 30-day trial with one customer.

---

## 3. LLM Provider: Anthropic Claude (Haiku + Sonnet)

**Decision:** Use Anthropic Claude as the primary LLM provider with model tiering.

**Model allocation:**
- **Claude Haiku** — intent detection, thread matching, missing field detection. High volume, low complexity, fast, cheap.
- **Claude Sonnet** — RFQ field extraction, carrier bid parsing, follow-up email drafting, quote generation. Lower volume, higher complexity, needs accuracy.

**Why Anthropic:**
- Already building with Claude Code — it's the tool we know
- Claude Sonnet is strong at structured extraction from messy natural language, which is the core value of this system
- Use structured output (tool use / JSON mode) for all extraction tasks to get deterministic schemas back
- Zero-data-retention agreements available

**Why not OpenAI:**
- No strong reason to split across two providers for the MVP
- OpenAI is a fine fallback if needed, but introduces a second SDK, second billing, second set of API quirks for no clear benefit right now

---

## 4. Backend Framework: Next.js 14 (App Router)

**Decision:** Use Next.js 14+ with App Router for both backend API and frontend dashboard.

**Why:**
- Single deployable unit for API routes (webhook receiver, agent orchestration, CRUD) and frontend (broker dashboard)
- TypeScript throughout — one language, one toolchain
- The alternative (separate Express backend + separate React frontend) doubles the deployment surface and is slower to ship for a small team
- Server actions handle broker approval/rejection from the dashboard
- Deploys to Vercel with zero configuration

---

## 5. Database: PostgreSQL via Supabase

**Decision:** Use Supabase (hosted PostgreSQL) with Drizzle ORM.

**Why Supabase:**
- Hosted Postgres with a REST API, built-in auth (for broker login), and realtime subscriptions (for live dashboard updates)
- Free tier is sufficient for the MVP
- Relational model fits our data well: RFQ requests, state transitions (audit log), email messages, carrier bids, carriers, markup rules

**Why Drizzle ORM:**
- Type-safe database access from TypeScript
- Lightweight compared to Prisma
- Schema-as-code with migration support

**Key tables:**
- `rfq_requests` — one row per inbound RFQ, tracks current state
- `rfq_state_transitions` — append-only audit log of every state change
- `email_messages` — raw email metadata and parsed content
- `carrier_bids` — one row per carrier response per RFQ
- `carriers` — carrier directory
- `markup_rules` — configurable markup percentages

---

## 6. Spreadsheet Generation: ExcelJS

**Decision:** Use ExcelJS for generating and parsing Excel files.

**Why:**
- Carriers in freight expect `.xlsx` files, not CSV or Google Sheets links
- ExcelJS generates real Excel files with formatting, multiple sheets, and formulas
- It also parses inbound carrier spreadsheets — one library handles both directions
- Node.js native, fits the stack

---

## 7. Background Jobs: Inngest

**Decision:** Use Inngest for durable background processing.

**Why:**
- Runs on top of Vercel/Next.js — no separate infrastructure
- Provides durable execution: retries, delays, step functions
- Handles the async parts: email processing chains, scheduled carrier follow-ups, timeout checks
- Generous free tier
- Lighter weight than running Temporal or a Redis-based job queue

---

## 8. Frontend: React + Tailwind + shadcn/ui

**Decision:** Use shadcn/ui component library with Tailwind CSS.

**Why:**
- Production-quality components (tables, forms, modals, badges) without a full design system
- Tailwind keeps styling fast
- shadcn/ui components are copy-pasted into your codebase (not a dependency), so fully customizable

---

## 9. Hosting: Vercel + Supabase

**Decision:** Vercel for the Next.js app, Supabase for the database.

**Why:**
- Push to main = deployed. Zero config.
- Vercel provides a public URL immediately (needed for EmailEngine webhooks)
- One concern: Vercel serverless functions have timeout limits (10s hobby, 60s Pro). If agent chains exceed this, move orchestration to Railway ($5/mo) for long-running processes.

---

## What NOT to Build for MVP

- **Carrier matching AI** — broker picks carriers manually from a list for the trial. AI matching is Phase 2.
- **Negotiation automation** — out of scope. Broker handles negotiation.
- **Multi-tenant architecture** — one customer, one database, one deployment.
- **Custom domain email** — use Beltmann's existing mailbox.
- **Mobile app** — dashboard is desktop-only for MVP.

---

# Codex Recommendation

I agree with the overall direction, but not every specific decision.

The document is right about three important things:

- Do not build the email infrastructure layer from scratch.
- Keep the workflow state machine in your own application.
- Keep the MVP tightly scoped around one quoting workflow.

The place I disagree most is the email integration decision being treated as settled. `EmailEngine` is a reasonable option, but for a Microsoft-centric customer it should compete with direct `Microsoft Graph` integration rather than be assumed upfront. For the first customer, fewer moving parts matters more than architectural neatness. If Beltmann is already on Microsoft 365, direct Graph integration is likely the simpler and lower-risk path for the MVP.

I agree with rejecting `n8n` as the core workflow engine. It is fine for glue automation, but not as the system of record for a long-running quoting process with pauses, re-entry, approval gates, and confidence-based branching. That logic belongs in your app.

I would also avoid hard-wiring the architecture to one LLM vendor. Using one provider for the MVP is fine. Designing the system so the provider is swappable is the better technical decision.

My recommendation is:

- `Next.js` for UI and API routes
- `Postgres` as the source of truth for RFQs, email records, bids, and state transitions
- `Drizzle` for schema and database access
- `Microsoft Graph` first for mailbox integration if the customer is on Microsoft 365
- a custom TypeScript RFQ state machine in app code
- `ExcelJS` for quote sheet generation and spreadsheet parsing
- `Inngest` only if you need durable retries, scheduled follow-ups, or long-running async work in the first version

The key architectural rule should be this: email is only a channel. Your product's value is not "reading inboxes." It is converting messy transportation requests into structured RFQs, tracking state, drafting the next action, and helping brokers move the quote forward faster.

If you want the fastest credible MVP for Beltmann, build only this:

1. Read inbound quote emails from one mailbox.
2. Extract lane details, truck requirements, and missing fields.
3. Draft a follow-up email when required data is missing.
4. Generate a structured quote sheet.
5. Show the RFQ and its current state in a simple dashboard.

That is enough to demonstrate real value. Everything beyond that should be deferred unless the customer forces it into scope.
