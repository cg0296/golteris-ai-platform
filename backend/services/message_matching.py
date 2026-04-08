"""
backend/services/message_matching.py — Message-to-RFQ matching service.

When a new inbound message arrives, this service determines which RFQ it
belongs to (or whether it's a new RFQ / noise). It uses a tiered strategy:

    1. Thread matching (deterministic) — if the message has in_reply_to or
       thread_id that matches an existing message, attach to the same RFQ.
       This handles direct replies to our outbound emails.

    2. Sender matching — find active RFQs where the customer_email matches
       the message sender. If exactly one match, attach with high confidence.

    3. Context scoring — when multiple candidates exist, score them by
       comparing route keywords, equipment type, dates, and subject overlap.
       The highest-scoring candidate wins if above threshold.

    4. Review queue — if no strategy produces a confident match, the message
       goes to the review queue for the broker to resolve manually (FR-EI-4).

Called by:
    - The background worker after ingesting a new message
    - The email ingestion pipeline (#12)

Cross-cutting constraints:
    FR-EI-3 — Every inbound message attached via thread matching first, context scoring second
    FR-EI-4 — Ambiguous matches do NOT auto-attach; they enter the review queue
    FR-EI-5 — Message routing_status is set for the Inbox view badges
    C4 — Match reason stored in audit_events for traceability
"""

import logging
import re
from dataclasses import dataclass, field
from typing import Optional

from sqlalchemy.orm import Session

from backend.db.models import (
    Approval,
    ApprovalStatus,
    ApprovalType,
    AuditEvent,
    Carrier,
    CarrierRfqSend,
    CarrierSendStatus,
    Message,
    MessageRoutingStatus,
    ReviewQueue,
    ReviewQueueStatus,
    RFQ,
    RFQState,
)

logger = logging.getLogger("golteris.services.message_matching")

# Confidence thresholds for auto-attach vs review queue
AUTO_ATTACH_THRESHOLD = 0.85
REVIEW_THRESHOLD = 0.30  # Below this, treat as new RFQ

# Terminal RFQ states — don't match messages to closed RFQs
TERMINAL_STATES = {RFQState.WON, RFQState.LOST, RFQState.CANCELLED}


@dataclass
class MatchCandidate:
    """A potential RFQ that a message could belong to, with a confidence score."""
    rfq_id: int
    score: float
    method: str  # "thread", "sender", "context"
    reason: str  # Human-readable explanation of why this was a match


@dataclass
class MatchResult:
    """The outcome of attempting to match a message to an RFQ."""
    rfq_id: Optional[int] = None
    confidence: float = 0.0
    method: str = "none"
    reason: str = ""
    candidates: list[MatchCandidate] = field(default_factory=list)
    routing_status: MessageRoutingStatus = MessageRoutingStatus.NEEDS_REVIEW


