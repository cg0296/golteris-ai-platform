# Golteris — Product User Experience

The product is not a collection of AI agents. The product is an **operating console for brokers** handling inbound quote requests, follow-up questions, and carrier coordination.

The user should feel one thing above all else: **control**.

---

## UX Thesis

The broker should be able to answer these four questions within 2 seconds:

1. **What needs my attention right now?**
2. **What happened since I last looked?**
3. **Which loads or RFQs are in motion?**
4. **What will happen next if I do nothing?**

If the interface cannot answer those questions quickly, it is failing.

---

## Product Principles

- **Human-controlled by default.** Nothing runs without the user enabling it. Nothing sends without approval.
- **Business-object first, agent second.** Organize around `RFQs`, `loads`, `messages`, and `decisions` — not around which agent is running.
- **Plain English everywhere.** No "extraction pipeline executed." Say *"Pulled 5 new quote requests from your inbox."*
- **Fast approvals, not deep navigation.** The broker should clear most HITL items in under 10 seconds.
- **Reversible actions and visible reasoning.** Nothing the system does should feel permanent or surprising.
- **Quiet by default, loud only when needed.** Don't create a second noisy inbox.

### The key mental model

The system uses agents internally. The broker should never have to think about that. They should experience:

- *"A load needs clarification."*
- *"A draft reply is ready."*
- *"Three carrier quotes arrived."*
- *"This RFQ is waiting on the customer."*

Not *"the extraction agent is running."*

---

## Primary Navigation

The MVP has five top-level areas:

- `Home` — Needs Review + Active RFQs + Recent Activity
- `Inbox` — inbound message routing status
- `RFQs` — full list of active and historical RFQs
- `History` — completed work and audit trail
- `Settings` — workflow toggles, mailbox controls, policies

Workflow on/off controls live in **Settings**, not on the home screen. Brokers should not live in a systems dashboard all day.

---

## Home Screen

The default home screen prioritizes **actionability over observability**.

### Layout

**Desktop** — three columns, all visible at once:

- **Left:** `Needs Review`
- **Center:** `Active RFQs`
- **Right:** `Recent Important Activity`

**Mobile** — the same three zones, stacked:

1. `Needs Review`
2. `Active RFQs`
3. `Recent Important Activity`

### Visual layout

```
┌────────────────────────────────────────────────────────────────┐
│ GOLTERIS   [Home] [Inbox] [RFQs] [History] [Settings]  Jillian │
├────────────────────────────────────────────────────────────────┤
│                                                                │
│  NEEDS REVIEW (3)  │  ACTIVE RFQs (12)       │  RECENT         │
│                    │                          │                │
│  ⚠ Approve reply   │  Load #4822              │  10:42          │
│    Acme Corp       │  Beltmann                │  Draft ready    │
│    Lane rates      │  Dallas → Atlanta        │  for Acme Corp  │
│    [Approve][Edit] │  Needs clarification     │                │
│                    │  Next: Send follow-up    │  10:35          │
│  ⚠ Missing equip   │                          │  Customer       │
│    Beltmann #4821  │  Load #4815              │  replied on     │
│    Send follow-up  │  Acme Corp               │  Load #4810     │
│    [Send][Edit]    │  Dallas → Atlanta        │                │
│                    │  Waiting on carriers     │  10:28          │
│  ⚠ Destination     │  Next: Nudge in 3h       │  Load #4822     │
│    unclear         │                          │  flagged        │
│    Load #4822      │  Load #4810              │                │
│    "ATL area"      │  Beltmann                │  10:18          │
│    [Confirm][Ask]  │  Quotes received         │  New RFQ        │
│                    │  Next: Broker review     │  from Beltmann  │
│                    │                          │                │
└────────────────────────────────────────────────────────────────┘
```

### Why this layout

This puts the highest-value work first — what needs approval, what loads are moving, what changed recently. It avoids making the product feel like a systems dashboard.

---

## Section 1 — Needs Review

The most important panel in the product. If this queue feels more burdensome than the old inbox, the product has failed. If the broker can clear it in 80% less time than the old way, the product has won.

This queue contains **only items that genuinely require human judgment**:

- Approve a drafted customer reply
- Confirm an ambiguous destination
- Resolve a message that could belong to multiple RFQs
- Approve sending a carrier quote request

### Card structure

Each card shows:

- **Action required** (headline verb)
- **Customer or load name**
- **Short reason**
- **Recommended action**
- **Buttons**

### Example card

```text
Approve customer follow-up
Beltmann • Load #4821
Missing equipment type and weight
Recommended: Send drafted clarification email

[Approve] [Edit] [Reject]
```

### UX rules

- Most items should be clearable in **under 10 seconds**.
- Do not show confidence percentages unless they are defensible and useful.
- Prefer short explanations like `Destination unclear: "ATL area"` over abstract scores.
- Inline buttons — no extra navigation to approve.

---

## Section 2 — Active RFQs

The operational center of the product. Instead of showing *"which agent is running,"* show **which RFQs are active and what stage they are in**. This is the single most important shift from a systems-dashboard mindset to a business-object mindset.

