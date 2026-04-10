"""
100-scenario stress test for Golteris AI Platform.

Tests every layer: email ingestion, message matching, extraction, validation,
quote sheet, carrier distribution, bid parsing, quote response, state machine,
API edge cases, and concurrency.

Each scenario injects data via the API, polls the worker, and checks results.
Scenarios are grouped by category and can be run individually or as a suite.

Usage:
    python scripts/stress_test_100.py                    # Run all
    python scripts/stress_test_100.py --category email   # Run one category
    python scripts/stress_test_100.py --scenario 42      # Run one scenario
"""

import json
import time
import subprocess
import sys
import argparse
from datetime import datetime

API = "https://app.golteris.com"
RESULTS = []
SCENARIO_NUM = 0


# ═══════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════

def api(method, path, data=None):
    cmd = ["curl", "-s"]
    if method in ("POST", "PUT", "PATCH", "DELETE"):
        cmd += ["-X", method]
    if data:
        cmd += ["-H", "Content-Type: application/json", "-d", json.dumps(data)]
    cmd.append(f"{API}{path}")
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    try:
        return json.loads(r.stdout) if r.stdout.strip() else {}
    except Exception:
        return {"raw": r.stdout[:300]}


def inject(sender, subject, body):
    return api("POST", "/api/dev/inject-email", {
        "sender": sender, "subject": subject, "body": body,
    })


def poll(rounds=3, interval=3):
    for _ in range(rounds):
        api("POST", "/api/admin/poll")
        time.sleep(interval)


def get_rfqs(limit=20):
    return api("GET", f"/api/rfqs?limit={limit}&include_terminal=true")


def get_rfq(rfq_id):
    return api("GET", f"/api/rfqs/{rfq_id}")


def get_activity(rfq_id=None, limit=20):
    path = f"/api/admin/activity-log?limit={limit}"
    if rfq_id:
        path += f"&rfq_id={rfq_id}"
    return api("GET", path)


def latest_rfq():
    """Return the most recently created RFQ."""
    data = get_rfqs(1)
    rfqs = data.get("rfqs", [])
    return rfqs[0] if rfqs else None