def match_message_to_rfq(db: Session, message_id: int) -> MatchResult:
    """
    Determine which RFQ an inbound message belongs to.

    Tries matching strategies in priority order: thread -> sender -> context.
    Updates the message's routing_status and rfq_id based on the result.
    Creates review_queue entries for ambiguous matches (FR-EI-4).

    Args:
        db: SQLAlchemy session.
        message_id: The inbound message to match.

    Returns:
        MatchResult with the outcome (rfq_id, confidence, method, routing_status).
        If no match, rfq_id is None and routing_status indicates what happened.
    """
    message = db.query(Message).filter(Message.id == message_id).first()
    if not message:
        logger.error("Message %d not found", message_id)
        return MatchResult(reason="Message not found")

    # Strategy 0: RFQ reference tag in subject (most reliable).
    # Outbound emails include [RFQ-42] in the subject. When the recipient
    # replies, the tag carries over in the Re: subject. This is a
    # deterministic match that works even when thread headers are lost.
    result = _try_rfq_tag_match(db, message)
    if result.rfq_id:
        _apply_match(db, message, result)
        return result

    # Strategy 1: Thread matching (deterministic, highest priority)
    result = _try_thread_match(db, message)
    if result.rfq_id:
        _apply_match(db, message, result)
        return result

    # Strategy 2: Sender matching against active RFQs
    candidates = _find_sender_candidates(db, message)

    if candidates:
        # Strategy 3: Context scoring to refine all candidates
        scored = _score_candidates(db, message, candidates)
        best = max(scored, key=lambda c: c.score)

        if best.score >= AUTO_ATTACH_THRESHOLD:
            # Strong match — auto-attach
            result = MatchResult(
                rfq_id=best.rfq_id,
                confidence=best.score,
                method=best.method,
                reason=best.reason,
                candidates=scored,
                routing_status=MessageRoutingStatus.ATTACHED,
            )
            _apply_match(db, message, result)
            return result

        if len(scored) == 1:
            # Single sender match below threshold — check if the RFQ is
            # awaiting clarification. If so, this is almost certainly the
            # reply to our clarification email. Auto-attach it because:
            # 1. Thread matching fails (outbound messages don't store
            #    message_id_header, so in_reply_to can't find the parent)
            # 2. Context scoring can't boost the score because the RFQ
            #    fields are empty (that's WHY clarification was needed)
            rfq = db.query(RFQ).filter(RFQ.id == best.rfq_id).first()
            if rfq and rfq.state == RFQState.NEEDS_CLARIFICATION:
                result = MatchResult(
                    rfq_id=best.rfq_id,
                    confidence=0.90,
                    method="clarification_reply",
                    reason=f"Reply from same sender while RFQ #{best.rfq_id} awaits clarification",
                    candidates=scored,
                    routing_status=MessageRoutingStatus.ATTACHED,
                )
                _apply_match(db, message, result)
                return result

            # Single sender match, not a clarification reply — review queue
            result = MatchResult(
                confidence=best.score,
                method="weak_sender",
                reason=f"Single sender match but confidence {best.score:.2f} below threshold",
                candidates=scored,
                routing_status=MessageRoutingStatus.NEEDS_REVIEW,
            )
            _send_to_review_queue(db, message, result)
            return result

        if len(scored) > 1:
            # Multiple candidates, none strong enough — review queue (FR-EI-4)
            result = MatchResult(
                confidence=best.score,
                method="ambiguous",
                reason=f"Multiple candidates, best score {best.score:.2f} below threshold",
                candidates=scored,
                routing_status=MessageRoutingStatus.NEEDS_REVIEW,
            )
            _send_to_review_queue(db, message, result)
            return result

        # Shouldn't reach here, but safety fallback
        _send_to_review_queue(db, message, MatchResult(
            confidence=best.score, method="unknown", reason="Unexpected match state",
            candidates=scored, routing_status=MessageRoutingStatus.NEEDS_REVIEW,
        ))
        return result

    # Strategy 4: Carrier match — check if the sender is a known carrier
    # with an active carrier_rfq_sends record. Carrier replies won't match
    # on customer_email (that's the shipper), so we need to check the
    # carriers table and carrier_rfq_sends to link them back to an RFQ.
    carrier_result = _try_carrier_match(db, message)
    if carrier_result.rfq_id:
        _apply_match(db, message, carrier_result)
        return carrier_result

    # No candidates at all — this is a new RFQ.
    # Enqueue extraction so the pipeline automatically creates a structured
    # RFQ from the email content. The chain continues from extraction:
    #   extraction → validation (if needs_clarification) or quote_sheet (if ready)
    from backend.worker import enqueue_job

    result = MatchResult(
        method="no_match",
        reason="No matching RFQs found — new quote request, extraction enqueued",
        routing_status=MessageRoutingStatus.NEW_RFQ_CREATED,
    )
    message.routing_status = result.routing_status
    db.commit()

    enqueue_job(db, "extraction", {"message_id": message.id})
    logger.info("Message %d: no match — new RFQ, extraction job enqueued", message_id)
    return result


def _try_rfq_tag_match(db: Session, message: Message) -> MatchResult:
    """
    Try to match via [RFQ-{id}] tag in the subject line.

    All outbound emails include a reference tag like [RFQ-42] in the subject.
    When the recipient replies, email clients preserve it in the Re: subject.
    This gives us a deterministic match that doesn't depend on thread headers
    or sender lookup — just a simple regex on the subject.
    """
    subject = message.subject or ""
    match = re.search(r'\[RFQ-(\d+)\]', subject)
    if not match:
        return MatchResult()

    rfq_id = int(match.group(1))
    rfq = db.query(RFQ).filter(RFQ.id == rfq_id).first()

    if not rfq:
        logger.warning("Message %d has [RFQ-%d] tag but RFQ not found", message.id, rfq_id)
        return MatchResult()

    if rfq.state in TERMINAL_STATES:
        logger.info("Message %d has [RFQ-%d] tag but RFQ is %s — skipping", message.id, rfq_id, rfq.state.value)
        return MatchResult()

    return MatchResult(
        rfq_id=rfq_id,
        confidence=0.99,
        method="rfq_tag",
        reason=f"Subject contains [RFQ-{rfq_id}] reference tag",
        routing_status=MessageRoutingStatus.ATTACHED,
    )


