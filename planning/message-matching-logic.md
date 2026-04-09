# Message Matching Logic — Current System Documentation

Last updated: April 9, 2026

## Overview

When a new inbound email arrives, the system must decide:
1. Does this belong to an existing RFQ?
2. Is this from a carrier or a customer?
3. What action should be taken?

The matching service (`backend/services/message_matching.py`) runs as the first job in the pipeline after email ingestion.

---

## Matching Strategy (Priority Order)

### Strategy 0: RFQ Tag Match (Deterministic)
- **How:** Regex search for `[RFQ-{id}]` in the email subject
- **When it works:** All outbound emails include this tag. When someone replies, their email client preserves it in the "Re:" subject
- **Confidence:** 0.99
- **Skips terminal RFQs** (won/lost/cancelled)
- **Result:** Auto-attach to the tagged RFQ

### Strategy 1: Thread Match (Deterministic)
- **How:** Check `in_reply_to` header → find parent message → use its RFQ. Or check `thread_id` → find any message in that thread with an RFQ
- **When it works:** Direct replies to outbound emails where the email client sets proper headers
- **Confidence:** 0.99 (in_reply_to) or 0.97 (thread_id)
- **Known issue:** Our outbound messages don't always store `message_id_header`, so `in_reply_to` matching often fails
- **Result:** Auto-attach

### Strategy 2: Sender Match + Context Scoring
- **How:** Find all active (non-terminal) RFQs where `customer_email` matches the sender's email address
- **Base score:** 0.70 per candidate
- **Context scoring boosts** (additive):
  - Subject contains origin city: +0.10
  - Subject contains destination city: +0.10
  - Body mentions origin: +0.08
  - Body mentions destination: +0.08
  - Body mentions equipment type: +0.05
  - Body mentions commodity: +0.05
- **Max possible score:** 0.70 + 0.46 = 1.16

**Decision tree after scoring:**

| Condition | Action | Confidence |
|-----------|--------|------------|
| Best score >= 0.85 | Auto-attach | Score value |
| Single match + RFQ in `needs_clarification` | Auto-attach as clarification reply | 0.90 |
| Single match < 0.85, not clarification | Send to review queue | Score value |
| Multiple matches, none >= 0.85 | Send to review queue | Best score |

### Strategy 3: Carrier Match
- **How:** Look up sender email in `carriers` table → find `carrier_rfq_sends` record → get the RFQ
- **When it works:** Carrier replies to a distributed RFQ email
- **Confidence:** 0.95
- **Also enqueues** `parse_carrier_bid` job immediately
- **Result:** Auto-attach + bid parsing

### Strategy 4: No Match (New RFQ)
- **How:** None of the above strategies produced a match
- **Result:** Mark as `new_rfq`, enqueue `extraction` job
- **This triggers:** Intent classification → extraction (if RFQ) or inquiry response (if inquiry)

---

## Post-Match Actions (_apply_match)

After a message is attached to an RFQ, the system takes action based on the RFQ's current state:

| RFQ State | Action | Job Enqueued |
|-----------|--------|-------------|
| `inquiry` | — | (none currently) |
| `needs_clarification` | Re-extract with new info | `extraction` |
| `waiting_on_carriers` | Parse carrier bid | `parse_carrier_bid` |
| `quotes_received` | Parse carrier bid | `parse_carrier_bid` |
| `quote_sent` | Classify customer response | `quote_response` |
| Other states | Attach only, no action | — |

Broker emails (from `jillian@beltmann.com` or `agents@golteris.com`) are ignored for post-match actions.

---

## Intent Classification (New Messages Only)

For messages that don't match any existing RFQ (Strategy 4), the extraction agent runs an intent classification step before processing:

| Classification | Action |
|---------------|--------|
| `rfq` | Normal extraction pipeline → creates RFQ |
| `inquiry` | Creates lightweight RFQ in `inquiry` state, drafts answer, invites customer to book freight |

Classification uses an LLM tool-use call. Defaults to `rfq` if classification fails.

---

## Known Bugs / Gaps

### BUG: Sender match auto-attach is too aggressive
- **Scenario:** Customer has RFQ #53 in `needs_clarification`. They send a completely unrelated email with a new subject.
- **What happens:** Single sender match + `needs_clarification` state → auto-attach at 0.90 confidence
- **What should happen:** New subject without `[RFQ-NN]` tag should be treated as a new email, not a reply
- **Root cause:** Lines 142-161 — the clarification reply shortcut doesn't check if the subject looks like a reply

### GAP: No subject comparison for clarification replies
- The clarification shortcut (single sender + needs_clarification) should verify the subject matches (contains "Re:" or `[RFQ-NN]` tag)

### GAP: Inquiry state not handled in post-match
- When a message is matched to an RFQ in `inquiry` state, no action is taken
- Should trigger re-extraction like `needs_clarification` does

### GAP: Same sender, multiple active RFQs + new request
- If a customer has 2 active RFQs and sends a third unrelated email, it goes to the review queue
- This is correct behavior but could be improved — if the subject/content clearly doesn't match either existing RFQ, it should create a new one

### GAP: Out-of-office / read receipts
- Auto-replies like "I'm out of office" get processed as RFQs or matched to existing ones
- Should be detected and ignored

### GAP: Carrier match requires carriers table entry
- If a carrier replies but isn't in the carriers table, they won't match via Strategy 3
- Falls through to sender match, which checks customer_email (wrong field for carriers)
- Result: carrier reply creates a new RFQ instead of being parsed as a bid

---

## Constants

| Constant | Value | Purpose |
|----------|-------|---------|
| `AUTO_ATTACH_THRESHOLD` | 0.85 | Minimum score for auto-attach |
| `REVIEW_THRESHOLD` | 0.30 | Below this, treat as new RFQ (not currently enforced) |
| `TERMINAL_STATES` | won, lost, cancelled | Don't match messages to closed RFQs |

---

## Flow Diagram

```
Inbound Email
      │
      ▼
[RFQ tag in subject?] ──yes──► Auto-attach to tagged RFQ
      │ no
      ▼
[Thread/reply headers?] ──yes──► Auto-attach to parent RFQ
      │ no
      ▼
[Sender matches active RFQ?]
      │ yes                          │ no
      ▼                              ▼
[Context score >= 0.85?]    [Sender is known carrier?]
   │ yes    │ no                │ yes      │ no
   ▼        ▼                   ▼          ▼
Auto-    [Single match +      Attach +   NEW RFQ
attach    needs_clarif?]      parse bid   (extraction)
         │ yes    │ no
         ▼        ▼
      Auto-    Review
      attach   queue
```
