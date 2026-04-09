"""
backend/api/dev.py — Development tools API router (#88).

Provides endpoints for demo/development operations like reseeding the
database. These endpoints are destructive and should not be available
in production without explicit configuration.

Endpoints:
    POST /api/dev/reseed — Clear and reseed all tables with demo data

Called by:
    The Settings page "Reset Demo Data" button.
"""

import logging
from datetime import datetime, timedelta
from decimal import Decimal

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from backend.db.database import get_db
from backend.db.models import (
    AgentRun,
    AgentRunStatus,
    Approval,
    ApprovalStatus,
    ApprovalType,
    AuditEvent,
    Carrier,
    CarrierBid,
    CarrierRfqSend,
    Job,
    Message,
    MessageDirection,
    MessageRoutingStatus,
    RFQ,
    RFQState,
    ReviewQueue,
    Workflow,
)

logger = logging.getLogger("golteris.api.dev")

router = APIRouter(prefix="/api/dev", tags=["dev"])


@router.post("/clear")
def clear_all_data(db: Session = Depends(get_db)):
    """Clear all data without reseeding. Clean slate for live demo."""
    from backend.db.models import AgentCall
    db.query(Job).delete()
    db.query(ReviewQueue).delete()
    db.query(CarrierRfqSend).delete()
    db.query(CarrierBid).delete()
    db.query(AuditEvent).delete()
    db.query(Approval).delete()
    db.query(AgentCall).delete()
    db.query(AgentRun).delete()
    db.query(Message).delete()
    db.query(RFQ).delete()
    db.commit()
    return {"status": "ok", "message": "All data cleared"}