def _try_thread_match(db: Session, message: Message) -> MatchResult:
    """
    Try to match via thread_id or in_reply_to (deterministic matching).

    If the message has an in_reply_to header, look for the parent message
    and use its RFQ. If it has a thread_id, look for any message in that
    thread that's already attached to an RFQ.

    This is the highest-confidence match — it's based on email headers,
    not content analysis.
    """
    # Try in_reply_to first — most reliable for direct replies
    if message.in_reply_to:
        parent = (
            db.query(Message)
            .filter(Message.message_id_header == message.in_reply_to)
            .first()
        )
        if parent and parent.rfq_id:
            return MatchResult(
                rfq_id=parent.rfq_id,
                confidence=0.99,
                method="thread_reply",
                reason=f"Direct reply to message in RFQ #{parent.rfq_id}",
                routing_status=MessageRoutingStatus.ATTACHED,
            )

    # Try thread_id — for messages in the same conversation
    if message.thread_id:
        thread_msg = (
            db.query(Message)
            .filter(
                Message.thread_id == message.thread_id,
                Message.rfq_id.isnot(None),
                Message.id != message.id,
            )
            .first()
        )
        if thread_msg and thread_msg.rfq_id:
            return MatchResult(
                rfq_id=thread_msg.rfq_id,
                confidence=0.97,
                method="thread_id",
                reason=f"Same thread as message attached to RFQ #{thread_msg.rfq_id}",
                routing_status=MessageRoutingStatus.ATTACHED,
            )

    return MatchResult()  # No thread match


def _find_sender_candidates(db: Session, message: Message) -> list[MatchCandidate]:
    """
    Find active RFQs where the customer_email matches the message sender.

    Only considers non-terminal RFQs (not won/lost/cancelled) since a new
    message from a customer with a closed RFQ is likely a new request.
    """
    # Normalize sender to just the email address
    sender_email = _extract_email(message.sender)
    if not sender_email:
        return []

    active_rfqs = (
        db.query(RFQ)
        .filter(
            RFQ.customer_email == sender_email,
            RFQ.state.notin_([s.value for s in TERMINAL_STATES]),
        )
        .all()
    )

    return [
        MatchCandidate(
            rfq_id=rfq.id,
            score=0.70,  # Base score for sender match — context scoring refines it
            method="sender",
            reason=f"Same sender ({sender_email}) as RFQ #{rfq.id}",
        )
        for rfq in active_rfqs
    ]


def _score_candidates(
    db: Session,
    message: Message,
    candidates: list[MatchCandidate],
) -> list[MatchCandidate]:
    """
    Refine candidate scores using context signals from the message content.

    Boosts scores when the message mentions route/equipment/commodity that
    match the candidate RFQ. This helps disambiguate when a customer has
    multiple active RFQs.

    Scoring adjustments (additive):
    - Subject keyword overlap with RFQ route: +0.10
    - Body mentions origin or destination: +0.08 each
    - Body mentions equipment type: +0.05
    - Body mentions commodity: +0.05
    """
    for candidate in candidates:
        # This is a simple scoring approach — no LLM needed.
        # For the MVP, keyword matching is sufficient. More sophisticated
        # scoring (embeddings, LLM context) can come later.
        rfq = db.query(RFQ).filter(RFQ.id == candidate.rfq_id).first()
        if not rfq:
            continue

        body_lower = (message.body or "").lower()
        subject_lower = (message.subject or "").lower()

        # Route keywords in subject
        if rfq.origin and rfq.origin.lower().split(",")[0] in subject_lower:
            candidate.score += 0.10
        if rfq.destination and rfq.destination.lower().split(",")[0] in subject_lower:
            candidate.score += 0.10

        # Route keywords in body
        if rfq.origin and rfq.origin.lower().split(",")[0] in body_lower:
            candidate.score += 0.08
        if rfq.destination and rfq.destination.lower().split(",")[0] in body_lower:
            candidate.score += 0.08

        # Equipment match
        if rfq.equipment_type and rfq.equipment_type.lower() in body_lower:
            candidate.score += 0.05

        # Commodity match
        if rfq.commodity and rfq.commodity.lower() in body_lower:
            candidate.score += 0.05

        candidate.reason += f" (context score: {candidate.score:.2f})"

    return candidates


