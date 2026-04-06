# Request Lifecycle — How an RFQ Flows Through Golteris

This document traces the complete lifecycle of a freight quote request from the moment a customer email arrives to the moment the RFQ is closed as won/lost/cancelled.

---

## Database Tables

```
┌─────────────┐     ┌─────────────┐     ┌──────────────┐
│  workflows   │     │    rfqs      │     │   messages    │
├─────────────┤     ├─────────────┤     ├──────────────┤
│ id           │     │ id           │◄────│ rfq_id        │
│ name         │     │ customer_*   │     │ direction     │
│ enabled ◄────────── │ origin       │     │ sender        │
│ config       │  C1 │ destination  │     │ subject       │
│ created_at   │     │ equipment    │     │ body          │
│ updated_at   │     │ truck_count  │     │ thread_id     │
└─────────────┘     │ commodity    │     │ routing_status│
                     │ weight_lbs   │     │ received_at   │
                     │ state ●──────────── └──────────────┘
                     │ confidence   │
                     │ outcome      │     ┌──────────────┐
                     │ quoted_amount│     │  approvals    │
                     │ created_at   │     ├──────────────┤
                     │ updated_at   │◄────│ rfq_id        │
                     └──────┬───────┘     │ approval_type │
                            │             │ draft_body    │
              ┌─────────────┼──────┐      │ status ●──── C2
              │             │      │      │ resolved_body │
              ▼             ▼      ▼      │ resolved_by   │
     ┌──────────────┐ ┌────────┐ ┌───────└──────────────┘
     │ audit_events  │ │ agent  │ │
     ├──────────────┤ │ _runs  │ │ ┌──────────────┐
     │ rfq_id        │ ├────────┤ │ │ carrier_bids  │
     │ event_type    │ │ rfq_id  │ │ ├──────────────┤
     │ actor         │ │ workflow│ └─│ rfq_id        │
     │ description   │ │ status  │   │ carrier_name  │
     │ event_data    │ │ cost    │   │ rate          │
     │ created_at    │ │ tokens  │   │ raw_response  │
     └──────────────┘ └───┬────┘   └──────────────┘
               C4         │
                          ▼         ┌──────────────┐
                    ┌──────────┐    │ review_queue  │
                    │ agent    │    ├──────────────┤
                    │ _calls   │    │ message_id    │
                    ├──────────┤    │ candidates    │
                    │ run_id    │    │ reason        │
                    │ agent_name│    │ status        │
                    │ provider  │    │ resolved_rfq  │
                    │ model     │    └──────────────┘
                    │ prompts   │
                    │ tokens    │
                    │ cost_usd  │
                    │ duration  │
                    └──────────┘
                         C5
```

---

## API Endpoints

```
System
  GET  /health                          → {"status": "ok"}
  GET  /api                             → version info
  GET  /docs                            → Swagger UI

RFQs
  GET  /api/rfqs/active                 → active RFQs (Home screen center column)
  GET  /api/rfqs?state=X&search=Y       → paginated list with filters (RFQs tab)
  GET  /api/rfqs/:id                    → full RFQ + messages + timeline (detail drawer)

Approvals (HITL)
  GET  /api/approvals/pending           → Needs Review queue (Home screen left column)
  GET  /api/approvals/:id               → single approval with draft
  POST /api/approvals/:id/approve       → send as-is
  POST /api/approvals/:id/edit          → send edited version
  POST /api/approvals/:id/reject        → reject draft

Activity
  GET  /api/activity/recent             → last 20 business events (Home screen right column)

Messages / Inbox
  GET  /api/messages                    → all messages with routing badges

History
  GET  /api/history                     → closed RFQs + stats (time saved, avg cycle time)

Settings
  GET  /api/workflows                   → all workflows with on/off status
  PUT  /api/workflows/:id               → toggle workflow
  POST /api/workflows/kill              → kill switch — disable everything

Agent Observability
  GET  /api/agent/calls                 → paginated LLM call log
  GET  /api/agent/runs                  → paginated workflow runs
  GET  /api/agent/tasks                 → live task queue
```

---

## Lifecycle of a Request

### Step 1 — Email Arrives

Tom at Beltmann sends an email:
> *"Need a rate on 3 flatbeds Dallas to Atlanta next Tuesday. Steel coils, 45k lbs, tarped."*