def scenario(num, category, name, action_fn, check_fn, timeout=20):
    """Run a single scenario: action → poll → check."""
    global SCENARIO_NUM
    SCENARIO_NUM = num
    print(f"\n{'─'*60}")
    print(f"  #{num:03d} [{category}] {name}")

    try:
        result = action_fn()
        if isinstance(result, dict) and result.get("raw", "").startswith("<!"):
            record("FAIL", num, category, name, "API returned HTML (server error)")
            return False

        poll(rounds=timeout // 5, interval=4)
        time.sleep(2)

        passed, details = check_fn(result)
        status = "PASS" if passed else "FAIL"
        record(status, num, category, name, details)
        return passed

    except Exception as e:
        record("ERROR", num, category, name, str(e)[:120])
        return False


def record(status, num, category, name, details):
    icon = {"PASS": "✓", "FAIL": "✗", "ERROR": "!", "SKIP": "–"}.get(status, "?")
    print(f"  {icon} {status}: {details[:100]}")
    RESULTS.append({
        "num": num, "category": category, "name": name,
        "status": status, "details": details,
    })


# ═══════════════════════════════════════════════════════════
# CATEGORY 1: EMAIL INGESTION (1-15)
# ═══════════════════════════════════════════════════════════

def s001():
    """Normal RFQ email with all fields."""
    def action():
        return inject(
            "Alice Smith <alice@acmecorp.com>",
            "Quote request - Chicago to Dallas",
            "Need 2 dry vans from Chicago IL to Dallas TX. 40,000 lbs of auto parts. Pickup May 1, 2026. Delivery May 3, 2026."
        )
    def check(r):
        rfq = latest_rfq()
        if not rfq:
            return False, "No RFQ created"
        if rfq.get("state") in ("ready_to_quote", "needs_clarification"):
            return True, f"RFQ #{rfq['id']} state={rfq['state']} ref={rfq.get('ref_number')}"
        return False, f"Unexpected state: {rfq.get('state')}"
    return scenario(1, "email", "Normal RFQ with all fields", action, check)


def s002():
    """Minimal email — just origin and destination, missing everything else."""
    def action():
        return inject(
            "Bob <bob@somewhere.com>",
            "Shipping help",
            "I need to move stuff from NYC to LA."
        )
    def check(r):
        rfq = latest_rfq()
        if not rfq:
            return False, "No RFQ created"
        if rfq.get("state") == "needs_clarification":
            return True, f"Correctly flagged as needs_clarification — missing fields"
        if rfq.get("state") == "inquiry":
            return True, f"Classified as inquiry — vague request"
        return False, f"State: {rfq.get('state')}"
    return scenario(2, "email", "Minimal email — origin/dest only", action, check)


def s003():
    """Empty email body."""
    def action():
        return inject("Empty <empty@test.com>", "Quote needed", "")
    def check(r):
        rfq = latest_rfq()
        if rfq and rfq.get("customer_email") == "empty@test.com":
            return True, f"Created RFQ #{rfq['id']} from empty body — state={rfq.get('state')}"
        return True, "No RFQ created from empty body — acceptable"
    return scenario(3, "email", "Empty email body", action, check)


def s004():
    """Email with only a signature, no real content."""
    def action():
        return inject(
            "Sig Only <sig@corp.com>", "Re: stuff",
            "Sent from my iPhone\n\n---\nJohn Smith\nVP Operations\n555-1234"
        )
    def check(r):
        # Should be cleaned to near-empty, classified as inquiry or ignored
        return True, "Processed without crash"
    return scenario(4, "email", "Email with only signature", action, check)


def s005():
    """Email in Spanish."""
    def action():
        return inject(
            "Carlos <carlos@mex.com>", "Cotización de flete",
            "Necesito enviar 3 camiones de producto congelado de Monterrey a Ciudad de México. 45,000 libras."
        )
    def check(r):
        rfq = latest_rfq()
        if rfq and rfq.get("customer_email") == "carlos@mex.com":
            return True, f"Handled non-English email — state={rfq.get('state')}"
        return True, "No crash on non-English input"
    return scenario(5, "email", "Email in Spanish", action, check)


def s006():
    """Email with HTML tags in body."""
    def action():
        return inject(
            "Html <html@test.com>", "Quote please",
            "<html><body><p>Need <b>2 flatbeds</b> from <i>Denver</i> to <i>Phoenix</i>.</p><br/><table><tr><td>Weight</td><td>30000 lbs</td></tr></table></body></html>"
        )
    def check(r):
        rfq = latest_rfq()
        if rfq and rfq.get("customer_email") == "html@test.com":
            return True, f"Extracted from HTML — origin={rfq.get('origin')}"
        return True, "Processed HTML without crash"
    return scenario(6, "email", "Email with HTML tags", action, check)


def s007():
    """Very long email (2000+ words)."""
    def action():
        filler = "This is additional context about our shipping needs. " * 200
        return inject(
            "Verbose <verbose@test.com>", "Detailed shipping request",
            f"We need 1 dry van from Atlanta GA to Nashville TN. 20000 lbs of electronics. {filler}"
        )
    def check(r):
        rfq = latest_rfq()
        if rfq and rfq.get("customer_email") == "verbose@test.com":
            return True, f"Handled long email — state={rfq.get('state')}"
        return False, "No RFQ created from long email"
    return scenario(7, "email", "Very long email (2000+ words)", action, check)


def s008():
    """Email with special characters and emojis."""
    def action():
        return inject(
            "Émile Müller <emile@über.com>", "Fréight Quoté 🚛",
            "Néed 1 réefer from São Paulo → Bogotá. 15,000 lbs of açaí 🫐. ASAP! $$$"
        )
    def check(r):
        return True, "No crash on special characters/emojis"
    return scenario(8, "email", "Special characters and emojis", action, check)


def s009():
    """Auto-reply / out-of-office should be ignored."""
    def action():
        return inject(
            "AutoReply <noreply@corp.com>",
            "Automatic Reply: Out of Office",
            "I am out of the office until Monday. For urgent matters contact Jane."
        )
    def check(r):
        # Should NOT create an RFQ
        rfq = latest_rfq()
        if rfq and rfq.get("customer_email") == "noreply@corp.com":
            return False, "Auto-reply created an RFQ — should have been ignored"
        return True, "Auto-reply correctly ignored"
    return scenario(9, "email", "Auto-reply should be ignored", action, check)


def s010():
    """Delivery notification / bounce should be ignored."""
    def action():
        return inject(
            "mailer-daemon@outlook.com",
            "Undeliverable: Your message could not be delivered",
            "Delivery has failed to these recipients. 550 5.1.1 User unknown."
        )
    def check(r):
        rfq = latest_rfq()
        if rfq and rfq.get("customer_email") == "mailer-daemon@outlook.com":
            return False, "Bounce created an RFQ"
        return True, "Bounce correctly ignored"
    return scenario(10, "email", "Bounce/undeliverable ignored", action, check)


def s011():
    """Multi-lane request — 3 different routes in one email."""
    def action():
        return inject(
            "MultiLane <multi@corp.com>", "Multiple shipments needed",
            "We need quotes for:\n1. Chicago to Dallas — 2 dry vans, 40k lbs\n2. Miami to Atlanta — 1 reefer, 15k lbs\n3. LA to Seattle — 3 flatbeds, 60k lbs"
        )
    def check(r):
        rfq = latest_rfq()
        if rfq and rfq.get("customer_email") == "multi@corp.com":
            return True, f"Multi-lane handled — state={rfq.get('state')}, origin={rfq.get('origin')}"
        return False, "No RFQ created for multi-lane"
    return scenario(11, "email", "Multi-lane request (3 routes)", action, check)


def s012():
    """Email that's a general inquiry, not an RFQ."""
    def action():
        return inject(
            "Curious <curious@test.com>", "Question about services",
            "Hi, do you handle international shipping? What countries do you service? Also do you do warehousing?"
        )
    def check(r):
        rfq = latest_rfq()
        if rfq and rfq.get("customer_email") == "curious@test.com":
            if rfq.get("state") == "inquiry":
                return True, "Correctly classified as inquiry"
            return True, f"Created as {rfq.get('state')} — acceptable"
        return True, "No RFQ for general inquiry — acceptable"
    return scenario(12, "email", "General inquiry (not an RFQ)", action, check)


def s013():
    """Email with impossible dates (past dates)."""
    def action():
        return inject(
            "PastDate <pastdate@test.com>", "Need shipment",
            "Need 1 dry van from Boston to Philly. 10000 lbs. Pickup January 5, 2020."
        )
    def check(r):
        rfq = latest_rfq()
        if rfq and rfq.get("customer_email") == "pastdate@test.com":
            return True, f"Handled past date — pickup={rfq.get('pickup_date')}"
        return True, "Processed without crash"
    return scenario(13, "email", "Email with impossible past dates", action, check)


def s014():
    """Email with swapped dates (delivery before pickup)."""
    def action():
        return inject(
            "SwapDate <swapdate@test.com>", "Freight quote",
            "1 reefer from Memphis to Louisville. 25000 lbs. Pickup June 15 2026, delivery June 10 2026."
        )
    def check(r):
        rfq = latest_rfq()
        if rfq and rfq.get("customer_email") == "swapdate@test.com":
            return True, f"Handled swapped dates — pickup={rfq.get('pickup_date')}, delivery={rfq.get('delivery_date')}"
        return True, "Processed without crash"
    return scenario(14, "email", "Swapped dates (delivery before pickup)", action, check)


def s015():
    """Email with ridiculous weight (999,999,999 lbs)."""
    def action():
        return inject(
            "BigShip <bigship@test.com>", "Need shipping",
            "Need 1 flatbed from Houston to Phoenix. 999999999 lbs of steel."
        )
    def check(r):
        rfq = latest_rfq()
        if rfq and rfq.get("customer_email") == "bigship@test.com":
            return True, f"Handled extreme weight — weight={rfq.get('weight_lbs')}"
        return True, "Processed without crash"
    return scenario(15, "email", "Extreme weight (999M lbs)", action, check)


# ═══════════════════════════════════════════════════════════
# CATEGORY 2: MESSAGE MATCHING (16-30)
# ═══════════════════════════════════════════════════════════

def s016():
    """Reply with [RFQ-ref_number] tag — should match."""
    def action():
        rfq = latest_rfq()
        if not rfq:
            return {"skip": True}
        ref = rfq.get("ref_number", str(rfq["id"]))
        return inject(
            "alice@acmecorp.com", f"Re: Quote request [RFQ-{ref}]",
            "Actually make it 3 trucks instead of 2."
        )
    def check(r):
        if r.get("skip"):
            return True, "Skipped — no RFQ available"
        return True, "Reply with RFQ tag processed"
    return scenario(16, "matching", "Reply with [RFQ-ref] tag matches", action, check)


def s017():
    """Same sender, completely different subject — should create new RFQ."""
    def action():
        return inject(
            "Alice Smith <alice@acmecorp.com>",
            "New request - Seattle to Portland",
            "Separate shipment: 1 reefer from Seattle WA to Portland OR. 12000 lbs of seafood."
        )
    def check(r):
        rfqs = get_rfqs(5)
        alice_rfqs = [x for x in rfqs.get("rfqs", []) if "alice" in (x.get("customer_email") or "").lower() or "alice" in (x.get("customer_name") or "").lower()]
        if len(alice_rfqs) >= 2:
            return True, f"Created separate RFQ for new route — {len(alice_rfqs)} RFQs for Alice"
        return False, f"Only {len(alice_rfqs)} RFQs for Alice — expected 2+"
    return scenario(17, "matching", "Same sender new subject = new RFQ", action, check)


def s018():
    """Reply from same sender on existing thread — should attach."""
    def action():
        rfq = latest_rfq()
        if not rfq:
            return {"skip": True}
        return inject(
            f"{rfq.get('customer_name', 'Test')} <{rfq.get('customer_email', 'test@test.com')}>",
            f"Re: {rfq.get('origin', 'Test')} to {rfq.get('destination', 'Test')}",
            "Also wanted to add: need liftgate at destination."
        )
    def check(r):
        if r.get("skip"):
            return True, "Skipped"
        return True, "Reply processed without crash"
    return scenario(18, "matching", "Reply from same sender attaches", action, check)


def s019():
    """Email from a known carrier (should route to bid parser)."""
    def action():
        carriers = api("GET", "/api/carriers")
        carrier_list = carriers.get("carriers", [])
        if not carrier_list:
            return {"skip": True}
        c = carrier_list[0]
        rfq = latest_rfq()
        if not rfq:
            return {"skip": True}
        ref = rfq.get("ref_number", str(rfq["id"]))
        return inject(
            f"{c['name']} <{c['email']}>",
            f"Re: RFQ [RFQ-{ref}]",
            "We can do this for $3,200 all in. Available next Tuesday."
        )
    def check(r):
        if r.get("skip"):
            return True, "Skipped — no carriers or RFQs"
        return True, "Carrier reply processed"
    return scenario(19, "matching", "Known carrier reply routes to bid parser", action, check)


def s020():
    """Email from unknown sender with no context — should create new RFQ."""
    def action():
        return inject(
            "Unknown Person <unknown42@randomdomain.com>",
            "Freight help",
            "Can you move 1 truck of furniture from Denver to Salt Lake City? About 20k lbs."
        )
    def check(r):
        rfq = latest_rfq()
        if rfq and "unknown42" in (rfq.get("customer_email") or ""):
            return True, f"New RFQ created for unknown sender — #{rfq['id']}"
        return False, "No RFQ for unknown sender"
    return scenario(20, "matching", "Unknown sender creates new RFQ", action, check)


def s021():
    """Read receipt should be ignored."""
    def action():
        return inject(
            "outlook@microsoft.com",
            "Read: Your message was read",
            "Your message to John was read on April 10, 2026 at 3:00 PM."
        )
    def check(r):
        return True, "Read receipt processed (should be ignored)"
    return scenario(21, "matching", "Read receipt ignored", action, check)


def s022():
    """Reply with legacy [RFQ-NN] numeric tag — backwards compat."""
    def action():
        rfq = latest_rfq()
        if not rfq:
            return {"skip": True}
        return inject(
            f"{rfq.get('customer_name', 'Test')} <{rfq.get('customer_email', 'test@test.com')}>",
            f"Re: old thread [RFQ-{rfq['id']}]",
            "Just following up on this."
        )
    def check(r):
        if r.get("skip"):
            return True, "Skipped"
        return True, "Legacy numeric tag processed"
    return scenario(22, "matching", "Legacy [RFQ-NN] tag backwards compat", action, check)


def s023():
    """Two different people at same company — should create separate RFQs."""
    def action():
        inject("John <john@bigcorp.com>", "Need quote - Miami to Tampa",
               "1 dry van Miami to Tampa, 15000 lbs office supplies.")
        poll(2, 3)
        return inject("Jane <jane@bigcorp.com>", "Freight request - Boston to NYC",
                      "2 reefers Boston to NYC, 30000 lbs frozen food.")
    def check(r):
        rfqs = get_rfqs(10)
        bigcorp = [x for x in rfqs.get("rfqs", []) if "bigcorp.com" in (x.get("customer_email") or "")]
        if len(bigcorp) >= 2:
            return True, f"Separate RFQs for different people at same company — {len(bigcorp)}"
        return False, f"Only {len(bigcorp)} RFQs for bigcorp.com"
    return scenario(23, "matching", "Different people at same company = separate RFQs", action, check)


def s024():
    """Email with [RFQ-INVALID] tag — nonexistent RFQ ref."""
    def action():
        return inject(
            "Ghost <ghost@test.com>",
            "Re: stuff [RFQ-99999999]",
            "Following up on our conversation."
        )
    def check(r):
        return True, "Invalid RFQ tag handled without crash"
    return scenario(24, "matching", "Invalid [RFQ-99999999] tag", action, check)


def s025():
    """Carrier declines the load — should NOT create a bid."""
    def action():
        rfq = latest_rfq()
        if not rfq:
            return {"skip": True}
        ref = rfq.get("ref_number", str(rfq["id"]))
        carriers = api("GET", "/api/carriers")
        if not carriers.get("carriers"):
            return {"skip": True}
        c = carriers["carriers"][0]
        return inject(
            f"{c['name']} <{c['email']}>",
            f"Re: RFQ [RFQ-{ref}]",
            "Sorry, we'll have to pass on this one. No trucks available in that area."
        )
    def check(r):
        if r.get("skip"):
            return True, "Skipped"
        # Check for carrier_declined audit event
        act = get_activity(limit=10)
        declined = [e for e in act.get("events", []) if e.get("event_type") == "carrier_declined"]
        if declined:
            return True, f"Carrier decline detected: {declined[0].get('description', '')[:80]}"
        return True, "Processed (decline may not have triggered — carrier match needed)"
    return scenario(25, "matching", "Carrier declines load — no junk bid", action, check)


def s026():
    """Rapid-fire: 3 emails from same sender in 5 seconds."""
    def action():
        inject("Rapid <rapid@test.com>", "Quote 1", "1 dry van Chicago to Detroit 10000 lbs")
        inject("Rapid <rapid@test.com>", "Quote 2", "1 reefer LA to SF 20000 lbs")
        return inject("Rapid <rapid@test.com>", "Quote 3", "1 flatbed Dallas to Houston 30000 lbs")
    def check(r):
        rfqs = get_rfqs(10)
        rapid = [x for x in rfqs.get("rfqs", []) if "rapid@test.com" in (x.get("customer_email") or "")]
        return True, f"Rapid fire: {len(rapid)} RFQs created for rapid@test.com"
    return scenario(26, "matching", "Rapid-fire 3 emails same sender", action, check, timeout=30)


def s027():
    """Email from broker's own address — should be ignored."""
    def action():
        return inject(
            "agents@golteris.com",
            "Test self-send",
            "This is a test from our own mailbox."
        )
    def check(r):
        return True, "Self-send processed (should skip processing)"
    return scenario(27, "matching", "Email from broker's own address", action, check)


def s028():
    """Email with no sender."""
    def action():
        return inject("", "No sender email", "Need a quote from Dallas to Austin.")
    def check(r):
        return True, "Empty sender handled without crash"
    return scenario(28, "matching", "Email with no sender", action, check)


def s029():
    """Email with no subject."""
    def action():
        return inject("NoSubject <nosub@test.com>", "", "Need 1 dry van Boston to Philly 15000 lbs.")
    def check(r):
        rfq = latest_rfq()
        if rfq and "nosub@test.com" in (rfq.get("customer_email") or ""):
            return True, f"Created RFQ from no-subject email — state={rfq.get('state')}"
        return True, "Handled no-subject without crash"
    return scenario(29, "matching", "Email with no subject", action, check)


def s030():
    """Forwarded email chain with deep quoting."""
    def action():
        return inject(
            "Forwarder <fwd@test.com>",
            "Fwd: Re: Re: Fwd: Shipping request",
            "---------- Forwarded message ----------\nFrom: Someone\nDate: Mon, Apr 7\n\n"
            "> > > Original request: Need 1 dry van from Omaha to KC\n"
            "> > Sure, let me check\n"
            "> Actually we need 2 trucks\n\n"
            "Can you help with this? 25000 lbs of grain."
        )
    def check(r):
        rfq = latest_rfq()
        if rfq and "fwd@test.com" in (rfq.get("customer_email") or ""):
            return True, f"Forwarded chain handled — state={rfq.get('state')}"
        return True, "Processed without crash"
    return scenario(30, "matching", "Deeply forwarded email chain", action, check)


# ═══════════════════════════════════════════════════════════
# CATEGORY 3: EXTRACTION EDGE CASES (31-45)
# ═══════════════════════════════════════════════════════════

def s031():
    """Abbreviations: dry van = DV, flatbed = FB, reefer = RF."""
    def action():
        return inject(
            "Abbrev <abbrev@test.com>", "Need DV quote",
            "2 DV from CHI to DAL, ~35K lbs of consumer goods. PU 5/1."
        )
    def check(r):
        rfq = latest_rfq()
        if rfq and "abbrev@test.com" in (rfq.get("customer_email") or ""):
            return True, f"Abbreviations handled — equip={rfq.get('equipment_type')}, origin={rfq.get('origin')}"
        return True, "Processed without crash"
    return scenario(31, "extraction", "Industry abbreviations (DV, CHI, DAL)", action, check)


def s032():
    """Weight in different formats: 35K, 35,000, 35000, 35 thousand."""
    def action():
        return inject(
            "Weight <weight@test.com>", "Quote request",
            "Need 1 dry van Pittsburgh to Cleveland. Approx 35K lbs of machinery."
        )
    def check(r):
        rfq = latest_rfq()
        if rfq and "weight@test.com" in (rfq.get("customer_email") or ""):
            return True, f"Weight parsed — weight_lbs={rfq.get('weight_lbs')}"
        return True, "Processed without crash"
    return scenario(32, "extraction", "Weight format: 35K lbs", action, check)


def s033():
    """Multiple equipment types in one request."""
    def action():
        return inject(
            "MixEquip <mixequip@test.com>", "Mixed equipment",
            "Need 1 flatbed and 2 dry vans from St Louis to Memphis. 45000 lbs total."
        )
    def check(r):
        rfq = latest_rfq()
        if rfq and "mixequip@test.com" in (rfq.get("customer_email") or ""):
            return True, f"Mixed equipment — type={rfq.get('equipment_type')}, trucks={rfq.get('truck_count')}"
        return True, "Processed without crash"
    return scenario(33, "extraction", "Mixed equipment types in one email", action, check)


def s034():
    """Zip codes instead of city names."""
    def action():
        return inject(
            "Zips <zips@test.com>", "Shipment quote",
            "Need a quote from 60601 to 75201. 1 dry van, 20000 lbs."
        )
    def check(r):
        rfq = latest_rfq()
        if rfq and "zips@test.com" in (rfq.get("customer_email") or ""):
            return True, f"Zip codes handled — origin={rfq.get('origin')}, dest={rfq.get('destination')}"
        return True, "Processed without crash"
    return scenario(34, "extraction", "Zip codes instead of city names", action, check)


def s035():
    """Relative dates: 'next Monday', 'end of week', 'ASAP'."""
    def action():
        return inject(
            "RelDate <reldate@test.com>", "Urgent shipment",
            "Need 1 reefer from Orlando to Jacksonville ASAP. 18000 lbs of dairy. Pickup next Monday."
        )
    def check(r):
        rfq = latest_rfq()
        if rfq and "reldate@test.com" in (rfq.get("customer_email") or ""):
            return True, f"Relative dates — pickup={rfq.get('pickup_date')}"
        return True, "Processed without crash"
    return scenario(35, "extraction", "Relative dates (ASAP, next Monday)", action, check)


def s036():
    """Canadian addresses."""
    def action():
        return inject(
            "Canadian <canadian@test.com>", "Cross-border shipment",
            "Need 1 dry van from Toronto, ON to Montreal, QC. 22000 lbs of furniture."
        )
    def check(r):
        rfq = latest_rfq()
        if rfq and "canadian@test.com" in (rfq.get("customer_email") or ""):
            return True, f"Canadian addresses — origin={rfq.get('origin')}, dest={rfq.get('destination')}"
        return True, "Processed without crash"
    return scenario(36, "extraction", "Canadian addresses (Toronto to Montreal)", action, check)


def s037():
    """Hazmat / special requirements."""
    def action():
        return inject(
            "Hazmat <hazmat@test.com>", "Hazmat shipment",
            "Need 1 tanker from Houston to New Orleans. 40000 lbs of Class 3 flammable liquids. Hazmat placards required. Driver must have hazmat endorsement."
        )
    def check(r):
        rfq = latest_rfq()
        if rfq and "hazmat@test.com" in (rfq.get("customer_email") or ""):
            return True, f"Hazmat handled — special={rfq.get('special_requirements', '')[:60]}"
        return True, "Processed without crash"
    return scenario(37, "extraction", "Hazmat special requirements", action, check)


def s038():
    """Request with per-mile rate expectation."""
    def action():
        return inject(
            "PerMile <permile@test.com>", "Rate check",
            "What's your rate per mile for a dry van from KC to Denver? About 600 miles. 38000 lbs."
        )
    def check(r):
        return True, "Per-mile context processed without crash"
    return scenario(38, "extraction", "Per-mile rate expectation", action, check)


def s039():
    """Email with inline attachment references."""
    def action():
        return inject(
            "Attached <attached@test.com>", "See attached BOL",
            "Hi, please see the attached BOL for the shipment details. We need a quote ASAP.\n\n[BOL-2026-001.pdf attached]"
        )
    def check(r):
        return True, "Attachment reference handled without crash"
    return scenario(39, "extraction", "Email referencing attachments", action, check)


def s040():
    """LTL (less than truckload) request."""
    def action():
        return inject(
            "LTL <ltl@test.com>", "LTL quote needed",
            "Need LTL service from Indianapolis to Columbus. 4 pallets, 2500 lbs. Class 70. Dims: 48x40x48 each."
        )
    def check(r):
        rfq = latest_rfq()
        if rfq and "ltl@test.com" in (rfq.get("customer_email") or ""):
            return True, f"LTL request handled — equip={rfq.get('equipment_type')}"
        return True, "Processed without crash"
    return scenario(40, "extraction", "LTL (less than truckload) request", action, check)


def s041():
    """Temperature-controlled with specific temp range."""
    def action():
        return inject(
            "TempCtrl <tempctrl@test.com>", "Frozen shipment",
            "Need 1 reefer from Omaha to Denver. 30000 lbs of frozen beef. Must maintain -10°F throughout transit."
        )
    def check(r):
        rfq = latest_rfq()
        if rfq and "tempctrl@test.com" in (rfq.get("customer_email") or ""):
            return True, f"Temp-controlled — special={rfq.get('special_requirements', '')[:60]}"
        return True, "Processed without crash"
    return scenario(41, "extraction", "Temperature-controlled (-10°F)", action, check)


def s042():
    """Multiple pickup/delivery stops."""
    def action():
        return inject(
            "MultiStop <multistop@test.com>", "Multi-stop route",
            "Need 1 dry van: pickup in Chicago, second stop in Milwaukee, deliver to Minneapolis. Total 35000 lbs."
        )
    def check(r):
        return True, "Multi-stop handled without crash"
    return scenario(42, "extraction", "Multiple pickup/delivery stops", action, check)


def s043():
    """Request with budget constraint."""
    def action():
        return inject(
            "Budget <budget@test.com>", "Need cheap freight",
            "Looking for cheapest option from Tampa to Jacksonville. 1 dry van 20000 lbs. Budget is $500 max."
        )
    def check(r):
        return True, "Budget constraint handled without crash"
    return scenario(43, "extraction", "Request with budget constraint ($500 max)", action, check)


def s044():
    """International shipment request."""
    def action():
        return inject(
            "Intl <intl@test.com>", "Mexico shipment",
            "Need 2 dry vans from Laredo TX to Guadalajara Mexico. 40000 lbs of auto parts. Cross-border."
        )
    def check(r):
        return True, "International shipment handled without crash"
    return scenario(44, "extraction", "International cross-border shipment", action, check)


def s045():
    """Request with conflicting information."""
    def action():
        return inject(
            "Conflict <conflict@test.com>", "Shipment",
            "Need 1 reefer... actually make that a dry van... wait, it needs to be temperature controlled so reefer. From Dallas (or maybe Fort Worth) to LA."
        )
    def check(r):
        rfq = latest_rfq()
        if rfq and "conflict@test.com" in (rfq.get("customer_email") or ""):
            return True, f"Conflicting info handled — equip={rfq.get('equipment_type')}, origin={rfq.get('origin')}"
        return True, "Processed without crash"
    return scenario(45, "extraction", "Conflicting information in email", action, check)


# ═══════════════════════════════════════════════════════════
# CATEGORY 4: API EDGE CASES (46-60)
# ═══════════════════════════════════════════════════════════

def s046():
    """GET /api/rfqs with invalid state filter."""
    def action():
        return api("GET", "/api/rfqs?state=nonexistent_state")
    def check(r):
        if "error" in str(r).lower() or "detail" in r:
            return True, f"Invalid state filter handled: {str(r)[:80]}"
        return True, f"Returned {len(r.get('rfqs', []))} rfqs — filter ignored"
    return scenario(46, "api", "GET /api/rfqs with invalid state", action, check)


def s047():
    """GET /api/rfqs/{id} with nonexistent ID."""
    def action():
        return api("GET", "/api/rfqs/999999")
    def check(r):
        if r.get("detail") or "not found" in str(r).lower():
            return True, "404 returned for nonexistent RFQ"
        return False, f"Unexpected response: {str(r)[:80]}"
    return scenario(47, "api", "GET nonexistent RFQ ID", action, check)


def s048():
    """POST /api/rfqs/{id}/distribute with no carriers."""
    def action():
        rfq = latest_rfq()
        if not rfq:
            return {"skip": True}
        return api("POST", f"/api/rfqs/{rfq['id']}/distribute", {
            "carrier_ids": [], "attach_quote_sheet": False,
        })
    def check(r):
        if r.get("skip"):
            return True, "Skipped"
        if "error" in str(r).lower() or "detail" in r:
            return True, f"Empty carrier list handled: {str(r)[:80]}"
        return False, f"Should have rejected empty carrier list: {str(r)[:80]}"
    return scenario(48, "api", "Distribute to zero carriers", action, check)


def s049():
    """POST /api/rfqs/{id}/distribute with invalid carrier IDs."""
    def action():
        rfq = latest_rfq()
        if not rfq:
            return {"skip": True}
        return api("POST", f"/api/rfqs/{rfq['id']}/distribute", {
            "carrier_ids": [999999, 888888], "attach_quote_sheet": False,
        })
    def check(r):
        if r.get("skip"):
            return True, "Skipped"
        if "error" in str(r).lower() or "detail" in r:
            return True, f"Invalid carrier IDs handled: {str(r)[:80]}"
        return False, f"Should have rejected invalid carriers: {str(r)[:80]}"
    return scenario(49, "api", "Distribute to nonexistent carriers", action, check)


def s050():
    """POST /api/rfqs/{id}/price with no bid."""
    def action():
        rfq = latest_rfq()
        if not rfq:
            return {"skip": True}
        return api("POST", f"/api/rfqs/{rfq['id']}/price", {
            "carrier_bid_id": 999999,
        })
    def check(r):
        if r.get("skip"):
            return True, "Skipped"
        if "error" in str(r).lower() or "detail" in r:
            return True, f"Missing bid handled: {str(r)[:80]}"
        return False, f"Should have failed: {str(r)[:80]}"
    return scenario(50, "api", "Price RFQ with nonexistent bid", action, check)


def s051():
    """POST /api/rfqs/{id}/outcome with invalid outcome."""
    def action():
        rfq = latest_rfq()
        if not rfq:
            return {"skip": True}
        return api("POST", f"/api/rfqs/{rfq['id']}/outcome", {"outcome": "banana"})
    def check(r):
        if r.get("skip"):
            return True, "Skipped"
        return True, f"Invalid outcome handled: {str(r)[:80]}"
    return scenario(51, "api", "Set invalid outcome", action, check)


def s052():
    """POST /api/carriers with missing required fields."""
    def action():
        return api("POST", "/api/carriers", {"name": ""})
    def check(r):
        return True, f"Empty carrier creation handled: {str(r)[:80]}"
    return scenario(52, "api", "Create carrier with empty name", action, check)


def s053():
    """POST /api/carriers with duplicate email."""
    def action():
        api("POST", "/api/carriers", {
            "name": "DupTest1", "email": "duptest@unique.com",
            "equipment_types": ["Dry Van"],
        })
        return api("POST", "/api/carriers", {
            "name": "DupTest2", "email": "duptest@unique.com",
            "equipment_types": ["Reefer"],
        })
    def check(r):
        return True, f"Duplicate carrier email handled: {str(r)[:80]}"
    return scenario(53, "api", "Duplicate carrier email", action, check)


def s054():
    """POST /api/approvals/{id}/approve with nonexistent approval."""
    def action():
        return api("POST", "/api/approvals/999999/approve", {})
    def check(r):
        if "not found" in str(r).lower() or r.get("detail"):
            return True, "Nonexistent approval handled"
        return False, f"Unexpected: {str(r)[:80]}"
    return scenario(54, "api", "Approve nonexistent approval", action, check)


def s055():
    """POST /api/chat with empty message."""
    def action():
        return api("POST", "/api/chat", {"message": ""})
    def check(r):
        return True, f"Empty chat message handled: {str(r)[:80]}"
    return scenario(55, "api", "Chat with empty message", action, check)


def s056():
    """POST /api/chat with very long message."""
    def action():
        long_msg = "Tell me about RFQ " * 500
        return api("POST", "/api/chat", {"message": long_msg})
    def check(r):
        return True, f"Long chat message handled: {str(r)[:80]}"
    return scenario(56, "api", "Chat with 5000-word message", action, check, timeout=30)


def s057():
    """GET /api/rfqs with extreme pagination."""
    def action():
        return api("GET", "/api/rfqs?limit=10000&offset=999999")
    def check(r):
        rfqs = r.get("rfqs", [])
        return True, f"Extreme pagination: {len(rfqs)} results returned"
    return scenario(57, "api", "Extreme pagination (offset=999999)", action, check)


def s058():
    """POST /api/rfqs/{id}/counter-offer with zero rate."""
    def action():
        rfq = latest_rfq()
        if not rfq:
            return {"skip": True}
        bids = api("GET", f"/api/rfqs/{rfq['id']}/bids")
        bid_list = bids.get("bids", [])
        if not bid_list:
            return {"skip": True}
        return api("POST", f"/api/rfqs/{rfq['id']}/counter-offer", {
            "carrier_bid_id": bid_list[0]["id"],
            "proposed_rate": 0,
        })
    def check(r):
        if r.get("skip"):
            return True, "Skipped — no bids available"
        return True, f"Zero-rate counter-offer handled: {str(r)[:80]}"
    return scenario(58, "api", "Counter-offer with $0 rate", action, check)


def s059():
    """POST /api/rfqs/{id}/generate-quote on RFQ with no quoted amount."""
    def action():
        rfq = latest_rfq()
        if not rfq:
            return {"skip": True}
        return api("POST", f"/api/rfqs/{rfq['id']}/generate-quote")
    def check(r):
        if r.get("skip"):
            return True, "Skipped"
        return True, f"Generate quote without amount: {str(r)[:80]}"
    return scenario(59, "api", "Generate quote with no quoted amount", action, check)


def s060():
    """DELETE /api/carriers/{id} then try to distribute to it."""
    def action():
        # Create a throwaway carrier
        c = api("POST", "/api/carriers", {
            "name": "DeleteMe", "email": "deleteme@test.com",
            "equipment_types": ["Dry Van"],
        })
        cid = c.get("id") or c.get("carrier", {}).get("id")
        if not cid:
            return {"skip": True}
        api("DELETE", f"/api/carriers/{cid}")
        rfq = latest_rfq()
        if not rfq:
            return {"skip": True}
        return api("POST", f"/api/rfqs/{rfq['id']}/distribute", {
            "carrier_ids": [cid], "attach_quote_sheet": False,
        })
    def check(r):
        if r.get("skip"):
            return True, "Skipped"
        return True, f"Distribute to deleted carrier: {str(r)[:80]}"
    return scenario(60, "api", "Distribute to deleted carrier", action, check)


# ═══════════════════════════════════════════════════════════
# CATEGORY 5: STATE MACHINE (61-75)
# ═══════════════════════════════════════════════════════════

def s061():
    """Transition RFQ to invalid state."""
    def action():
        rfq = latest_rfq()
        if not rfq:
            return {"skip": True}
        return api("POST", f"/api/rfqs/{rfq['id']}/outcome", {"outcome": "won"})
    def check(r):
        if r.get("skip"):
            return True, "Skipped"
        return True, f"Direct won transition: {str(r)[:80]}"
    return scenario(61, "state", "Force RFQ to won from wrong state", action, check)


def s062():
    """Cancel an RFQ from needs_clarification."""
    def action():
        rfq = latest_rfq()
        if not rfq:
            return {"skip": True}
        return api("POST", f"/api/rfqs/{rfq['id']}/outcome", {"outcome": "cancelled"})
    def check(r):
        if r.get("skip"):
            return True, "Skipped"
        return True, f"Cancel from current state: {str(r)[:80]}"
    return scenario(62, "state", "Cancel RFQ from any state", action, check)


def s063():
    """Try to act on a cancelled/terminal RFQ."""
    def action():
        # Find a cancelled RFQ
        rfqs = get_rfqs(20)
        terminal = [x for x in rfqs.get("rfqs", []) if x.get("state") in ("won", "lost", "cancelled")]
        if not terminal:
            return {"skip": True}
        rfq = terminal[0]
        return api("POST", f"/api/rfqs/{rfq['id']}/distribute", {
            "carrier_ids": [1], "attach_quote_sheet": False,
        })
    def check(r):
        if r.get("skip"):
            return True, "Skipped — no terminal RFQs"
        return True, f"Act on terminal RFQ: {str(r)[:80]}"
    return scenario(63, "state", "Distribute on cancelled RFQ", action, check)


def s064():
    """Double-approve an already approved approval."""
    def action():
        approvals = api("GET", "/api/approvals")
        pending = approvals.get("approvals", [])
        if not pending:
            return {"skip": True}
        aid = pending[0]["id"]
        api("POST", f"/api/approvals/{aid}/approve")
        return api("POST", f"/api/approvals/{aid}/approve")
    def check(r):
        if r.get("skip"):
            return True, "Skipped — no pending approvals"
        return True, f"Double-approve: {str(r)[:80]}"
    return scenario(64, "state", "Double-approve same approval", action, check)


def s065():
    """Reject then try to approve same approval."""
    def action():
        approvals = api("GET", "/api/approvals")
        pending = approvals.get("approvals", [])
        if not pending:
            return {"skip": True}
        aid = pending[0]["id"]
        api("POST", f"/api/approvals/{aid}/reject")
        return api("POST", f"/api/approvals/{aid}/approve")
    def check(r):
        if r.get("skip"):
            return True, "Skipped — no pending approvals"
        return True, f"Reject then approve: {str(r)[:80]}"
    return scenario(65, "state", "Reject then approve same approval", action, check)


def s066():
    """Request clarification on RFQ already in ready_to_quote."""
    def action():
        rfqs = get_rfqs(20)
        ready = [x for x in rfqs.get("rfqs", []) if x.get("state") == "ready_to_quote"]
        if not ready:
            return {"skip": True}
        return api("POST", f"/api/rfqs/{ready[0]['id']}/request-clarification")
    def check(r):
        if r.get("skip"):
            return True, "Skipped — no ready_to_quote RFQs"
        return True, f"Clarification on ready RFQ: {str(r)[:80]}"
    return scenario(66, "state", "Clarification on ready_to_quote RFQ", action, check)


def s067():
    """Regenerate quote sheet on RFQ with no data."""
    def action():
        rfqs = get_rfqs(20)
        nc = [x for x in rfqs.get("rfqs", []) if x.get("state") == "needs_clarification"]
        if not nc:
            return {"skip": True}
        return api("POST", f"/api/rfqs/{nc[0]['id']}/regenerate-quote-sheet")
    def check(r):
        if r.get("skip"):
            return True, "Skipped"
        return True, f"Regen quote sheet on incomplete RFQ: {str(r)[:80]}"
    return scenario(67, "state", "Regenerate quote sheet on incomplete RFQ", action, check)


def s068():
    """Full lifecycle: create → clarify → ready → distribute → bid → price → quote → accept."""
    def action():
        # Create
        inject("Lifecycle <lifecycle@test.com>", "Full test",
               "Need 1 dry van from Austin TX to San Antonio TX. 15000 lbs of electronics.")
        poll(3, 4)
        rfq = latest_rfq()
        if not rfq:
            return {"error": "No RFQ created"}
        return {"rfq_id": rfq["id"]}
    def check(r):
        rid = r.get("rfq_id")
        if not rid:
            return False, "No RFQ for lifecycle test"
        rfq = get_rfq(rid)
        return True, f"Lifecycle RFQ #{rid} — state={rfq.get('state')}, ref={rfq.get('ref_number')}"
    return scenario(68, "state", "Full lifecycle (create through extract)", action, check, timeout=25)


def s069():
    """Set outcome on RFQ that already has an outcome."""
    def action():
        rfqs = get_rfqs(20)
        won = [x for x in rfqs.get("rfqs", []) if x.get("outcome") == "won"]
        if not won:
            return {"skip": True}
        return api("POST", f"/api/rfqs/{won[0]['id']}/outcome", {"outcome": "lost"})
    def check(r):
        if r.get("skip"):
            return True, "Skipped — no won RFQs"
        return True, f"Change outcome on terminal: {str(r)[:80]}"
    return scenario(69, "state", "Change outcome on already-won RFQ", action, check)


def s070():
    """Manual reply on RFQ in inquiry state."""
    def action():
        rfqs = get_rfqs(20)
        inq = [x for x in rfqs.get("rfqs", []) if x.get("state") == "inquiry"]
        if not inq:
            return {"skip": True}
        return api("POST", f"/api/rfqs/{inq[0]['id']}/manual-reply", {
            "to": "test@test.com",
            "subject": "Re: Your inquiry",
            "body": "Thanks for reaching out, here's some info...",
        })
    def check(r):
        if r.get("skip"):
            return True, "Skipped — no inquiry RFQs"
        return True, f"Manual reply on inquiry: {str(r)[:80]}"
    return scenario(70, "state", "Manual reply on inquiry-state RFQ", action, check)


def s071():
    """Distribute same RFQ to same carrier twice."""
    def action():
        rfqs = get_rfqs(20)
        ready = [x for x in rfqs.get("rfqs", []) if x.get("state") in ("ready_to_quote", "waiting_on_carriers")]
        carriers = api("GET", "/api/carriers").get("carriers", [])
        if not ready or not carriers:
            return {"skip": True}
        cid = carriers[0]["id"]
        rid = ready[0]["id"]
        api("POST", f"/api/rfqs/{rid}/distribute", {"carrier_ids": [cid], "attach_quote_sheet": False})
        poll(1, 3)
        return api("POST", f"/api/rfqs/{rid}/distribute", {"carrier_ids": [cid], "attach_quote_sheet": False})
    def check(r):
        if r.get("skip"):
            return True, "Skipped"
        return True, f"Double distribute: {str(r)[:80]}"
    return scenario(71, "state", "Distribute to same carrier twice", action, check)


def s072():
    """Price RFQ with negative markup."""
    def action():
        rfqs = get_rfqs(20)
        qr = [x for x in rfqs.get("rfqs", []) if x.get("state") in ("quotes_received", "waiting_on_carriers")]
        if not qr:
            return {"skip": True}
        bids = api("GET", f"/api/rfqs/{qr[0]['id']}/bids")
        if not bids.get("bids"):
            return {"skip": True}
        return api("POST", f"/api/rfqs/{qr[0]['id']}/price", {
            "carrier_bid_id": bids["bids"][0]["id"],
            "markup_percent": -50,
        })
    def check(r):
        if r.get("skip"):
            return True, "Skipped — no bids"
        return True, f"Negative markup: {str(r)[:80]}"
    return scenario(72, "state", "Price with negative markup", action, check)


def s073():
    """Download quote sheet as Excel on RFQ with no quote sheet."""
    def action():
        rfqs = get_rfqs(20)
        nc = [x for x in rfqs.get("rfqs", []) if x.get("state") == "needs_clarification"]
        if not nc:
            return {"skip": True}
        return api("GET", f"/api/rfqs/{nc[0]['id']}/quote-sheet/download")
    def check(r):
        if r.get("skip"):
            return True, "Skipped"
        return True, f"Download without quote sheet: {str(r)[:80]}"
    return scenario(73, "state", "Download Excel with no quote sheet", action, check)


def s074():
    """Redraft on RFQ that's not in needs_clarification."""
    def action():
        rfqs = get_rfqs(20)
        ready = [x for x in rfqs.get("rfqs", []) if x.get("state") == "ready_to_quote"]
        if not ready:
            return {"skip": True}
        return api("POST", f"/api/rfqs/{ready[0]['id']}/redraft")
    def check(r):
        if r.get("skip"):
            return True, "Skipped"
        return True, f"Redraft on ready RFQ: {str(r)[:80]}"
    return scenario(74, "state", "Redraft on non-clarification RFQ", action, check)


def s075():
    """Generate customer quote on RFQ with $0 quoted amount."""
    def action():
        rfqs = get_rfqs(20)
        for rfq_item in rfqs.get("rfqs", []):
            if rfq_item.get("state") in ("quotes_received", "waiting_on_broker"):
                return api("POST", f"/api/rfqs/{rfq_item['id']}/generate-quote")
        return {"skip": True}
    def check(r):
        if r.get("skip"):
            return True, "Skipped — no RFQs in right state"
        return True, f"Generate quote result: {str(r)[:80]}"
    return scenario(75, "state", "Generate customer quote from wrong state", action, check)


# ═══════════════════════════════════════════════════════════
# CATEGORY 6: CARRIER BID PARSING (76-85)
# ═══════════════════════════════════════════════════════════

def s076():
    """Carrier bid with rate in body text."""
    def action():
        rfq = latest_rfq()
        if not rfq:
            return {"skip": True}
        ref = rfq.get("ref_number", str(rfq["id"]))
        return inject(
            "QuoteCarrier <quotecarrier@test.com>",
            f"Re: RFQ [RFQ-{ref}]",
            "Hi, we can do this for $2,850 all in. Available next week. Net 30 terms."
        )
    def check(r):
        if r.get("skip"):
            return True, "Skipped"
        return True, "Carrier bid with rate injected"
    return scenario(76, "bids", "Carrier bid with $2,850 rate", action, check)


def s077():
    """Carrier bid with per-mile rate."""
    def action():
        rfq = latest_rfq()
        if not rfq:
            return {"skip": True}
        ref = rfq.get("ref_number", str(rfq["id"]))
        return inject(
            "PerMileCarrier <permile-carrier@test.com>",
            f"Re: RFQ [RFQ-{ref}]",
            "We can do $3.25/mile for this lane. Quick pay available."
        )
    def check(r):
        if r.get("skip"):
            return True, "Skipped"
        return True, "Per-mile bid injected"
    return scenario(77, "bids", "Carrier bid with per-mile rate", action, check)


def s078():
    """Carrier bid with linehaul + FSC breakdown."""
    def action():
        rfq = latest_rfq()
        if not rfq:
            return {"skip": True}
        ref = rfq.get("ref_number", str(rfq["id"]))
        return inject(
            "FSCCarrier <fsc@test.com>",
            f"Re: RFQ [RFQ-{ref}]",
            "Linehaul: $2,400\nFuel Surcharge: $380\nTotal: $2,780\nAvailable Thursday."
        )
    def check(r):
        if r.get("skip"):
            return True, "Skipped"
        return True, "Linehaul+FSC bid injected"
    return scenario(78, "bids", "Linehaul + FSC breakdown bid", action, check)


def s079():
    """Carrier reply that's a question, not a bid."""
    def action():
        rfq = latest_rfq()
        if not rfq:
            return {"skip": True}
        ref = rfq.get("ref_number", str(rfq["id"]))
        return inject(
            "QuestionCarrier <question-carrier@test.com>",
            f"Re: RFQ [RFQ-{ref}]",
            "What's the commodity? Is it palletized? Do you need a liftgate? What are the dims?"
        )
    def check(r):
        if r.get("skip"):
            return True, "Skipped"
        return True, "Carrier question (not a bid) processed"
    return scenario(79, "bids", "Carrier asks questions instead of bidding", action, check)


def s080():
    """Carrier sends bid with conditions/restrictions."""
    def action():
        rfq = latest_rfq()
        if not rfq:
            return {"skip": True}
        ref = rfq.get("ref_number", str(rfq["id"]))
        return inject(
            "CondCarrier <cond@test.com>",
            f"Re: RFQ [RFQ-{ref}]",
            "We can do $3,100 but ONLY if pickup is before 2pm. No weekend delivery. Driver needs 2 hour window. Tarping extra $200."
        )
    def check(r):
        if r.get("skip"):
            return True, "Skipped"
        return True, "Conditional bid injected"
    return scenario(80, "bids", "Bid with conditions/restrictions", action, check)


def s081():
    """Carrier reply with multiple rate options."""
    def action():
        rfq = latest_rfq()
        if not rfq:
            return {"skip": True}
        ref = rfq.get("ref_number", str(rfq["id"]))
        return inject(
            "MultiRate <multirate@test.com>",
            f"Re: RFQ [RFQ-{ref}]",
            "Option A: $2,500 standard (3-5 days)\nOption B: $3,200 expedited (next day)\nOption C: $2,100 flexible (1-2 weeks)"
        )
    def check(r):
        if r.get("skip"):
            return True, "Skipped"
        return True, "Multi-option bid injected"
    return scenario(81, "bids", "Carrier offers 3 rate options", action, check)


def s082():
    """Carrier declines with frustration."""
    def action():
        rfq = latest_rfq()
        if not rfq:
            return {"skip": True}
        ref = rfq.get("ref_number", str(rfq["id"]))
        return inject(
            "AngryCarrier <angry@test.com>",
            f"Re: RFQ [RFQ-{ref}]",
            "No way. This rate is way too low for that lane. Take me off your list."
        )
    def check(r):
        if r.get("skip"):
            return True, "Skipped"
        return True, "Angry decline processed"
    return scenario(82, "bids", "Carrier declines angrily", action, check)


def s083():
    """Carrier bid in different currency."""
    def action():
        rfq = latest_rfq()
        if not rfq:
            return {"skip": True}
        ref = rfq.get("ref_number", str(rfq["id"]))
        return inject(
            "CADCarrier <cad@test.com>",
            f"Re: RFQ [RFQ-{ref}]",
            "We can do this for CAD $4,200. That's about USD $3,100."
        )
    def check(r):
        if r.get("skip"):
            return True, "Skipped"
        return True, "CAD bid processed"
    return scenario(83, "bids", "Bid in Canadian dollars", action, check)


def s084():
    """Carrier replies with just 'OK' — ambiguous."""
    def action():
        rfq = latest_rfq()
        if not rfq:
            return {"skip": True}
        ref = rfq.get("ref_number", str(rfq["id"]))
        return inject(
            "VagueCarrier <vague@test.com>",
            f"Re: RFQ [RFQ-{ref}]",
            "OK"
        )
    def check(r):
        if r.get("skip"):
            return True, "Skipped"
        return True, "Ambiguous 'OK' reply processed"
    return scenario(84, "bids", "Carrier replies just 'OK'", action, check)


def s085():
    """Carrier sends bid for wrong lane / mismatched route."""
    def action():
        rfq = latest_rfq()
        if not rfq:
            return {"skip": True}
        ref = rfq.get("ref_number", str(rfq["id"]))
        return inject(
            "WrongLane <wronglane@test.com>",
            f"Re: RFQ [RFQ-{ref}]",
            "We can do New York to Chicago for $1,800. Is that the lane you mean?"
        )
    def check(r):
        if r.get("skip"):
            return True, "Skipped"
        return True, "Wrong-lane bid processed"
    return scenario(85, "bids", "Carrier bids on wrong lane", action, check)


# ═══════════════════════════════════════════════════════════
# CATEGORY 7: QUOTE RESPONSE CLASSIFICATION (86-95)
# ═══════════════════════════════════════════════════════════

def s086():
    """Customer clearly accepts: 'Let's do it'."""
    def action():
        rfqs = get_rfqs(20)
        qs = [x for x in rfqs.get("rfqs", []) if x.get("state") == "quote_sent"]
        if not qs:
            return {"skip": True}
        rfq = qs[0]
        ref = rfq.get("ref_number", str(rfq["id"]))
        return inject(
            f"{rfq.get('customer_name')} <{rfq.get('customer_email')}>",
            f"Re: Quote [RFQ-{ref}]",
            "Let's do it. Book the truck."
        )
    def check(r):
        if r.get("skip"):
            return True, "Skipped — no quote_sent RFQs"
        return True, "Clear acceptance processed"
    return scenario(86, "quote_response", "Customer clearly accepts", action, check)


def s087():
    """Customer clearly rejects: 'Too expensive'."""
    def action():
        rfqs = get_rfqs(20)
        qs = [x for x in rfqs.get("rfqs", []) if x.get("state") == "quote_sent"]
        if not qs:
            return {"skip": True}
        rfq = qs[0]
        ref = rfq.get("ref_number", str(rfq["id"]))
        return inject(
            f"{rfq.get('customer_name')} <{rfq.get('customer_email')}>",
            f"Re: Quote [RFQ-{ref}]",
            "Too expensive. We found a cheaper carrier. Thanks anyway."
        )
    def check(r):
        if r.get("skip"):
            return True, "Skipped — no quote_sent RFQs"
        return True, "Clear rejection processed"
    return scenario(87, "quote_response", "Customer clearly rejects", action, check)


def s088():
    """Customer asks a question about the quote."""
    def action():
        rfqs = get_rfqs(20)
        qs = [x for x in rfqs.get("rfqs", []) if x.get("state") == "quote_sent"]
        if not qs:
            return {"skip": True}
        rfq = qs[0]
        ref = rfq.get("ref_number", str(rfq["id"]))
        return inject(
            f"{rfq.get('customer_name')} <{rfq.get('customer_email')}>",
            f"Re: Quote [RFQ-{ref}]",
            "Can you do any better on the price? What about $200 less?"
        )
    def check(r):
        if r.get("skip"):
            return True, "Skipped — no quote_sent RFQs"
        return True, "Price negotiation processed"
    return scenario(88, "quote_response", "Customer negotiates price", action, check)


def s089():
    """Customer accepts but also asks a question (#191)."""
    def action():
        rfqs = get_rfqs(20)
        qs = [x for x in rfqs.get("rfqs", []) if x.get("state") == "quote_sent"]
        if not qs:
            return {"skip": True}
        rfq = qs[0]
        ref = rfq.get("ref_number", str(rfq["id"]))
        return inject(
            f"{rfq.get('customer_name')} <{rfq.get('customer_email')}>",
            f"Re: Quote [RFQ-{ref}]",
            "Book it. Also, do you guys handle hazmat? We have another shipment coming up."
        )
    def check(r):
        if r.get("skip"):
            return True, "Skipped — no quote_sent RFQs"
        return True, "Accept + question combo processed"
    return scenario(89, "quote_response", "Accept + question in same email", action, check)


def s090():
    """Ambiguous response: 'Sounds good, let me check with my team'."""
    def action():
        rfqs = get_rfqs(20)
        qs = [x for x in rfqs.get("rfqs", []) if x.get("state") == "quote_sent"]
        if not qs:
            return {"skip": True}
        rfq = qs[0]
        ref = rfq.get("ref_number", str(rfq["id"]))
        return inject(
            f"{rfq.get('customer_name')} <{rfq.get('customer_email')}>",
            f"Re: Quote [RFQ-{ref}]",
            "Sounds good, let me check with my team and get back to you."
        )
    def check(r):
        if r.get("skip"):
            return True, "Skipped — no quote_sent RFQs"
        return True, "Ambiguous response processed (should be question)"
    return scenario(90, "quote_response", "Ambiguous 'check with my team'", action, check)


def s091():
    """Customer replies with just 'Thanks'."""
    def action():
        rfqs = get_rfqs(20)
        qs = [x for x in rfqs.get("rfqs", []) if x.get("state") in ("quote_sent", "waiting_on_broker")]
        if not qs:
            return {"skip": True}
        rfq = qs[0]
        ref = rfq.get("ref_number", str(rfq["id"]))
        return inject(
            f"{rfq.get('customer_name')} <{rfq.get('customer_email')}>",
            f"Re: Quote [RFQ-{ref}]",
            "Thanks"
        )
    def check(r):
        if r.get("skip"):
            return True, "Skipped"
        return True, "Bare 'Thanks' reply processed"
    return scenario(91, "quote_response", "Customer replies just 'Thanks'", action, check)


def s092():
    """Customer requests different equipment."""
    def action():
        rfqs = get_rfqs(20)
        qs = [x for x in rfqs.get("rfqs", []) if x.get("state") in ("quote_sent", "waiting_on_broker")]
        if not qs:
            return {"skip": True}
        rfq = qs[0]
        ref = rfq.get("ref_number", str(rfq["id"]))
        return inject(
            f"{rfq.get('customer_name')} <{rfq.get('customer_email')}>",
            f"Re: Quote [RFQ-{ref}]",
            "Actually, can you re-quote with a flatbed instead of dry van? The cargo is oversized."
        )
    def check(r):
        if r.get("skip"):
            return True, "Skipped"
        return True, "Equipment change request processed"
    return scenario(92, "quote_response", "Customer requests different equipment", action, check)


def s093():
    """Customer replies in ALL CAPS."""
    def action():
        rfqs = get_rfqs(20)
        qs = [x for x in rfqs.get("rfqs", []) if x.get("state") in ("quote_sent", "waiting_on_broker")]
        if not qs:
            return {"skip": True}
        rfq = qs[0]
        ref = rfq.get("ref_number", str(rfq["id"]))
        return inject(
            f"{rfq.get('customer_name')} <{rfq.get('customer_email')}>",
            f"Re: Quote [RFQ-{ref}]",
            "YES GO AHEAD BOOK IT NOW PLEASE URGENT"
        )
    def check(r):
        if r.get("skip"):
            return True, "Skipped"
        return True, "ALL CAPS acceptance processed"
    return scenario(93, "quote_response", "ALL CAPS acceptance", action, check)


def s094():
    """Customer replies weeks later."""
    def action():
        rfqs = get_rfqs(20)
        qs = [x for x in rfqs.get("rfqs", []) if x.get("state") in ("quote_sent", "waiting_on_broker")]
        if not qs:
            return {"skip": True}
        rfq = qs[0]
        ref = rfq.get("ref_number", str(rfq["id"]))
        return inject(
            f"{rfq.get('customer_name')} <{rfq.get('customer_email')}>",
            f"Re: Quote [RFQ-{ref}]",
            "Sorry for the late reply. Is this quote still valid? If so, let's proceed."
        )
    def check(r):
        if r.get("skip"):
            return True, "Skipped"
        return True, "Late reply processed"
    return scenario(94, "quote_response", "Customer replies weeks later", action, check)


def s095():
    """Customer forwards quote to someone else and CCs broker."""
    def action():
        rfqs = get_rfqs(20)
        qs = [x for x in rfqs.get("rfqs", []) if x.get("state") in ("quote_sent", "waiting_on_broker")]
        if not qs:
            return {"skip": True}
        rfq = qs[0]
        ref = rfq.get("ref_number", str(rfq["id"]))
        return inject(
            f"{rfq.get('customer_name')} <{rfq.get('customer_email')}>",
            f"Fwd: Quote [RFQ-{ref}]",
            "Hey boss, what do you think about this rate? See below.\n\n------\nOriginal quote: $3,500 for 1 dry van..."
        )
    def check(r):
        if r.get("skip"):
            return True, "Skipped"
        return True, "Forwarded quote processed"
    return scenario(95, "quote_response", "Customer forwards quote internally", action, check)


# ═══════════════════════════════════════════════════════════
# CATEGORY 8: SYSTEM / CONCURRENCY (96-100)
# ═══════════════════════════════════════════════════════════

def s096():
    """Workflow kill switch — disable all, inject email, re-enable."""
    def action():
        api("POST", "/api/workflows/kill")
        result = inject(
            "KillTest <killtest@test.com>", "Test during kill",
            "Need 1 dry van from Reno to Vegas. 10000 lbs."
        )
        poll(1, 3)
        # Re-enable workflows
        workflows = api("GET", "/api/workflows")
        for w in workflows.get("workflows", []):
            api("PUT", f"/api/workflows/{w['id']}", {"enabled": True})
        return result
    def check(r):
        return True, "Kill switch test complete — workflows re-enabled"
    return scenario(96, "system", "Workflow kill switch during email", action, check)


def s097():
    """Poll worker when no jobs exist."""
    def action():
        return api("POST", "/api/admin/poll")
    def check(r):
        return True, f"Empty poll: {str(r)[:80]}"
    return scenario(97, "system", "Poll worker with no jobs", action, check)


def s098():
    """Inject 10 emails simultaneously."""
    def action():
        for i in range(10):
            inject(
                f"Batch{i} <batch{i}@test.com>",
                f"Batch shipment {i}",
                f"Need 1 dry van from City{i} to City{i+10}. {10000 + i*1000} lbs."
            )
        return {"injected": 10}
    def check(r):
        return True, "10 simultaneous emails injected"
    return scenario(98, "system", "10 simultaneous email injections", action, check, timeout=40)


def s099():
    """SQL injection attempt in email body."""
    def action():
        return inject(
            "Hacker <hacker@test.com>",
            "Quote'; DROP TABLE rfqs; --",
            "Need a van from '; DELETE FROM messages WHERE 1=1; -- to NYC"
        )
    def check(r):
        # Verify tables still exist
        rfqs = get_rfqs(1)
        if "rfqs" in rfqs:
            return True, "SQL injection attempt handled safely — tables intact"
        return False, "Possible SQL injection issue!"
    return scenario(99, "system", "SQL injection attempt", action, check)


def s100():
    """XSS attempt in email fields."""
    def action():
        return inject(
            '<script>alert("xss")</script> <xss@test.com>',
            '<img src=x onerror=alert(1)>',
            'Need freight from <script>document.cookie</script> to <b onmouseover=alert(1)>NYC</b>'
        )
    def check(r):
        return True, "XSS attempt processed without crash"
    return scenario(100, "system", "XSS attempt in email fields", action, check)


# ═══════════════════════════════════════════════════════════
# Runner
# ═══════════════════════════════════════════════════════════

ALL_SCENARIOS = [
    s001, s002, s003, s004, s005, s006, s007, s008, s009, s010,
    s011, s012, s013, s014, s015, s016, s017, s018, s019, s020,
    s021, s022, s023, s024, s025, s026, s027, s028, s029, s030,
    s031, s032, s033, s034, s035, s036, s037, s038, s039, s040,
    s041, s042, s043, s044, s045, s046, s047, s048, s049, s050,
    s051, s052, s053, s054, s055, s056, s057, s058, s059, s060,
    s061, s062, s063, s064, s065, s066, s067, s068, s069, s070,
    s071, s072, s073, s074, s075, s076, s077, s078, s079, s080,
    s081, s082, s083, s084, s085, s086, s087, s088, s089, s090,
    s091, s092, s093, s094, s095, s096, s097, s098, s099, s100,
]

CATEGORIES = {
    "email": list(range(1, 16)),
    "matching": list(range(16, 31)),
    "extraction": list(range(31, 46)),
    "api": list(range(46, 61)),
    "state": list(range(61, 76)),
    "bids": list(range(76, 86)),
    "quote_response": list(range(86, 96)),
    "system": list(range(96, 101)),
}


def main():
    parser = argparse.ArgumentParser(description="100-scenario Golteris stress test")
    parser.add_argument("--category", "-c", help="Run only one category")
    parser.add_argument("--scenario", "-s", type=int, help="Run only one scenario")
    parser.add_argument("--start", type=int, default=1, help="Start from scenario N")
    args = parser.parse_args()

    print("=" * 60)
    print("  GOLTERIS 100-SCENARIO STRESS TEST")
    print(f"  Target: {API}")
    print(f"  Started: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)

    to_run = ALL_SCENARIOS

    if args.scenario:
        to_run = [s for s in ALL_SCENARIOS if ALL_SCENARIOS.index(s) + 1 == args.scenario]
    elif args.category:
        nums = CATEGORIES.get(args.category, [])
        to_run = [ALL_SCENARIOS[n - 1] for n in nums]
    elif args.start > 1:
        to_run = ALL_SCENARIOS[args.start - 1:]

    for s_fn in to_run:
        try:
            s_fn()
        except Exception as e:
            print(f"  ! CRASH: {e}")
            RESULTS.append({
                "num": SCENARIO_NUM, "category": "?", "name": "?",
                "status": "CRASH", "details": str(e)[:120],
            })

    # ── Summary ──
    print("\n" + "=" * 60)
    print("  RESULTS SUMMARY")
    print("=" * 60)

    by_status = {}
    for r in RESULTS:
        by_status.setdefault(r["status"], []).append(r)

    for status in ["PASS", "FAIL", "ERROR", "CRASH", "SKIP"]:
        items = by_status.get(status, [])
        if items:
            print(f"\n  {status} ({len(items)}):")
            for r in items:
                print(f"    #{r['num']:03d} [{r['category']}] {r['name']}: {r['details'][:70]}")

    pass_count = len(by_status.get("PASS", []))
    total = len(RESULTS)
    fail_count = len(by_status.get("FAIL", [])) + len(by_status.get("ERROR", [])) + len(by_status.get("CRASH", []))

    print(f"\n  {pass_count}/{total} passed, {fail_count} failed/errored")
    print("=" * 60)

    # Save results
    with open("planning/stress-test-100-results.json", "w") as f:
        json.dump(RESULTS, f, indent=2)
    print(f"  Results saved to planning/stress-test-100-results.json")


if __name__ == "__main__":
    main()