@router.post("/reseed")
def reseed_demo_data(db: Session = Depends(get_db)):
    """
    Clear all data and reseed with realistic Beltmann demo scenarios.

    This is a destructive operation — all existing RFQs, messages, approvals,
    events, bids, and jobs are deleted and replaced with fresh demo data.

    The seed data creates a realistic snapshot of a broker's day:
    - 10 RFQs in various states across the lifecycle
    - Inbound messages with routing badges (attached, new_rfq, needs_review, ignored)
    - Pending approvals for the approval modal
    - Carrier bids for bid comparison
    - Agent runs for time saved calculations
    - Audit events for the activity feed and RFQ timelines
    """
    now = datetime.utcnow()

    # --- Clear all tables (order matters due to foreign keys) ---
    db.query(Job).delete()
    db.query(ReviewQueue).delete()
    db.query(CarrierRfqSend).delete()
    db.query(CarrierBid).delete()
    db.query(AuditEvent).delete()
    db.query(Approval).delete()
    db.query(AgentRun).delete()
    db.query(Message).delete()
    db.query(RFQ).delete()
    db.query(Carrier).delete()
    db.query(Workflow).delete()
    # Don't delete users — preserve auth accounts
    db.commit()

    # --- Seed default user if none exist ---
    from backend.db.models import User
    from backend.auth import hash_password
    if db.query(User).count() == 0:
        db.add(User(
            email="jillian@beltmann.com",
            hashed_password=hash_password("beltmann2026"),
            name="Jillian",
            role="owner",
        ))
        db.flush()

    # --- Workflows (C1 enforcement) ---
    workflows_data = [
        ("Inbound Quote Processing", True),
        ("Carrier Distribution", True),
        ("Follow-up Automation", False),
    ]
    for wf_name, enabled in workflows_data:
        db.add(Workflow(name=wf_name, enabled=enabled))
    db.flush()

    # --- Carriers ---
    carriers_data = [
        ("Express Carriers", "dispatch@expresscarriers.com", "Mike Johnson", "555-0101",
         ["Dry Van", "Flatbed"], [{"origin": "Seattle", "destination": "Portland"}, {"origin": "Chicago", "destination": "Dallas"}], True),
        ("National Trucking", "quotes@nationaltrucking.com", "Sarah Williams", "555-0102",
         ["Dry Van", "Reefer", "Flatbed"], [], True),
        ("Southern Freight", "ops@southernfreight.com", "Carlos Martinez", "555-0103",
         ["Flatbed"], [{"origin": "Houston", "destination": "Atlanta"}, {"origin": "Miami", "destination": "Charlotte"}], True),
        ("Pacific Transport", "rates@pacifictransport.com", "Lisa Chang", "555-0104",
         ["Dry Van", "Reefer"], [{"origin": "Los Angeles", "destination": "Phoenix"}, {"origin": "San Francisco", "destination": "Denver"}], False),
        ("Midwest Haulers", "bids@midwesthaulers.com", "Tom Anderson", "555-0105",
         ["Dry Van", "Flatbed"], [{"origin": "Detroit", "destination": "Nashville"}, {"origin": "Chicago", "destination": "Milwaukee"}], False),
        ("Great Plains Logistics", "dispatch@greatplainslogistics.com", "Amy Roberts", "555-0106",
         ["Dry Van"], [{"origin": "San Antonio", "destination": "El Paso"}], False),
        ("Northeast Express", "quotes@northeastexpress.com", "David Park", "555-0107",
         ["Reefer", "Dry Van"], [{"origin": "Boston", "destination": "New York"}, {"origin": "Columbus", "destination": "Indianapolis"}], False),
        ("Coastal Carriers", "ops@coastalcarriers.com", "Nina Patel", "555-0108",
         ["Reefer"], [{"origin": "Miami", "destination": "Charlotte"}], False),
    ]

    carriers = []
    for name, email, contact, phone, equip, lanes, preferred in carriers_data:
        carrier = Carrier(
            name=name, email=email, contact_name=contact, phone=phone,
            equipment_types=equip, lanes=lanes, preferred=preferred,
        )
        db.add(carrier)
        carriers.append(carrier)
    db.flush()

    # --- RFQs in various lifecycle states ---
    rfqs_data = [
        ("Tom Reynolds", "tom@reynoldslogistics.com", "Reynolds Logistics",
         "Chicago, IL", "Dallas, TX", "Dry Van", 2, "Auto parts", 38000,
         RFQState.READY_TO_QUOTE, timedelta(hours=18)),
        ("Sarah Chen", "sarah@pacificgoods.com", "Pacific Goods Inc",
         "Los Angeles, CA", "Phoenix, AZ", "Flatbed", 1, "Steel beams", 42000,
         RFQState.WAITING_ON_CARRIERS, timedelta(hours=15)),
        ("Mike O'Brien", "mike@midwestfreight.com", "Midwest Freight Co",
         "Detroit, MI", "Nashville, TN", "Reefer", 3, None, None,
         RFQState.NEEDS_CLARIFICATION, timedelta(hours=12)),
        ("Lisa Park", "lisa@summitsupply.com", "Summit Supply",
         "Seattle, WA", "Portland, OR", "Dry Van", 1, "Electronics", 15000,
         RFQState.QUOTES_RECEIVED, timedelta(hours=10)),
        ("James Wilson", "james@wilsonmfg.com", "Wilson Manufacturing",
         "Houston, TX", "Atlanta, GA", "Flatbed", 2, "Machinery", 55000,
         RFQState.WAITING_ON_BROKER, timedelta(hours=8)),
        ("Amy Torres", "amy@torresimports.com", "Torres Imports",
         "Miami, FL", "Charlotte, NC", "Reefer", 1, "Frozen produce", 22000,
         RFQState.READY_TO_QUOTE, timedelta(hours=6)),
        ("David Kim", "david@kimelectronics.com", "Kim Electronics",
         "San Francisco, CA", "Denver, CO", "Dry Van", 4, "Consumer electronics", 30000,
         RFQState.WAITING_ON_CARRIERS, timedelta(hours=4)),
        ("Rachel Green", "rachel@greenfoods.com", "Green Foods LLC",
         "Boston, MA", "New York, NY", "Reefer", 1, "Organic produce", 18000,
         RFQState.QUOTE_SENT, timedelta(hours=24)),
        ("Carlos Ruiz", "carlos@ruizconstruction.com", "Ruiz Construction",
         "San Antonio, TX", "El Paso, TX", "Flatbed", 6, "Building materials", 72000,
         RFQState.WON, timedelta(days=3)),
        ("Nina Patel", "nina@pateltextiles.com", "Patel Textiles",
         "Columbus, OH", "Indianapolis, IN", "Dry Van", 1, "Textiles", 12000,
         RFQState.LOST, timedelta(days=2)),
    ]

    rfqs = []
    for name, email, company, origin, dest, equip, trucks, commodity, weight, state, age in rfqs_data:
        rfq = RFQ(
            customer_name=name, customer_email=email, customer_company=company,
            origin=origin, destination=dest, equipment_type=equip,
            truck_count=trucks, commodity=commodity, weight_lbs=weight,
            state=state,
            confidence_scores={"origin": 0.97, "destination": 0.95, "equipment_type": 0.92,
                               "commodity": 0.45 if commodity is None else 0.88},
            created_at=now - age, updated_at=now - timedelta(hours=1),
        )
        # Set closed_at for terminal states
        if state in (RFQState.WON, RFQState.LOST, RFQState.CANCELLED):
            rfq.closed_at = now - timedelta(hours=2)
            rfq.outcome = state.value
            if state == RFQState.WON:
                rfq.quoted_amount = Decimal("8500.00")
        db.add(rfq)
        rfqs.append(rfq)

    db.flush()

    # --- Inbound messages with routing statuses ---
    messages_data = [
        (rfqs[0], "inbound", rfqs[0].customer_email,
         f"Quote Request - {rfqs[0].origin} to {rfqs[0].destination}",
         f"Hi Jillian,\n\nWe need {rfqs[0].truck_count} {rfqs[0].equipment_type}(s) from {rfqs[0].origin} to {rfqs[0].destination}. Commodity is auto parts, approximately 38,000 lbs. Need tarping.\n\nPickup next Monday.\n\nThanks,\nTom Reynolds",
         "attached", 18),
        (rfqs[1], "inbound", rfqs[1].customer_email,
         f"Urgent: Flatbed needed {rfqs[1].origin} to {rfqs[1].destination}",
         f"Jillian,\n\nNeed a flatbed ASAP from {rfqs[1].origin} to {rfqs[1].destination}. 1 truck, oversized steel beams. Can you quote?\n\nSarah Chen\nPacific Goods",
         "attached", 15),
        (rfqs[2], "inbound", rfqs[2].customer_email,
         f"Need reefer quote {rfqs[2].origin} to {rfqs[2].destination}",
         f"Hi,\n\nLooking for 3 reefers from {rfqs[2].origin} to {rfqs[2].destination}. Frozen goods, must maintain -10F.\n\nMike O'Brien\nMidwest Freight",
         "new_rfq", 12),
        (rfqs[5], "inbound", rfqs[5].customer_email,
         f"Reefer shipment {rfqs[5].origin} to {rfqs[5].destination}",
         f"Hello Beltmann team,\n\nWe have a reefer load from {rfqs[5].origin} to {rfqs[5].destination}. 1 truck, frozen produce.\n\nAmy Torres",
         "new_rfq", 6),
        (None, "inbound", "unknown.sender@gmail.com", "Re: Shipment update",
         "Hi,\n\nJust checking on the status of our shipment. Can you provide an ETA?\n\nThanks",
         "needs_review", 5),
        (None, "inbound", "logistics@acmecorp.com", "Multiple routes needed",
         "Jillian,\n\nWe have 3 different shipments:\n1. NYC to Boston - 2 dry vans\n2. Chicago to Milwaukee - 1 flatbed\n3. LA to San Diego - 1 reefer\n\nCan we set up a call?\n\nAcme Logistics",
         "needs_review", 4),
        (None, "inbound", "newsletter@freightweekly.com", "This Week in Freight: Market Update",
         "Freight Weekly Newsletter\n\nSpot rates continue to climb in the Southeast corridor...",
         "ignored", 20),
        (None, "inbound", "noreply@carrierportal.com", "Your account statement is ready",
         "Your monthly carrier portal statement is available for download.",
         "ignored", 16),
        (None, "inbound", "marketing@truckstop.com", "Special offer: Premium membership",
         "Upgrade to Premium for exclusive load board access and rate insights.",
         "ignored", 14),
        # Carrier bid reply
        (rfqs[3], "inbound", "bids@expresscarriers.com", "Re: RFQ Seattle to Portland",
         f"Beltmann,\n\nWe can do Seattle to Portland for $2,850. Available next week.\n\nExpress Carriers Dispatch",
         "attached", 3),
        # Outbound reply
        (rfqs[0], "outbound", "jillian@beltmann.com",
         f"Re: Quote Request - {rfqs[0].origin} to {rfqs[0].destination}",
         f"Hi Tom,\n\nThank you for your request. We can offer 2 dry vans at $2,850 each for Chicago to Dallas.\n\nTransit time: 2-3 business days.\n\nBest,\nJillian\nBeltmann Logistics",
         "attached", 9),
    ]

    for rfq, direction, sender, subject, body, routing, hours_ago in messages_data:
        db.add(Message(
            rfq_id=rfq.id if rfq else None,
            direction=MessageDirection(direction),
            sender=sender, subject=subject, body=body,
            routing_status=MessageRoutingStatus(routing),
            received_at=now - timedelta(hours=hours_ago),
        ))

    # --- Pending approvals (for the approval modal) ---
    approvals_data = [
        (rfqs[0], ApprovalType.CUSTOMER_REPLY,
         f"Re: Quote Request - {rfqs[0].origin} to {rfqs[0].destination}",
         rfqs[0].customer_email, "Draft reply with rate options",
         f"Hi Tom,\n\nThank you for your quote request. Based on current market rates:\n\n- 2 Dry Vans: $2,850 each\n- Transit: 2-3 business days\n- All-in rate including fuel surcharge\n\nPlease let me know if you'd like to proceed.\n\nBest regards,\nJillian\nBeltmann Logistics"),
        (rfqs[3], ApprovalType.CARRIER_RFQ,
         f"RFQ: {rfqs[3].origin} to {rfqs[3].destination}",
         "dispatch@carrierexpress.com", "Carrier RFQ ready for distribution",
         f"Carrier RFQ\n\nLoad Details:\n- Origin: {rfqs[3].origin}\n- Destination: {rfqs[3].destination}\n- Equipment: {rfqs[3].equipment_type}\n- Truck Count: {rfqs[3].truck_count}\n- Commodity: {rfqs[3].commodity}\n\nPlease reply with your best rate and availability."),
        (rfqs[4], ApprovalType.CUSTOMER_QUOTE,
         f"Quote: {rfqs[4].origin} to {rfqs[4].destination}",
         rfqs[4].customer_email, "Low confidence on commodity field",
         f"Hi James,\n\nHere is your quote:\n\n- Route: {rfqs[4].origin} to {rfqs[4].destination}\n- 2 Flatbeds: $4,200 each\n- Equipment: {rfqs[4].equipment_type}\n\nQuote valid for 48 hours.\n\nBest,\nJillian"),
    ]

    for rfq, atype, subject, recipient, reason, body in approvals_data:
        db.add(Approval(
            rfq_id=rfq.id, approval_type=atype,
            draft_body=body, draft_subject=subject,
            draft_recipient=recipient, reason=reason,
            status=ApprovalStatus.PENDING_APPROVAL,
        ))

    # --- Carrier bids ---
    db.add(CarrierBid(rfq_id=rfqs[3].id, carrier_name="Express Carriers",
                      carrier_email="bids@expresscarriers.com", rate=Decimal("2850.00"),
                      received_at=now - timedelta(hours=3)))
    db.add(CarrierBid(rfq_id=rfqs[3].id, carrier_name="National Trucking",
                      carrier_email="quotes@nationaltrucking.com", rate=Decimal("3100.00"),
                      received_at=now - timedelta(hours=2)))
    db.add(CarrierBid(rfq_id=rfqs[4].id, carrier_name="Southern Freight",
                      carrier_email="ops@southernfreight.com", rate=Decimal("4200.00"),
                      received_at=now - timedelta(minutes=45)))

    # --- Agent runs (for time saved) ---
    for j in range(6):
        db.add(AgentRun(
            rfq_id=rfqs[j].id, workflow_name="extraction",
            status=AgentRunStatus.COMPLETED,
            duration_ms=30000 + j * 15000,
            started_at=now - timedelta(hours=j + 1),
            finished_at=now - timedelta(hours=j),
            total_cost_usd=Decimal("0.02"),
        ))

    # --- Audit events (activity feed + RFQ timelines) ---
    events = [
        (rfqs[0], "rfq_created", "system", f"New RFQ from {rfqs[0].customer_name} — {rfqs[0].origin} to {rfqs[0].destination}", 18),
        (rfqs[1], "rfq_created", "system", f"New RFQ from {rfqs[1].customer_name} — {rfqs[1].origin} to {rfqs[1].destination}", 15),
        (rfqs[0], "extraction_completed", "extraction_agent", f"Extracted shipment details for {rfqs[0].customer_company} quote", 17),
        (rfqs[2], "rfq_created", "system", f"New RFQ from {rfqs[2].customer_name} — {rfqs[2].origin} to {rfqs[2].destination}", 12),
        (rfqs[0], "state_changed", "system", "Moved from Needs clarification to Ready to quote", 16),
        (rfqs[1], "state_changed", "system", "Moved from Ready to quote to Waiting on carriers", 14),
        (rfqs[3], "rfq_created", "system", f"New RFQ from {rfqs[3].customer_name} — {rfqs[3].origin} to {rfqs[3].destination}", 10),
        (rfqs[1], "email_sent", "system", f"Sent carrier RFQ to 3 carriers for {rfqs[1].customer_company} shipment", 13),
        (rfqs[3], "state_changed", "system", "Moved from Waiting on carriers to Quotes received", 8),
        (rfqs[2], "escalated_for_review", "extraction_agent", f"Flagged {rfqs[2].customer_company} RFQ — low confidence on commodity field", 11),
        (rfqs[4], "state_changed", "system", "Moved from Quotes received to Waiting on broker review", 7),
        (rfqs[5], "rfq_created", "system", f"New RFQ from {rfqs[5].customer_name} — {rfqs[5].origin} to {rfqs[5].destination}", 6),
        (rfqs[3], "state_changed", "system", "Express Carriers quoted $2,850 for Seattle to Portland", 3),
        (rfqs[6], "rfq_created", "system", f"New RFQ from {rfqs[6].customer_name} — {rfqs[6].origin} to {rfqs[6].destination}", 4),
        (rfqs[0], "approval_approved", "jillian@beltmann.com", f"Approved draft reply to {rfqs[0].customer_name}", 9),
        (rfqs[0], "email_sent", "system", f"Sent customer reply to {rfqs[0].customer_email}", 9),
    ]

    for rfq, etype, actor, desc, hours_ago in events:
        db.add(AuditEvent(
            rfq_id=rfq.id, event_type=etype, actor=actor,
            description=desc,
            created_at=now - timedelta(hours=hours_ago),
        ))

    db.commit()

    return {
        "status": "ok",
        "seeded": {
            "rfqs": len(rfqs),
            "messages": len(messages_data),
            "workflows": len(workflows_data),
            "carriers": len(carriers),
            "approvals": len(approvals_data),
            "carrier_bids": 3,
            "agent_runs": 6,
            "audit_events": len(events),
        },
    }