```
                    ┌──────────────┐
    Tom's email ──► │   WORKER     │  (polls every 10s)
                    │              │
                    │  1. Check:   │
                    │     workflows│──► workflows.enabled = true?
                    │     .enabled │    If no → skip, idle
                    │              │
                    │  2. Read     │
                    │     mailbox  │──► seeded folder (demo) or Gmail (prod)
                    │              │
                    │  3. Write    │
                    │     message  │──► INSERT INTO messages (direction='inbound',
                    │              │      sender='tom@beltmann.com', body=...,
                    │              │      routing_status=NULL)
                    └──────┬───────┘
                           │
                           ▼
```

**Database after Step 1:**
- `messages` — 1 new row, `rfq_id=NULL`, `routing_status=NULL`
- `audit_events` — "New email received from tom@beltmann.com"

---

### Step 2 — Matching

The worker runs the **Matching Agent** to figure out: is this a reply to an existing RFQ, or a new one?

```
    message ──► MATCHING AGENT
                    │
                    ├─ Check thread_id / in_reply_to headers
                    │   Match found? → attach to existing RFQ
                    │
                    ├─ No header match → score against active RFQs
                    │   (sender, company, route similarity)
                    │   High confidence? → attach
                    │
                    ├─ Ambiguous? → review_queue (human decides)
                    │   routing_status = 'needs_review'
                    │
                    └─ No match at all? → CREATE NEW RFQ
                        routing_status = 'new_rfq'
```

For Tom's email — it's new, no thread history. A new RFQ is created.

**Database after Step 2:**
- `rfqs` — 1 new row, `state='needs_clarification'`, fields all NULL (not extracted yet)
- `messages` — updated: `rfq_id=42`, `routing_status='new_rfq'`
- `audit_events` — "New RFQ #42 created from Beltmann email"

---

### Step 3 — Extraction

The worker runs the **Extraction Agent** — calls the LLM with tool-use to pull structured fields.

```
    message.body ──► LLM (tool-use call)
                         │
                         │  System: "Extract freight RFQ fields..."
                         │  User: "Need a rate on 3 flatbeds Dallas to Atlanta..."
                         │  Tool: extract_rfq schema
                         │
                         ▼
                    {
                      "origin": "Dallas, TX",           confidence: 0.95
                      "destination": "Atlanta, GA",      confidence: 0.93
                      "equipment_type": "Flatbed",       confidence: 0.97
                      "truck_count": 3,                  confidence: 0.99
                      "commodity": "Steel coils",        confidence: 0.91
                      "weight_lbs": 45000,               confidence: 0.94
                      "special_requirements": "Tarped",  confidence: 0.88
                      "pickup_date": "2026-04-07",       confidence: 0.85
                    }
```

**Database after Step 3:**
- `rfqs` — updated with all extracted fields + `confidence_scores` JSONB
- `agent_runs` — 1 row: `workflow_name='extraction'`, `status='completed'`, `duration_ms=1200`
- `agent_calls` — 1 row: full prompt, response, `provider='anthropic'`, `model='claude-sonnet-4-6'`, `input_tokens=850`, `output_tokens=320`, `cost_usd=0.004`
- `audit_events` — "Fields extracted from Beltmann email — origin: Dallas, TX → destination: Atlanta, GA"

---

### Step 4 — Validation

The worker runs the **Validation Agent** — checks if all required fields are present and confident.

```
    RFQ fields ──► VALIDATION
                       │
                       ├─ origin? ✓ (0.95 > 0.90 threshold)
                       ├─ destination? ✓
                       ├─ equipment? ✓
                       ├─ truck_count? ✓
                       ├─ commodity? ✓
                       ├─ weight? ✓
                       ├─ pickup_date? ✓ (but 0.85 < 0.90 — LOW CONFIDENCE)
                       │
                       └─► Missing/low-confidence: pickup_date
                           → state = 'needs_clarification'
                           → DRAFT A FOLLOW-UP EMAIL
```

In this case, Tom's email says "next Tuesday" — the extraction guessed April 7 but confidence is only 0.85. The validation agent drafts a clarification.

**Database after Step 4:**
- `rfqs` — `state='needs_clarification'`
- `approvals` — 1 new row:
  ```
  approval_type = 'customer_reply'
  draft_body = "Hi Tom, thanks for the request. To confirm — pickup
                is Tuesday April 7? Also need delivery appointment
                time. — Jillian"
  status = 'pending_approval'    ◄── C2: NOTHING SENDS UNTIL HUMAN APPROVES
  reason = "Low confidence on pickup date (0.85)"
  ```
- `audit_events` — "Draft follow-up prepared for Tom @ Beltmann — confirming pickup date"

---

### Step 5 — Human Approval (HITL)