Each RFQ row shows:

- RFQ or load ID
- Customer name
- Route summary
- **Current state**
- Last update time
- **Next expected action**
- Risk flag if blocked

### RFQ states

- `Needs clarification`
- `Ready to quote`
- `Waiting on carriers`
- `Quotes received`
- `Waiting on broker review`
- `Quote sent`

### Example row

```text
Load #4822
Beltmann
Dallas, TX → Atlanta, GA
Needs clarification
Last updated 8 min ago
Next: Send customer follow-up
```

That is the language brokers think in. `Extraction Agent running` is not.

---

## Section 3 — Recent Important Activity

A **filtered event feed**, not a raw system log. Only meaningful, business-level events.

### Show

- New RFQ created
- Customer replied
- Follow-up draft prepared
- Carrier quote received
- RFQ moved to waiting state
- Broker approved a draft

### Hide (unless drilling into detail)

- Internal extraction steps
- Validation passes
- Queue routing
- Individual LLM calls

### Example feed

```text
10:42  ✍️  Draft reply prepared for Acme Corp
10:35  📥  Customer replied on Load #4810
10:28  ⚠️  Load #4822 flagged for destination clarification
10:22  ✅  You approved draft reply to Beltmann
10:18  🆕  New RFQ created from Beltmann email
```

Every item is clickable → opens the RFQ detail view for that load.

---

## RFQ Detail View

The **trust surface**. When a broker clicks into an RFQ, they see one coherent business record with four sections.

### 1. Summary

```text
Load #4815 — Beltmann
────────────────────────────────────────
Route:      Dallas, TX → Atlanta, GA
Equipment:  Flatbed × 3
Pickup:     April 10, 2026, 8am
Delivery:   April 11, 2026
Customer:   Tom (Beltmann Logistics)
Special:    Tarping required, weight TBD
```

### 2. Messages

The customer and carrier conversation attached to this RFQ. This is how the broker confirms the system **attached the right emails to the right work item**.

```text
📨 10:14  Beltmann → Golteris
   "Need a rate on 3 flatbeds Dallas to Atlanta next Tue..."

📤 10:22  Golteris → Beltmann (approved by Jillian)
   "Hi Tom, thanks for the request. To get you an accurate
    rate I need to confirm commodity, tarping, delivery..."

📨 10:31  Beltmann → Golteris
   "Steel coils, 45k lbs, tarped, delivery by noon Wed."

📤 10:35  Golteris → 12 carriers (approved by Jillian)
   "Flatbed load Dallas → Atlanta, 45k lbs steel coils..."
```

### 3. Current Status

```text
State:           Waiting on carriers
Why:             RFQ sent to 12 carriers at 10:35
Missing:         Nothing
Recommended:     Nudge carriers at 13:35 if no responses
```

### 4. Actions and History

```text
TIMELINE
10:14  📥  Email received from Beltmann
10:14  🆕  New RFQ created
10:15  ✅  Fields complete, ready to clarify commodity
10:15  ⏸  Paused — drafted follow-up for your review
10:22  ✅  You approved the follow-up
10:22  📤  Follow-up sent to Beltmann
10:31  📥  Customer reply received
10:32  ✅  All fields complete — ready to quote
10:32  ⏸  Paused — drafted carrier RFQ for your review
10:35  ✅  You approved the carrier RFQ
10:35  📤  RFQ sent to 12 carriers

[ View raw emails ]    [ View system reasoning ]
```

Lead with **what happened, why, and what the user can do**. Advanced debug details (raw prompts, token counts, extraction scores) live behind a disclosure — available if needed, invisible otherwise.

---

## HITL Approval Flow

The most frequent interaction in the product. It must be *fast*.

```
┌─ Approve Reply — Acme Corp, Load #4821 ───────────────────┐
│                                                            │
│  CUSTOMER SAID:                                            │
│  "Can you give me a rate on 3 flatbeds Dallas to Atlanta  │
│   for next Tuesday? Need them loaded by 8am."             │
│                                                            │
│  AGENT DRAFTED:                                            │
│  ┌────────────────────────────────────────────────────┐   │
│  │ Hi Tom,                                            │   │
│  │                                                    │   │
│  │ Thanks for the request. To get you an accurate    │   │
│  │ rate on the 3 flatbeds Dallas → Atlanta pickup    │   │
│  │ April 7, I need to confirm:                       │   │
│  │                                                    │   │
│  │ 1. Commodity and weight?                          │   │
│  │ 2. Any tarping required?                          │   │
│  │ 3. Delivery appointment time?                     │   │
│  │                                                    │   │
│  │ I'll have carriers lined up as soon as I hear     │   │
│  │ back.                                              │   │
│  │                                                    │   │
│  │ — Jillian                                          │   │
│  └────────────────────────────────────────────────────┘   │
│                                                            │
│  Why flagged: Missing commodity info                      │
│                                                            │
│  [ Send As-Is ]  [ Edit ]  [ Reject ]  [ Skip ]           │
└────────────────────────────────────────────────────────────┘
```

### Keyboard shortcuts

