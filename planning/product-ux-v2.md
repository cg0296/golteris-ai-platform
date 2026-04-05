# Golteris Product UX v2

The product is not a collection of AI agents. The product is an operating console for brokers handling inbound quote requests, follow-up questions, and carrier coordination.

The user should feel one thing above all else: control.

---

## UX Thesis

The broker should be able to answer these four questions within 2 seconds:

1. What needs my attention right now?
2. What happened since I last looked?
3. Which loads or RFQs are in motion?
4. What will happen next if I do nothing?

If the interface cannot answer those questions quickly, it is failing.

---

## Product Principles

- Human-controlled by default.
- Business-object first, agent second.
- Plain English everywhere.
- Fast approvals, not deep navigation.
- Reversible actions and visible reasoning.
- Quiet by default, loud only when needed.

The key shift from v1 is this:

Do not organize the product around agents.
Organize it around `RFQs`, `loads`, `messages`, and `decisions`.

The system can use agents internally, but the broker should experience:

- a load needs clarification
- a draft reply is ready
- three carrier quotes arrived
- this RFQ is waiting on the customer

That is the right mental model.

---

## Primary Navigation

The MVP should have five top-level areas:

- `Inbox`
- `Needs Review`
- `RFQs`
- `History`
- `Settings`

This is simpler than exposing workflows as the primary operating surface.

`Settings` can contain workflow toggles and mailbox controls. Brokers should not live there all day.

---

## Home Screen

The default home screen should prioritize actionability over observability.

### Layout

Desktop:

- Left: `Needs Review`
- Center: `Active RFQs`
- Right: `Recent Important Activity`

Mobile:

1. `Needs Review`
2. `Active RFQs`
3. `Recent Important Activity`

### Why this layout

This puts the highest-value work first:

- what needs approval
- what loads are moving
- what changed recently

It avoids making the product feel like a systems dashboard.

---

## Section 1: Needs Review

This is the most important panel in the product.

This queue should contain only items that genuinely require human judgment, such as:

- approve a drafted customer reply
- confirm an ambiguous destination
- resolve a message that could belong to multiple RFQs
- approve sending a carrier quote request

Each item should be clear, compact, and fast to resolve.

### Good card structure

- action required
- customer or load name
- short reason
- recommended action
- buttons

Example:

```text
Approve customer follow-up
Beltmann • Load #4821
Missing equipment type and weight
Recommended: Send drafted clarification email

[Approve] [Edit] [Reject]
```

### UX rules

- Most items should be clearable in under 10 seconds.
- Do not show confidence percentages unless they are defensible and useful.
- Prefer short explanations like `Destination unclear: "ATL area"` over abstract scores.

---

## Section 2: Active RFQs

This is the operational center of the product.

Instead of showing “which agent is running,” show which RFQs are active and what stage they are in.

Each RFQ row should include:

- RFQ or load ID
- customer name
- route summary
- current state
- last update time
- next expected action
- risk flag if blocked

Example states:

- `Needs clarification`
- `Ready to quote`
- `Waiting on carriers`
- `Quotes received`
- `Waiting on broker review`
- `Quote sent`

Example row:

```text
Load #4822
Beltmann
Dallas, TX → Atlanta, GA
Needs clarification
Last updated 8 min ago
Next: Send customer follow-up
```

This is much better than showing `Extraction Agent running`.

The broker cares about business progress, not internal execution machinery.

---

## Section 3: Recent Important Activity

This should be a filtered event feed, not a raw system log.

Only show meaningful events such as:

- new RFQ created
- customer replied
- follow-up draft prepared
- carrier quote received
- RFQ moved to waiting state
- broker approved a draft

Avoid noise like internal extraction steps unless the user drills into detail.

Good examples:

```text
10:42 Draft reply prepared for Acme Corp
10:35 Customer replied on Load #4810
10:28 Load #4822 flagged for destination clarification
10:18 New RFQ created from Beltmann email
```

Each item should open the RFQ detail or activity detail view.

---

## RFQ Detail View

This is the trust surface.

When a broker clicks into an RFQ, they should see one coherent business record with four sections:

1. `Summary`
2. `Messages`
3. `Current Status`
4. `Actions and History`

### Summary

Show:

- route
- equipment
- truck count
- dates
- customer
- important requirements

### Messages

Show the customer and carrier conversation attached to this RFQ.

This matters because the broker needs confidence that the system attached the right emails to the right work item.

### Current Status

Show:

- current RFQ state
- why it is in that state
- what is missing, if anything
- what the system recommends next

### Actions and History

Show:

- drafted replies
- approvals
- sent messages
- state transitions
- manual overrides

This is where deeper system reasoning can live.

Avoid defaulting to raw prompt details. Lead with:

- what happened
- why it happened
- what the user can do

Advanced debug details can sit behind a secondary disclosure.

---

## Inbox View

The inbox should not try to replace Outlook completely.

Its job is to show:

- newly ingested messages
- whether each message was attached to an RFQ
- whether human review is needed

Useful statuses:

- `Attached to RFQ #104`
- `New RFQ created`
- `Needs review`
- `Ignored`

This helps the user trust the message-routing layer without forcing them back into email constantly.

---

## Settings and Workflow Controls

Workflow toggles still matter, but they should live in a dedicated settings/admin surface, not dominate the home screen.

This area should include:

- mailbox connection status
- workflow on/off toggles
- approval policy
- notification preferences
- customer-specific rules

This is where a user answers:

- is the system enabled
- what is it allowed to send
- what requires approval

That is important, but it is not the main daily workspace.

---

## Tone and Language

Use language the broker already uses.

Prefer:

- `New quote request received`
- `Waiting on customer`
- `Draft ready to send`
- `3 carrier quotes received`

Avoid:

- `Extraction pipeline complete`
- `Entity resolution failed`
- `Quote agent invoked`
- `Low-confidence inference score`

The UX should make the product feel operational, not technical.

---

## Notification Strategy

Notifications should be exception-driven.

Use:

- immediate alerts for urgent human action
- periodic digests for normal review items
- daily summary for proof of value

Do not notify on every background event.

The interface should reduce interruption, not create a second noisy inbox.

---

## Demo MVP

For the Beltmann demo, build only these views:

1. `Home`
   - Needs Review
   - Active RFQs
   - Recent Important Activity

2. `RFQ Detail`
   - summary
   - message history
   - current state
   - draft/review actions

3. `Inbox`
   - inbound messages
   - attached/new/review statuses

4. `Approval Drawer or Modal`
   - customer message
   - drafted response
   - reason for review
   - approve/edit/reject

That is enough to tell a strong story.

---

## The Story the UX Should Tell

The user should walk away thinking:

`I do not have to babysit an AI system. I can see what came in, what happened to it, what needs me, and what is moving.`

That is the correct UX target for this product.