@router.post("/inject-email")
def inject_email(body: dict, db: Session = Depends(get_db)):
    """
    Inject a fake inbound email into the pipeline for testing (#146).

    Accepts any sender/recipient/subject/body and processes it through
    the full pipeline — matching, extraction, validation, the whole chain.
    The system treats it exactly like a real email from the mailbox.

    Body:
        sender: str — e.g., "Tom Reynolds <tom@reynolds.com>"
        recipient: str — e.g., "agents@golteris.com" (optional, for logging)
        subject: str — email subject line
        body: str — email body text
        in_reply_to: str — optional, for thread matching
        thread_id: str — optional, for conversation threading

    Example:
        curl -X POST https://app.golteris.com/api/dev/inject-email \\
          -H "Content-Type: application/json" \\
          -d '{"sender": "Tom <tom@example.com>", "subject": "Need 2 flatbeds", "body": "Chicago to Dallas, 40k lbs steel"}'
    """
    from backend.worker import enqueue_job

    sender = body.get("sender", "test@example.com")
    recipient = body.get("recipient", "agents@golteris.com")
    subject = body.get("subject", "Test email")
    email_body = body.get("body", "")
    in_reply_to = body.get("in_reply_to")
    thread_id = body.get("thread_id")

    # Check for duplicate by subject + sender (prevent accidental double-inject)
    existing = (
        db.query(Message)
        .filter(Message.sender == sender, Message.subject == subject, Message.body == email_body)
        .first()
    )
    if existing:
        return {"status": "duplicate", "message_id": existing.id, "note": "Already injected"}

    # Create the message — same as what the email ingestion service does
    message = Message(
        sender=sender,
        recipients=recipient,
        subject=subject,
        body=email_body,
        direction=MessageDirection.INBOUND,
        in_reply_to=in_reply_to,
        thread_id=thread_id,
        routing_status=None,
        received_at=datetime.utcnow(),
    )
    db.add(message)
    db.commit()
    db.refresh(message)

    # Audit event
    db.add(AuditEvent(
        event_type="email_received",
        actor="dev_inject",
        description=f"Test email received from {sender}: {subject}",
        event_data={"message_id": message.id, "sender": sender, "subject": subject},
    ))
    db.commit()

    # Enqueue matching — this kicks off the full pipeline
    job = enqueue_job(db, "matching", {"message_id": message.id})

    logger.info("Injected test email #%d from %s: %s", message.id, sender, subject)

    return {
        "status": "injected",
        "message_id": message.id,
        "job_id": job.id,
        "sender": sender,
        "subject": subject,
        "note": "Matching job enqueued — pipeline will process this like a real email",
    }


