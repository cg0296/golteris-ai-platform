#!/bin/bash
# Creates 100 GitHub test issues from stress_test_100.py scenarios.
# Each issue has scope + acceptance criteria. Run once.

set -e

create_issue() {
  local num=$1
  local category=$2
  local title=$3
  local what=$4
  local criteria=$5
  local labels=$6

  body=$(cat <<EOF
## Scope
$what

## Acceptance Criteria
$criteria

## How to Run
\`\`\`bash
python scripts/stress_test_100.py -s $num
\`\`\`

## Category
\`$category\` — Scenario #$num of 100 in the stress test suite.
EOF
)

  gh issue create \
    --title "Test #$(printf '%03d' $num): $title" \
    --body "$body" \
    --label "$labels" \
    >/dev/null && echo "  ✓ #$num: $title"
}

L_EMAIL="testing,email"
L_MATCH="testing,matching"
L_EXTRACT="testing"
L_API="testing"
L_STATE="testing,state-machine"
L_BIDS="testing"
L_QR="testing"
L_SYS="testing"

echo "Creating 100 test issues..."

# ─── EMAIL INGESTION (1-15) ───
create_issue 1 "email" "Normal RFQ with all fields" \
  "Inject a well-formed RFQ email with origin, destination, equipment, truck count, weight, pickup, delivery. Verify complete extraction." \
  "- [ ] RFQ created with state ready_to_quote or needs_clarification
- [ ] All 7 fields extracted with confidence > 0.8
- [ ] ref_number generated in YYYYMMDD-HHMM-NNN format" "$L_EMAIL"

create_issue 2 "email" "Minimal email — origin and destination only" \
  "Inject email containing only origin and destination. Verify system detects missing fields and triggers clarification flow." \
  "- [ ] RFQ created in needs_clarification state
- [ ] Validation agent generates follow-up email
- [ ] Missing fields list includes equipment, truck_count, weight, commodity" "$L_EMAIL"

create_issue 3 "email" "Empty email body" \
  "Inject email with empty body. Should not crash; should either ignore or create low-confidence inquiry." \
  "- [ ] System does not crash
- [ ] Either ignores or creates RFQ in inquiry state
- [ ] No spurious extraction" "$L_EMAIL"

create_issue 4 "email" "Email with only signature" \
  "Inject email where body is only 'Sent from my iPhone' + signature. Body cleaning should strip this." \
  "- [ ] _clean_email_body strips signature
- [ ] No RFQ extracted from noise
- [ ] Classified as inquiry or ignored" "$L_EMAIL"

create_issue 5 "email" "Email in Spanish" \
  "Inject non-English RFQ. Extraction should handle multilingual input." \
  "- [ ] No crash
- [ ] Either extracts fields or flags as inquiry
- [ ] Does not create garbage RFQ" "$L_EMAIL"

create_issue 6 "email" "Email with HTML tags" \
  "Inject email body containing HTML (b, i, table, br). Body cleaning should handle HTML gracefully." \
  "- [ ] HTML tags stripped or ignored
- [ ] Extraction succeeds on content
- [ ] No HTML artifacts in stored RFQ fields" "$L_EMAIL"

create_issue 7 "email" "Very long email (2000+ words)" \
  "Inject email with repeated filler to test token limits and extraction focus." \
  "- [ ] Processes without exceeding LLM context limit
- [ ] Cost tracked correctly in agent_calls
- [ ] Extraction finds key fields despite noise" "$L_EMAIL"

create_issue 8 "email" "Special characters and emojis" \
  "Inject email with Unicode, accented characters, and emojis in sender, subject, body." \
  "- [ ] No Unicode encoding errors
- [ ] Stored as-is in database
- [ ] Display correctly in UI" "$L_EMAIL"

create_issue 9 "email" "Auto-reply should be ignored" \
  "Inject email with 'Automatic Reply: Out of Office' subject. Must be filtered before matching." \
  "- [ ] No RFQ created
- [ ] message_ignored audit event logged
- [ ] routing_status = ignored" "$L_EMAIL"

create_issue 10 "email" "Bounce/undeliverable ignored" \
  "Inject Microsoft Exchange undeliverable bounce. Must be filtered." \
  "- [ ] No RFQ created
- [ ] Recognized as auto-reply
- [ ] routing_status = ignored" "$L_EMAIL"

create_issue 11 "email" "Multi-lane request (3 routes)" \
  "Inject email listing 3 separate lanes. System currently creates 1 RFQ — verify behavior or trigger split." \
  "- [ ] Does not crash
- [ ] Extracts primary lane OR flags as multi-lane
- [ ] Additional lanes captured in special_requirements if not split" "$L_EMAIL"

create_issue 12 "email" "General inquiry (not an RFQ)" \
  "Inject a question email with no shipment intent. Intent classifier should route to inquiry." \
  "- [ ] Intent classified as inquiry, not rfq
- [ ] State set to inquiry
- [ ] Follow-up email drafted (not extraction)" "$L_EMAIL"

create_issue 13 "email" "Email with past pickup date" \
  "Inject email with pickup date in 2020. System should flag or correct impossible dates." \
  "- [ ] No crash
- [ ] Date stored or flagged
- [ ] needs_clarification if dates are nonsensical" "$L_EMAIL"

create_issue 14 "email" "Swapped dates (delivery before pickup)" \
  "Inject email where delivery_date < pickup_date. Extraction has auto-swap logic (#155)." \
  "- [ ] Dates auto-swapped OR flagged for review
- [ ] Final pickup_date <= delivery_date
- [ ] Quote sheet still generates" "$L_EMAIL"

create_issue 15 "email" "Extreme weight (999M lbs)" \
  "Inject email with absurd weight value. Should not crash integer fields." \
  "- [ ] No database overflow error
- [ ] Weight stored or flagged
- [ ] needs_clarification if value is implausible" "$L_EMAIL"

# ─── MESSAGE MATCHING (16-30) ───
create_issue 16 "matching" "Reply with [RFQ-ref] tag matches" \
  "Reply with smart ref_number tag in subject. Should match via Strategy 0 (rfq_tag)." \
  "- [ ] Message attaches to correct RFQ
- [ ] Match method = rfq_tag
- [ ] Confidence = 0.99" "$L_MATCH"

create_issue 17 "matching" "Same sender new subject creates new RFQ" \
  "Same customer email, completely different route, new subject. Should NOT attach to old RFQ (#180)." \
  "- [ ] New RFQ created, not attached
- [ ] Second RFQ has different origin/destination
- [ ] Both visible in RFQ list" "$L_MATCH"

create_issue 18 "matching" "Reply from same sender attaches" \
  "Same sender + Re: subject + matching content should attach via sender + context scoring." \
  "- [ ] Message attaches to existing RFQ
- [ ] Context score >= 0.85
- [ ] Method = sender or thread" "$L_MATCH"

create_issue 19 "matching" "Known carrier reply routes to bid parser" \
  "Reply from email matching carriers table should route to parse_carrier_bid." \
  "- [ ] Matched via carrier strategy
- [ ] parse_carrier_bid job enqueued
- [ ] RFQ transitions to quotes_received" "$L_MATCH"

create_issue 20 "matching" "Unknown sender creates new RFQ" \
  "Novel sender with no history. Should fall through to Strategy 4 (new RFQ)." \
  "- [ ] New RFQ created
- [ ] Extraction job enqueued
- [ ] routing_status = new_rfq_created" "$L_MATCH"

create_issue 21 "matching" "Read receipt ignored" \
  "Outlook read receipt should be filtered." \
  "- [ ] No RFQ created
- [ ] routing_status = ignored
- [ ] message_ignored audit event" "$L_MATCH"

create_issue 22 "matching" "Legacy [RFQ-NN] tag backwards compat" \
  "Reply with numeric [RFQ-65] tag should still match via fallback lookup." \
  "- [ ] Matches RFQ by numeric id when ref_number not found
- [ ] Logs legacy format usage
- [ ] Does not create duplicate" "$L_MATCH"

create_issue 23 "matching" "Different people at same company = separate RFQs" \
  "Two different people (@bigcorp.com) with different routes should each get their own RFQ (#193)." \
  "- [ ] 2 RFQs created
- [ ] Neither attached to the other
- [ ] Domain matching does not over-merge" "$L_MATCH"

create_issue 24 "matching" "Invalid [RFQ-99999999] tag" \
  "Reply with nonexistent RFQ ref. Should fall through matching strategies." \
  "- [ ] No crash
- [ ] Warning logged
- [ ] Falls through to other matching strategies" "$L_MATCH"

create_issue 25 "matching" "Carrier declines load — no junk bid" \
  "Carrier replies 'no' or 'we'll pass'. Bid parser should detect decline (#new fix)." \
  "- [ ] No CarrierBid row created
- [ ] carrier_declined audit event logged
- [ ] RFQ state does not transition" "$L_MATCH"

create_issue 26 "matching" "Rapid-fire 3 emails same sender" \
  "3 emails in quick succession from same sender with different routes. Test race conditions." \
  "- [ ] 3 RFQs created (or fewer if merged intentionally)
- [ ] No duplicate rows
- [ ] Worker processes all without crash" "$L_MATCH"

create_issue 27 "matching" "Email from broker's own address" \
  "Injected email from agents@golteris.com should be skipped." \
  "- [ ] No RFQ created
- [ ] Broker-origin detection works
- [ ] No processing job enqueued" "$L_MATCH"

create_issue 28 "matching" "Email with no sender" \
  "Empty sender field. Should not crash matching logic." \
  "- [ ] No crash
- [ ] Handled gracefully (ignored or flagged)" "$L_MATCH"

create_issue 29 "matching" "Email with no subject" \
  "Empty subject. Matching should still work via sender/content." \
  "- [ ] No crash
- [ ] Matching still runs
- [ ] RFQ created or attached appropriately" "$L_MATCH"

create_issue 30 "matching" "Deeply forwarded email chain" \
  "Fwd: Re: Re: Fwd: with quoted content. Body cleaning should extract real content." \
  "- [ ] Quoted text stripped
- [ ] Extraction finds actual request
- [ ] Not confused by the chain" "$L_MATCH"

# ─── EXTRACTION (31-45) ───
create_issue 31 "extraction" "Industry abbreviations (DV, CHI, DAL)" \
  "Shorthand for equipment and cities. LLM should expand." \
  "- [ ] DV → Dry Van
- [ ] CHI → Chicago, DAL → Dallas
- [ ] Extraction succeeds" "$L_EXTRACT"

create_issue 32 "extraction" "Weight format: 35K lbs" \
  "Weight written as '35K'. Parser should convert to 35000." \
  "- [ ] weight_lbs = 35000
- [ ] Confidence > 0.7" "$L_EXTRACT"

create_issue 33 "extraction" "Mixed equipment types in one email" \
  "Email requests both flatbed and dry van. Handle gracefully." \
  "- [ ] No crash
- [ ] Either primary equipment or multi flag
- [ ] truck_count = total" "$L_EXTRACT"

create_issue 34 "extraction" "Zip codes instead of city names" \
  "Origin/destination given as zip codes." \
  "- [ ] No crash
- [ ] Either resolves zips OR stores as-is
- [ ] Flagged if ambiguous" "$L_EXTRACT"

create_issue 35 "extraction" "Relative dates (ASAP, next Monday)" \
  "Dates like 'ASAP' or 'next Monday'. Parser should resolve or flag." \
  "- [ ] No crash
- [ ] Date parsed or null with flag
- [ ] needs_clarification if ambiguous" "$L_EXTRACT"

create_issue 36 "extraction" "Canadian addresses (Toronto to Montreal)" \
  "Cross-border Canadian shipment. Should extract correctly." \
  "- [ ] origin = 'Toronto, ON'
- [ ] destination = 'Montreal, QC'
- [ ] No US-only assumptions" "$L_EXTRACT"

create_issue 37 "extraction" "Hazmat special requirements" \
  "Email with Class 3 flammable, placards, hazmat endorsement. Should populate special_requirements." \
  "- [ ] special_requirements captures hazmat info
- [ ] equipment_type = tanker or relevant
- [ ] Extraction succeeds" "$L_EXTRACT"

create_issue 38 "extraction" "Per-mile rate expectation" \
  "Customer asks for per-mile rate. Should still extract route." \
  "- [ ] Route extracted
- [ ] No failed extraction on rate-focused request" "$L_EXTRACT"

create_issue 39 "extraction" "Email referencing attachments" \
  "Customer says 'see attached BOL'. Attachments not supported — should degrade gracefully." \
  "- [ ] No crash
- [ ] Flags missing info if key fields are 'in the attachment'
- [ ] needs_clarification triggered" "$L_EXTRACT"

create_issue 40 "extraction" "LTL (less than truckload) request" \
  "4 pallets, 2500 lbs, freight class 70. Not a full truckload." \
  "- [ ] equipment_type = LTL or reflects partial
- [ ] No crash on pallet/class data
- [ ] weight captured" "$L_EXTRACT"

create_issue 41 "extraction" "Temperature-controlled (-10°F)" \
  "Frozen shipment with specific temp range." \
  "- [ ] equipment_type = reefer
- [ ] Temperature in special_requirements" "$L_EXTRACT"

create_issue 42 "extraction" "Multiple pickup/delivery stops" \
  "Multi-stop route. Current schema only supports 1 origin/destination." \
  "- [ ] No crash
- [ ] Primary stop captured
- [ ] Other stops in special_requirements" "$L_EXTRACT"

create_issue 43 "extraction" "Budget constraint in request" \
  "Customer says 'budget is \$500 max'. Should not affect extraction." \
  "- [ ] Route still extracted
- [ ] Budget captured in special_requirements or ignored" "$L_EXTRACT"

create_issue 44 "extraction" "International cross-border shipment" \
  "US to Mexico (Laredo → Guadalajara). Cross-border logistics." \
  "- [ ] Both locations extracted
- [ ] No US-only constraint
- [ ] Cross-border flagged if relevant" "$L_EXTRACT"

create_issue 45 "extraction" "Conflicting information in email" \
  "Email contradicts itself ('reefer... actually dry van... wait reefer'). Model should pick one." \
  "- [ ] Extraction completes
- [ ] Final value is defensible
- [ ] Lower confidence reflects ambiguity" "$L_EXTRACT"

# ─── API EDGE CASES (46-60) ───
create_issue 46 "api" "GET /api/rfqs with invalid state filter" \
  "Query with state=nonexistent_state. Should 400 or return empty." \
  "- [ ] No 500 error
- [ ] Graceful handling" "$L_API"

create_issue 47 "api" "GET nonexistent RFQ ID" \
  "GET /api/rfqs/999999 should 404." \
  "- [ ] Returns 404
- [ ] JSON error body" "$L_API"

create_issue 48 "api" "Distribute to zero carriers" \
  "POST distribute with empty carrier_ids array." \
  "- [ ] Returns 400
- [ ] Clear error message
- [ ] No RFQ state change" "$L_API"

create_issue 49 "api" "Distribute to nonexistent carriers" \
  "carrier_ids = [999999]. Should fail cleanly." \
  "- [ ] Returns 400
- [ ] No orphaned CarrierRfqSend rows" "$L_API"

create_issue 50 "api" "Price RFQ with nonexistent bid" \
  "POST /api/rfqs/{id}/price with carrier_bid_id = 999999." \
  "- [ ] Returns 404
- [ ] No price set on RFQ" "$L_API"

create_issue 51 "api" "Set invalid outcome" \
  "POST outcome with 'banana'. Should reject." \
  "- [ ] Returns 400
- [ ] RFQ outcome unchanged" "$L_API"

create_issue 52 "api" "Create carrier with empty name" \
  "POST /api/carriers with name=''." \
  "- [ ] Returns 400 or 422
- [ ] No empty carrier row" "$L_API"

create_issue 53 "api" "Duplicate carrier email" \
  "Create two carriers with same email. Should enforce uniqueness or merge." \
  "- [ ] Second create fails with clear error OR updates existing
- [ ] No silent duplicate" "$L_API"

create_issue 54 "api" "Approve nonexistent approval" \
  "POST approve on approval_id = 999999." \
  "- [ ] Returns 404
- [ ] No crash" "$L_API"

create_issue 55 "api" "Chat with empty message" \
  "POST /api/chat with empty body." \
  "- [ ] Returns 400 or empty response
- [ ] No LLM call with empty prompt" "$L_API"

create_issue 56 "api" "Chat with 5000-word message" \
  "POST /api/chat with very long user message. Should respect LLM token limits." \
  "- [ ] No crash
- [ ] Either truncates or returns limit error" "$L_API"

create_issue 57 "api" "Extreme pagination (offset=999999)" \
  "GET /api/rfqs?offset=999999&limit=10000. Should return empty, not crash." \
  "- [ ] Returns empty list
- [ ] No DB timeout" "$L_API"

create_issue 58 "api" "Counter-offer with \$0 rate" \
  "POST counter-offer with proposed_rate = 0." \
  "- [ ] Returns 400 or prevents send
- [ ] No zero-rate email sent to carrier" "$L_API"

create_issue 59 "api" "Generate quote with no quoted amount" \
  "POST generate-quote on RFQ where quoted_amount is null." \
  "- [ ] Returns 400 with 'no quoted amount' error
- [ ] No customer email drafted" "$L_API"

create_issue 60 "api" "Distribute to deleted carrier" \
  "Delete a carrier, then try to distribute to its id." \
  "- [ ] Returns 400
- [ ] No send attempted" "$L_API"

# ─── STATE MACHINE (61-75) ───
create_issue 61 "state" "Force RFQ to won from wrong state" \
  "POST outcome=won on RFQ in needs_clarification. State machine should block." \
  "- [ ] Transition rejected OR allowed with override audit
- [ ] Clear reason in response" "$L_STATE"

create_issue 62 "state" "Cancel RFQ from any state" \
  "Cancel should work from ANY non-terminal state." \
  "- [ ] Transition allowed
- [ ] outcome = cancelled
- [ ] closed_at set" "$L_STATE"

create_issue 63 "state" "Distribute on cancelled RFQ" \
  "Attempt distribution on terminal RFQ." \
  "- [ ] Returns 400
- [ ] No state change
- [ ] No carrier send" "$L_STATE"

create_issue 64 "state" "Double-approve same approval" \
  "Call approve twice on same approval_id." \
  "- [ ] Second call is idempotent or rejects cleanly
- [ ] Only one email send job enqueued" "$L_STATE"

create_issue 65 "state" "Reject then approve same approval" \
  "Reject, then try to approve. Should be blocked." \
  "- [ ] Approve rejected (status already resolved)
- [ ] No email sent" "$L_STATE"

create_issue 66 "state" "Clarification on ready_to_quote RFQ" \
  "Request clarification on RFQ that's already complete." \
  "- [ ] Either allowed with state change or blocked
- [ ] No data loss" "$L_STATE"

create_issue 67 "state" "Regenerate quote sheet on incomplete RFQ" \
  "Attempt regeneration when fields are missing." \
  "- [ ] Either generates partial sheet or flags error
- [ ] No crash" "$L_STATE"

create_issue 68 "state" "Full lifecycle (create through extract)" \
  "End-to-end: inject → extract → validate → quote sheet. Verify all state transitions." \
  "- [ ] RFQ reaches ready_to_quote (or needs_clarification)
- [ ] Quote sheet generated
- [ ] All audit events recorded" "$L_STATE"

create_issue 69 "state" "Change outcome on already-won RFQ" \
  "Terminal state should not transition to another terminal state." \
  "- [ ] Second outcome change blocked
- [ ] Audit logged" "$L_STATE"

create_issue 70 "state" "Manual reply on inquiry-state RFQ" \
  "Broker sends manual reply while RFQ is in inquiry." \
  "- [ ] Reply drafted and sent
- [ ] State transitions if applicable" "$L_STATE"

create_issue 71 "state" "Distribute to same carrier twice" \
  "Call distribute with same carrier_id on same RFQ twice." \
  "- [ ] Second call detects duplicate OR creates second send intentionally
- [ ] No duplicate emails to carrier" "$L_STATE"

create_issue 72 "state" "Price with negative markup" \
  "markup_percent = -50. Should sanity-check." \
  "- [ ] Returns 400 or warns
- [ ] No negative customer price" "$L_STATE"

create_issue 73 "state" "Download Excel with no quote sheet" \
  "GET /quote-sheet/download on RFQ without generated sheet." \
  "- [ ] Returns 404
- [ ] Clear error message" "$L_STATE"

create_issue 74 "state" "Redraft on non-clarification RFQ" \
  "Redraft endpoint only applies to needs_clarification." \
  "- [ ] Returns 400 or only shown in UI conditionally
- [ ] No change to RFQ" "$L_STATE"

create_issue 75 "state" "Generate customer quote from wrong state" \
  "Generate quote from state that shouldn't allow it (e.g., needs_clarification)." \
  "- [ ] Returns 400
- [ ] No quote email drafted" "$L_STATE"

# ─── BID PARSING (76-85) ───
create_issue 76 "bids" "Carrier bid with \$2,850 rate" \
  "Standard all-in bid. Verify extraction." \
  "- [ ] CarrierBid row created
- [ ] rate = 2850, currency = USD, rate_type = all_in" "$L_BIDS"

create_issue 77 "bids" "Per-mile rate bid" \
  "'\$3.25/mile'. Parser should detect rate_type = per_mile." \
  "- [ ] rate captured (may be per-mile or computed total)
- [ ] rate_type = per_mile" "$L_BIDS"

create_issue 78 "bids" "Linehaul + FSC breakdown bid" \
  "Linehaul \$2400 + FSC \$380 = \$2780. Parser should capture total." \
  "- [ ] rate = 2780
- [ ] rate_type = linehaul_plus_fsc" "$L_BIDS"

create_issue 79 "bids" "Carrier asks questions instead of bidding" \
  "Reply contains only questions, no rate. Should not create empty bid." \
  "- [ ] No CarrierBid row (or low confidence)
- [ ] Flagged for broker review" "$L_BIDS"

create_issue 80 "bids" "Bid with conditions/restrictions" \
  "Conditional bid with pickup time window and tarping fee." \
  "- [ ] Bid captured with conditions in notes
- [ ] Confidence reflects complexity" "$L_BIDS"

create_issue 81 "bids" "Carrier offers 3 rate options" \
  "Multiple rate options (standard/expedited/flexible)." \
  "- [ ] At least primary rate captured
- [ ] Notes mention alternatives" "$L_BIDS"

create_issue 82 "bids" "Carrier declines angrily" \
  "Angry decline with 'take me off your list'." \
  "- [ ] declined = true
- [ ] carrier_declined audit event
- [ ] No bid row" "$L_BIDS"

create_issue 83 "bids" "Bid in Canadian dollars" \
  "Rate given in CAD. Parser should capture currency." \
  "- [ ] currency = CAD
- [ ] rate stored in original currency" "$L_BIDS"

create_issue 84 "bids" "Carrier replies just 'OK'" \
  "Ambiguous one-word reply." \
  "- [ ] confidence < 0.7
- [ ] Flagged for review
- [ ] No bid commitment" "$L_BIDS"

create_issue 85 "bids" "Carrier bids on wrong lane" \
  "Bid references different origin/destination than the RFQ." \
  "- [ ] Captured but flagged
- [ ] Broker can see mismatch" "$L_BIDS"

# ─── QUOTE RESPONSE (86-95) ───
create_issue 86 "quote_response" "Customer clearly accepts" \
  "'Let's do it. Book the truck.'" \
  "- [ ] classification = accepted
- [ ] confidence > 0.8
- [ ] RFQ → won
- [ ] Confirmation email drafted" "$L_QR"

create_issue 87 "quote_response" "Customer clearly rejects" \
  "'Too expensive. Thanks anyway.'" \
  "- [ ] classification = rejected
- [ ] RFQ → lost
- [ ] Close-out email drafted" "$L_QR"

create_issue 88 "quote_response" "Customer negotiates price" \
  "Customer asks for \$200 off." \
  "- [ ] classification = question
- [ ] RFQ stays in waiting_on_broker
- [ ] Approval created for broker" "$L_QR"

create_issue 89 "quote_response" "Accept + question in same email (#191)" \
  "'Book it. Also, do you handle hazmat?'" \
  "- [ ] classification = accepted
- [ ] has_additional_question = true
- [ ] additional_question audit event created
- [ ] RFQ → won" "$L_QR"

create_issue 90 "quote_response" "Ambiguous 'check with my team'" \
  "Soft acceptance that's really a hold." \
  "- [ ] classification = question
- [ ] RFQ stays in waiting_on_broker" "$L_QR"

create_issue 91 "quote_response" "Customer replies just 'Thanks'" \
  "Bare acknowledgment. Ambiguous intent." \
  "- [ ] classification = question (safe default)
- [ ] confidence < 0.7" "$L_QR"

create_issue 92 "quote_response" "Customer requests different equipment" \
  "Change from dry van to flatbed." \
  "- [ ] classification = question
- [ ] RFQ stays waiting_on_broker for manual handling" "$L_QR"

create_issue 93 "quote_response" "ALL CAPS acceptance" \
  "'YES BOOK IT NOW'." \
  "- [ ] classification = accepted
- [ ] Not confused by caps
- [ ] RFQ → won" "$L_QR"

create_issue 94 "quote_response" "Customer replies weeks later" \
  "Late reply asking if quote is still valid." \
  "- [ ] classification = question (validity check)
- [ ] RFQ in waiting_on_broker" "$L_QR"

create_issue 95 "quote_response" "Customer forwards quote internally" \
  "Fwd: with internal question to boss. Not actually a response." \
  "- [ ] Detected as forward (no classification) OR treated as question
- [ ] No automatic won/lost transition" "$L_QR"

# ─── SYSTEM / SECURITY (96-100) ───
create_issue 96 "system" "Workflow kill switch during email" \
  "Kill all workflows (C1), inject email, verify nothing processes." \
  "- [ ] Injected email stored but no job runs
- [ ] Re-enabling workflows resumes processing
- [ ] Kill switch takes effect within 30s" "$L_SYS"

create_issue 97 "system" "Poll worker with no jobs" \
  "Empty poll should be idempotent." \
  "- [ ] Returns jobs_processed = 0
- [ ] No errors" "$L_SYS"

create_issue 98 "system" "10 simultaneous email injections" \
  "Burst test. Worker should process all without race conditions." \
  "- [ ] All 10 ingested
- [ ] No duplicate RFQs
- [ ] No worker crashes" "$L_SYS"

create_issue 99 "system" "SQL injection attempt" \
  "Email body with SQL injection strings. ORM should escape." \
  "- [ ] No SQL executed
- [ ] Tables intact
- [ ] Data stored as literal string" "$L_SYS"

create_issue 100 "system" "XSS attempt in email fields" \
  "Script tags in sender/subject/body. Frontend must escape on render." \
  "- [ ] Stored as-is in DB
- [ ] Rendered as text, not HTML
- [ ] No alert() fires in UI" "$L_SYS"

echo ""
echo "Done. 100 test issues created."
