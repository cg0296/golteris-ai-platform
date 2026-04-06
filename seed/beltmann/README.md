# Beltmann Seed Dataset

Realistic freight quote emails and carrier responses based on patterns from the Beltmann Logistics meeting recap. This dataset is the primary test fixture for all Phase 2 agents (REQUIREMENTS.md §3.5).

## Shipper Emails (12 files)

| # | File | Scenario | Tests | Expected State |
|---|---|---|---|---|
| 01 | `01_happy_path_single_flatbed.json` | Complete info, single truck, clean format | extraction, quote_sheet | ready_to_quote |
| 02 | `02_multi_truck_project.json` | 5 trucks, 2 lanes, complex requirements | extraction, multi_lane | ready_to_quote |
| 03 | `03_missing_commodity_weight.json` | No commodity, no weight | extraction, validation, missing_info | needs_clarification |
| 04 | `04_missing_dates.json` | No pickup/delivery dates | extraction, validation, missing_info | needs_clarification |
| 05 | `05_ambiguous_destination.json` | "Springfield" — no state specified | extraction, confidence, HITL | needs_clarification |
| 06 | `06_special_requirements_heavy.json` | Lift gate, driver unload, inside delivery | extraction, special_requirements | ready_to_quote |
| 07 | `07_thread_reply_followup.json` | Reply to #03 with missing info | matching, thread_matching | ready_to_quote |
| 08 | `08_noise_not_rfq.json` | Newsletter — not an RFQ | matching, noise_filtering | ignored |
| 09 | `09_messy_freeform.json` | Casual prose, no structure | extraction, messy_formatting | ready_to_quote |
| 10 | `10_mixed_equipment_types.json` | Flatbed + van in one request | extraction, multi_equipment | ready_to_quote |
| 11 | `11_urgent_time_sensitive.json` | Same-day request, premium willingness | extraction, urgency | ready_to_quote |
| 12 | `12_insurance_requirements.json` | $2.4M aerospace, $5M insurance min | extraction, special_requirements | ready_to_quote |

## Carrier Responses (8 files)

| # | File | Scenario | Responds To | Rate Type |
|---|---|---|---|---|
| 01 | `01_clean_all_in_rate.json` | Clean all-in rate | shipper #01 | all_in ($2,850) |
| 02 | `02_linehaul_plus_fsc.json` | Linehaul + FSC + tarping breakdown | shipper #01 | linehaul_plus_fsc ($2,907) |
| 03 | `03_per_mile_pricing.json` | Per-mile rate ($3.65/mi) | shipper #01 | per_mile (~$2,851) |
| 04 | `04_partial_availability.json` | Can do 2 of 3 trucks | shipper #09 | all_in ($1,950/truck) |
| 05 | `05_decline_with_reason.json` | Decline — insurance insufficient | shipper #12 | declined |
| 06 | `06_counter_offer.json` | Modified terms, two options | shipper #06 | all_in ($1,650 or $2,000) |
| 07 | `07_ambiguous_messy.json` | Rate buried in casual text | shipper #11 | all_in ($3,200) |
| 08 | `08_multi_lane_response.json` | Both lanes + volume discount | shipper #02 | all_in ($10,350 / $9,832.50) |

## Demo Hero Moments

This dataset supports the key demo scenarios from REQUIREMENTS.md §8:

1. **Email arrives, RFQ appears** — emails 01, 09, 11 (varying formats, all extractable)
2. **Missing info detected, clarification drafted** — emails 03, 04, 05 (different missing fields)
3. **Follow-up completes the RFQ** — email 07 (reply to 03, transitions to ready_to_quote)
4. **Noise filtered out** — email 08 (newsletter ignored, no RFQ created)
5. **Complex project handled** — email 02 (multi-truck, multi-lane)
6. **Carrier bids compared** — responses 01-03 all bid on the same RFQ with different rate structures
7. **Edge cases surface gracefully** — email 05 (ambiguous destination), email 10 (mixed equipment)

## JSON Schema

Each shipper email file contains:

```json
{
  "scenario": "Human-readable description",
  "tests": ["which agents/features this tests"],
  "expected_state": "the RFQ state after processing",
  "sender": "email address",
  "recipients": "email address",
  "subject": "email subject line",
  "body": "full email body text",
  "thread_id": "for reply matching (null if new thread)",
  "in_reply_to": "Message-ID of parent (null if new)",
  "message_id_header": "unique Message-ID for this email",
  "expected_extraction": { "field": "expected value" },
  "expected_confidence": { "field": 0.0-1.0 }
}
```

Each carrier response file adds:

```json
{
  "responds_to": "which shipper email this is a bid for",
  "expected_bid": {
    "carrier_name": "...",
    "rate": 0.00,
    "rate_type": "all_in | linehaul_plus_fsc | per_mile",
    "terms": "...",
    "availability": "confirmed | partial | unavailable"
  }
}
```

## Usage

Agents reference these files in their test suites:

```python
import json
from pathlib import Path

SEED_DIR = Path("seed/beltmann/shipper_emails")

def load_seed_email(filename: str) -> dict:
    return json.loads((SEED_DIR / filename).read_text())
```