def _apply_match(db: Session, message: Message, result: MatchResult) -> None:
    """
    Apply a successful match — link message to RFQ and log the audit event.
    """
    message.rfq_id = result.rfq_id
    message.routing_status = result.routing_status

    # Audit event for traceability (C4)
    event = AuditEvent(
        rfq_id=result.rfq_id,
        event_type="message_matched",
        actor="matching_service",
        description=f"Inbound message attached — {result.reason}",
        event_data={
            "message_id": message.id,
            "method": result.method,
            "confidence": result.confidence,
            "candidate_count": len(result.candidates),
        },
    )
    db.add(event)
    db.commit()

    logger.info(
        "Message %d matched to RFQ %d (method=%s, confidence=%.2f)",
        message.id, result.rfq_id, result.method, result.confidence,
    )

    # Smart routing based on RFQ state — determine what to do with the attached message
    if result.rfq_id:
        rfq = db.query(RFQ).filter(RFQ.id == result.rfq_id).first()
        broker_emails = ["jillian@beltmann.com", "agents@golteris.com"]
        sender_lower = (message.sender or "").lower()
        is_broker = any(be in sender_lower for be in broker_emails)

        if rfq and not is_broker:
            from backend.worker import enqueue_job

            if rfq.state == RFQState.NEEDS_CLARIFICATION:
                # Shipper replied with more details — re-extract to update RFQ fields
                enqueue_job(db, "extraction", {"message_id": message.id}, rfq_id=rfq.id)
                logger.info(
                    "Message %d is a clarification reply for RFQ %d — re-extraction enqueued",
                    message.id, rfq.id,
                )
            elif rfq.state in (RFQState.WAITING_ON_CARRIERS, RFQState.QUOTES_RECEIVED):
                # Auto-detect carrier replies (#102) — parse the bid
                enqueue_job(db, "parse_carrier_bid", {"message_id": message.id}, rfq_id=rfq.id)
                logger.info(
                    "Message %d looks like a carrier reply for RFQ %d — bid parsing enqueued",
                    message.id, rfq.id,
                )
            elif rfq.state == RFQState.QUOTE_SENT:
                # Customer responded to our quote (#145) — transition to
                # waiting_on_broker so it shows up as needing action, and
                # create an approval so it appears in Urgent Actions
                _handle_quote_response(db, rfq, message)


def _send_to_review_queue(db: Session, message: Message, result: MatchResult) -> None:
    """
    Put an ambiguous message into the review queue for the broker (FR-EI-4).

    The broker sees this in the Inbox view as a "Needs review" badge and
    can manually assign it to an RFQ or create a new one.
    """
    message.routing_status = MessageRoutingStatus.NEEDS_REVIEW

    review_entry = ReviewQueue(
        message_id=message.id,
        candidates=[
            {"rfq_id": c.rfq_id, "score": c.score, "reason": c.reason}
            for c in result.candidates
        ],
        reason=result.reason,
        status=ReviewQueueStatus.PENDING,
    )
    db.add(review_entry)
    db.commit()

    logger.info(
        "Message %d sent to review queue: %d candidates, reason=%s",
        message.id, len(result.candidates), result.reason,
    )