| Key | Action |
|---|---|
| `Enter` | Approve / Send As-Is |
| `E` | Edit |
| `R` | Reject |
| `S` | Skip (come back later) |
| `J` / `K` | Next / previous item |

A broker should be able to clear the queue without touching the mouse.

---

## Inbox View

The Inbox is not trying to replace Outlook. Its job is to show the **message-routing layer** — what came in and how it was handled.

Each message shows:

- Sender, subject, received time
- **Routing status**

### Routing statuses

- `Attached to RFQ #4815`
- `New RFQ created — #4822`
- `Needs review` — ambiguous routing
- `Ignored` — filtered out by rules

### Example list

```text
📨  10:31  Tom @ Beltmann       "Re: Dallas to Atlanta..."      → Attached to RFQ #4815
📨  10:18  Sarah @ Beltmann     "New project for next week"     → New RFQ created — #4822
📨  10:02  noreply@carrier.com  "Quote confirmation #88142"     → Attached to RFQ #4810
📨  09:47  unknown sender       "Pricing question"              → Needs review
📨  09:31  newsletter@dat.com   "Weekly market rates"           → Ignored
```

This helps the broker trust the routing layer without forcing them back into email.

---

## Settings and Workflow Controls

Workflow toggles still matter — but they live in a dedicated **Settings** area, not on the home screen.

### Settings contains

- **Mailbox connection status** — which inboxes are connected, health of each
- **Workflow toggles** — on/off per workflow (Inbound Quotes, Carrier Follow-ups, Claims Intake, etc.)
- **Approval policy** — what requires human review, what can auto-send, per workflow
- **Notification preferences** — digests, urgent pings, daily summary
- **Customer-specific rules** — per-customer overrides, SLAs, escalation paths
- **Scope controls** — what mailboxes, what senders, what actions agents are allowed to take

This is where the user answers:

- Is the system enabled?
- What is it allowed to send?
- What requires my approval?

Important, but not the daily workspace.

---

## Tone and Language

Use the language the broker already uses.

### Prefer

- `New quote request received`
- `Waiting on customer`
- `Draft ready to send`
- `3 carrier quotes received`
- `Load #4822 needs clarification`

### Avoid

- `Extraction pipeline complete`
- `Entity resolution failed`
- `Quote agent invoked`
- `Low-confidence inference score`
- `Workflow run 8f3a-... finished`

The UX should feel **operational, not technical**.

---

## Notification Strategy

Exception-driven. Don't create a second noisy inbox.

- **Immediate alerts** — urgent human action required (carrier quote arrived, customer waiting)
- **Periodic digests** — "3 items need your approval" during work hours, not constant pings
- **Daily summary** — end-of-day proof of value (see below)
- **Silent by default** — routine agent activity generates no notifications

---

## Daily Summary — The Proof Point

Every evening, the broker gets a summary (in-app, email, or Slack):

```
┌─ Golteris — Daily Summary for Jillian ────────────────────┐
│                                                            │
│  Today Golteris handled:                                   │
│                                                            │
│    📥  47 RFQs pulled from your inbox                     │
│    ✍️   23 replies drafted                                │
│    📤  12 carrier RFQs sent                               │
│    ⚠️   4 items flagged for your review                   │
│                                                            │
│  You approved 19 items in 14 minutes.                     │
│                                                            │
│  Time saved vs. manual handling: ~3h 40m                  │
│                                                            │
│  [ View full report → ]                                    │
└────────────────────────────────────────────────────────────┘
```

**This is what gets renewed.** Every day the product tells the broker how much time it saved them. The number speaks for itself.

---

## Mobile Experience

On a phone, the three home-screen zones stack:

1. **Needs Review** at the top (most actionable)
2. **Active RFQs** in the middle (what's in motion)
3. **Recent Important Activity** below (scrollable history)

`Inbox`, `RFQs`, `History`, and `Settings` live behind a bottom nav or hamburger.

The HITL approval flow is designed to work with one thumb — swipe right to approve, swipe left to reject, tap to edit.

---

## Demo MVP

For the Beltmann demo, build only these views:

1. **Home**
   - Needs Review
   - Active RFQs
   - Recent Important Activity

2. **RFQ Detail**
   - Summary
   - Message history
   - Current state
   - Actions and history

3. **Inbox**
   - Inbound messages
   - Routing statuses (attached / new / review / ignored)

4. **Approval Drawer**
   - Customer message
   - Drafted response
   - Reason for review
   - Approve / Edit / Reject

That is enough to tell a strong story. Everything else — Settings, daily summaries, keyboard shortcuts, notifications, mobile polish — is v2.

---

## The Story the UX Should Tell

The broker should walk away from the demo thinking:

> *"I don't have to babysit an AI system. I can see what came in, what happened to it, what needs me, and what is moving."*

That is the correct UX target for this product.

---

## The One-Line Pitch This Enables

> *"This is your inbox without the inbox. Turn it on, and you see every RFQ, every message, every decision — in plain English, with every action one click away. Nothing runs without your permission, nothing sends without your approval, and every minute it saves is on the screen."*

That's what Jillian buys.