@router.get("/debug-auth")
def debug_auth(db = Depends(get_db)):
    """Temporary debug endpoint to test auth."""
    try:
        from backend.db.models import User
        count = db.query(User).count()
        return {"user_count": count, "status": "ok"}
    except Exception as e:
        return {"error": str(e)}


@router.post("/migrate")
def run_migration(db = Depends(get_db)):
    """Add missing columns to existing tables on Render."""
    from sqlalchemy import text
    results = []
    migrations = [
        ("users", "org_id", "ALTER TABLE users ADD COLUMN org_id INTEGER"),
        ("rfqs", "org_id", "ALTER TABLE rfqs ADD COLUMN org_id INTEGER"),
        ("agent_calls", "provider", "ALTER TABLE agent_calls ADD COLUMN provider VARCHAR(100)"),
        ("agent_calls", "model", "ALTER TABLE agent_calls ADD COLUMN model VARCHAR(100)"),
        ("agent_calls", "system_prompt", "ALTER TABLE agent_calls ADD COLUMN system_prompt TEXT"),
        ("agent_calls", "user_prompt", "ALTER TABLE agent_calls ADD COLUMN user_prompt TEXT"),
        ("agent_calls", "response", "ALTER TABLE agent_calls ADD COLUMN response TEXT"),
        ("agent_calls", "error_message", "ALTER TABLE agent_calls ADD COLUMN error_message TEXT"),
    ]
    for table, col, sql in migrations:
        try:
            db.execute(text(sql))
            db.commit()
            results.append(f"{table}.{col}: added")
        except Exception as e:
            db.rollback()
            err = str(e)
            if "already exists" in err:
                results.append(f"{table}.{col}: already exists")
            else:
                results.append(f"{table}.{col}: {err[:80]}")
    return {"results": results}