def _handle_quote_response(db: Session, rfq: RFQ, message: Message) -> None:
    """
    Handle a customer reply to a sent quote (#145).

    When the customer responds after we sent them a quote, the broker
    needs to see it and decide: mark as Won, Lost, or reply back.

    Creates:
    - State transition to waiting_on_broker
    - Audit event for the timeline
    - Approval record so it appears in Urgent Actions
    """
    from backend.services.rfq_state_machine import transition_rfq

    # Transition to waiting_on_broker so the RFQ shows as needing action
    try:
        transition_rfq(
            db, rfq.id, RFQState.WAITING_ON_BROKER,
            actor="matching_service",
            reason="Customer responded to quote",
        )
    except Exception as e:
        logger.warning("Could not transition RFQ %d to waiting_on_broker: %s", rfq.id, e)

    # Create an approval so it shows in Urgent Actions — the broker
    # can see the customer's reply and decide next steps
    # Truncate long reply bodies for the draft preview
    reply_preview = (message.body or "")[:500]
    approval = Approval(
        rfq_id=rfq.id,
        approval_type=ApprovalType.CUSTOMER_REPLY,
        draft_body=reply_preview,
        draft_subject=message.subject or "Customer response",
        draft_recipient=_extract_email(message.sender) or "",
        reason="Customer responded to your quote — review and take action",
        status=ApprovalStatus.PENDING_APPROVAL,
    )
    db.add(approval)

    # Audit event for the timeline
    sender_name = message.sender.split("<")[0].strip() if "<" in (message.sender or "") else message.sender
    event = AuditEvent(
        rfq_id=rfq.id,
        event_type="customer_quote_response",
        actor="matching_service",
        description=f"Customer {sender_name} responded to quote — review needed",
        event_data={
            "message_id": message.id,
            "sender": message.sender,
            "subject": message.subject,
        },
    )
    db.add(event)
    db.commit()

    logger.info(
        "RFQ %d: customer responded to quote (message %d) — moved to waiting_on_broker",
        rfq.id, message.id,
    )


def _try_carrier_match(db: Session, message: Message) -> MatchResult:
    """
    Try to match a message to an RFQ via the carriers table.

    When the system sends carrier RFQs (#32), it creates carrier_rfq_sends
    rows linking each carrier to an RFQ. If a carrier replies, we can match
    on their email address → carrier → carrier_rfq_sends → RFQ.

    This is necessary because carrier replies won't match on customer_email
    (that field holds the shipper, not the carrier).
    """
    sender_email = _extract_email(message.sender)
    if not sender_email:
        return MatchResult()

    # Find the carrier by email
    carrier = (
        db.query(Carrier)
        .filter(Carrier.email.ilike(sender_email))
        .first()
    )
    if not carrier:
        return MatchResult()

    # Find the most recent carrier_rfq_sends for this carrier that was sent
    send_record = (
        db.query(CarrierRfqSend)
        .filter(
            CarrierRfqSend.carrier_id == carrier.id,
            CarrierRfqSend.status == CarrierSendStatus.SENT,
        )
        .order_by(CarrierRfqSend.sent_at.desc())
        .first()
    )
    if not send_record:
        return MatchResult()

    # Verify the RFQ is in a state that expects carrier responses
    rfq = db.query(RFQ).filter(RFQ.id == send_record.rfq_id).first()
    if not rfq or rfq.state in TERMINAL_STATES:
        return MatchResult()

    logger.info(
        "Message %d matched to RFQ %d via carrier %s (%s)",
        message.id, rfq.id, carrier.name, carrier.email,
    )

    # Enqueue carrier bid parsing since we know this is a carrier reply
    from backend.worker import enqueue_job
    enqueue_job(db, "parse_carrier_bid", {"message_id": message.id}, rfq_id=rfq.id)

    return MatchResult(
        rfq_id=rfq.id,
        confidence=0.95,
        method="carrier_send_record",
        reason=f"Carrier {carrier.name} ({carrier.email}) has a sent RFQ for this load",
        routing_status=MessageRoutingStatus.ATTACHED,
    )


def _extract_email(sender: str) -> Optional[str]:
    """
    Extract the email address from a sender string.

    Handles formats like:
    - "tom@example.com"
    - "Tom Reynolds <tom@example.com>"
    - "tom@example.com (Tom Reynolds)"
    """
    if not sender:
        return None

    # Try angle bracket format first: "Name <email>"
    match = re.search(r"<([^>]+)>", sender)
    if match:
        return match.group(1).lower().strip()

    # Try bare email
    match = re.search(r"[\w.+-]+@[\w-]+\.[\w.]+", sender)
    if match:
        return match.group(0).lower().strip()

    return sender.lower().strip()