Jillian opens the dashboard. The Home screen shows:

```
┌─ NEEDS REVIEW (1) ──────┬─ ACTIVE RFQs (1) ────────┬─ RECENT ──────────┐
│                          │                           │                    │
│  ⚠ Confirm pickup date  │  Load #42                 │  10:15             │
│    Beltmann              │  Beltmann                 │  Draft ready       │
│    Low confidence: 0.85  │  Dallas → Atlanta         │  for Beltmann      │
│    [Approve] [Edit]      │  Needs clarification      │                    │
│                          │  Next: Send follow-up     │  10:14             │
│                          │                           │  New RFQ from      │
│                          │                           │  Beltmann          │
└──────────────────────────┴───────────────────────────┴────────────────────┘
```

She clicks **Approve** (or hits `Enter`).

```
    Jillian hits Enter ──► POST /api/approvals/42/approve
                               │
                               ├─ approvals.status = 'approved'
                               ├─ approvals.resolved_by = 'jillian'
                               ├─ approvals.resolved_at = NOW()
                               │
                               └─► WORKER picks up approved item
                                   → Sends email via Gmail API / SMTP
                                   → INSERT INTO messages (direction='outbound')
                                   → audit_events: "Jillian approved follow-up to Tom"
                                   → audit_events: "Follow-up sent to Tom @ Beltmann"
                                   → rfqs.state = 'needs_clarification' (still waiting)
```

**Database after Step 5:**
- `approvals` — `status='approved'`, `resolved_by='jillian'`
- `messages` — new outbound row linked to RFQ #42
- `audit_events` — 2 new rows (approval + send)

---

### Step 6 — Customer Replies

Tom replies: *"Yes April 7, delivery by noon Wednesday."*

The worker picks this up → **Matching Agent** attaches via thread_id → **Extraction Agent** updates the RFQ with the confirmed date and delivery time → **Validation Agent** finds all fields complete → `state = 'ready_to_quote'`.

```
    rfqs.state: needs_clarification → ready_to_quote
```

---

### Step 7 — Carrier Distribution (Phase 9)

The system drafts carrier RFQ emails → creates `approvals` rows → Jillian approves → emails sent to 12 carriers → `state = 'waiting_on_carriers'`.

---

### Step 8 — Carrier Quotes Come Back

Carriers reply with pricing → **Carrier Response Parser** creates `carrier_bids` rows → `state = 'quotes_received'` → **Bid Comparison** ranks them → creates an approval for Jillian to review the top pick.

---

### Step 9 — Final Quote

Jillian picks the best carrier → **Pricing Engine** applies markup → **Customer Quote** generates the branded quote → approval → send → `state = 'quote_sent'`.

---

### Step 10 — Outcome

Tom accepts → Jillian marks it `won`. The RFQ is closed:
- `rfqs.outcome = 'won'`
- `rfqs.quoted_amount = 4500.00`
- `rfqs.closed_at = NOW()`
- Shows up in the History tab with cycle time and time-saved stats

---

## RFQ State Flow

```
    ┌───────────────────┐
    │ needs_clarification│◄──── missing fields or low confidence
    └────────┬──────────┘
             │ all fields complete
             ▼
    ┌───────────────────┐
    │  ready_to_quote    │
    └────────┬──────────┘
             │ carrier RFQs sent (after approval)
             ▼
    ┌───────────────────┐
    │waiting_on_carriers │
    └────────┬──────────┘
             │ at least one bid received
             ▼
    ┌───────────────────┐
    │  quotes_received   │
    └────────┬──────────┘
             │ broker reviews bids
             ▼
    ┌───────────────────┐
    │waiting_on_broker   │
    └────────┬──────────┘
             │ final quote sent to customer (after approval)
             ▼
    ┌───────────────────┐
    │    quote_sent       │
    └────────┬──────────┘
             │ customer responds
             ▼
    ┌────┬────┬──────────┐
    │ won│lost│cancelled  │
    └────┴────┴──────────┘
```

---

## Constraint Enforcement Points

| Constraint | Where it's enforced | What happens |
|---|---|---|
| **C1 — Kill switch** | `worker.py` checks `workflows.enabled` every loop | Worker idles if disabled |
| **C2 — HITL gate** | `approvals.status` checked before every outbound send | Nothing leaves without `approved` |
| **C4 — Traceability** | `audit_events` on every action, `agent_calls` on every LLM call | Full timeline in RFQ detail |
| **C5 — Cost caps** | Provider abstraction layer checks daily total before each LLM call | Hard stop at $20/day |