@router.post("/reset-jobs")
def reset_stuck_jobs(db = Depends(get_db)):
    """Reset stuck running jobs back to pending."""
    from backend.db.models import Job, JobStatus
    stuck = db.query(Job).filter(Job.status == JobStatus.RUNNING).all()
    for j in stuck:
        j.status = JobStatus.PENDING
        j.started_at = None
    db.commit()
    return {"reset": len(stuck)}


@router.post("/create-admin")
def create_admin_user(db = Depends(get_db)):
    """Create admin user without bcrypt dependency check."""
    try:
        from backend.db.models import User
        import bcrypt
        existing = db.query(User).filter(User.email == "curt@golteris.com").first()
        if existing:
            return {"status": "exists", "id": existing.id, "role": existing.role}
        hashed = bcrypt.hashpw(b"admin2026", bcrypt.gensalt()).decode()
        user = User(email="curt@golteris.com", hashed_password=hashed, name="Curt", role="admin")
        db.add(user)
        db.commit()
        return {"status": "created", "id": user.id}
    except Exception as e:
        return {"error": str(e), "type": type(e).__name__}


@router.get("/personas")
def get_personas():
    """
    Return dev personas and email templates for the Dev Area (#169).

    Reads from backend/dev/personas.json. Personas are real test contacts
    (Gmail addresses). Templates have placeholder fields like {origin}
    that the frontend fills in before sending.
    """
    import os
    personas_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "dev", "personas.json")
    try:
        with open(personas_path) as f:
            import json
            return json.load(f)
    except FileNotFoundError:
        return {"personas": [], "templates": []}


@router.post("/personas")
def save_personas(body: dict):
    """
    Save dev personas and templates (#170).

    Writes the full JSON to backend/dev/personas.json.
    Expects the same shape as GET /api/dev/personas returns.
    """
    import os
    personas_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "dev", "personas.json")
    import json
    with open(personas_path, "w") as f:
        json.dump(body, f, indent=2)
    return {"status": "ok"}
