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

    # Filter auto-replies and noise before any matching (#180)
    if _is_auto_reply(message):
        message.routing_status = MessageRoutingStatus.IGNORED
        db.add(AuditEvent(
            event_type="message_ignored",
            actor="matching_service",
            description=f"Auto-reply from {message.sender} ignored",
            event_data={"message_id": message.id, "reason": "auto_reply"},
        ))
        db.commit()
        logger.info("Message %d is an auto-reply — ignored", message_id)
        return MatchResult(method="auto_reply", reason="Auto-reply detected and ignored",
                          routing_status=MessageRoutingStatus.IGNORED)

    # Filter broker-team senders (#demo-fix).
    # If the message is from one of our own users (same email or same domain
    # as a registered user), treat it specially:
    #   - If it has an RFQ reference tag, still attach to that RFQ but don't
    #     trigger bid parsing or quote response classification.
    #   - If it has no tag, ignore it — don't create a bogus RFQ from a
    #     broker's internal email, forward, or reply noise.
    # This prevents internal broker team emails from accidentally spawning
    # new RFQs or being parsed as carrier bids.
    sender_lower = (message.sender or "").lower()
    if _is_broker_sender(db, sender_lower):
        # Still honor explicit RFQ tag matches so brokers CAN reply on a thread
        # and have it tracked. But stop short of extraction / bid parsing.
        tag_result = _try_rfq_tag_match(db, message)
        if tag_result.rfq_id:
            message.routing_status = MessageRoutingStatus.ATTACHED
            message.rfq_id = tag_result.rfq_id
            db.add(AuditEvent(
                rfq_id=tag_result.rfq_id,
                event_type="broker_reply_attached",
                actor="matching_service",
                description=f"Internal broker reply from {message.sender} attached (no extraction or bid parsing)",
                event_data={"message_id": message.id, "reason": "broker_sender"},
            ))
            db.commit()
            logger.info(
                "Message %d from broker team attached to RFQ %d (no routing)",
                message_id, tag_result.rfq_id,
            )
            return MatchResult(
                rfq_id=tag_result.rfq_id,
                confidence=0.99,
                method="broker_tag",
                reason="Internal broker reply attached via RFQ tag — no further routing",
                routing_status=MessageRoutingStatus.ATTACHED,
            )

        # No tag match — ignore this broker-internal email, don't spawn an RFQ
        message.routing_status = MessageRoutingStatus.IGNORED
        db.add(AuditEvent(
            event_type="message_ignored",
            actor="matching_service",
            description=f"Internal broker email from {message.sender} ignored (no RFQ tag)",
            event_data={"message_id": message.id, "reason": "broker_sender_no_tag"},
        ))
        db.commit()
        logger.info(
            "Message %d is from broker team with no RFQ tag — ignored to prevent bogus RFQ",
            message_id,
        )
        return MatchResult(
            method="broker_internal",
            reason="Internal broker email with no RFQ tag — ignored",
            routing_status=MessageRoutingStatus.IGNORED,
        )

    # Strategy 0: RFQ reference tag in subject (most reliable).
    # Outbound emails include [RFQ-YYYYMMDD-HHMM-NNN] in the subject.
    # When the recipient replies, the tag carries over in the Re: subject.
    # This is a deterministic match even when thread headers are lost.
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
            # awaiting clarification AND the subject looks like a reply.
            # A new subject from the same sender is a new email, not a reply (#180).
            rfq = db.query(RFQ).filter(RFQ.id == best.rfq_id).first()
            subject = (message.subject or "").strip()
            looks_like_reply = (
                subject.lower().startswith("re:")
                or bool(re.search(r'\[RFQ-[\w-]+\]', subject))
            )
            if rfq and rfq.state in (RFQState.NEEDS_CLARIFICATION, RFQState.INQUIRY) and looks_like_reply:
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

            # Single sender match, not a clarification reply.
            # If score is very low, treat as a new RFQ (#180).
            if best.score < REVIEW_THRESHOLD:
                # Too weak to even review — treat as new email
                from backend.worker import enqueue_job
                result = MatchResult(
                    method="below_review_threshold",
                    reason=f"Sender match score {best.score:.2f} below review threshold — treating as new",
                    routing_status=MessageRoutingStatus.NEW_RFQ_CREATED,
                )
                message.routing_status = result.routing_status
                db.commit()
                enqueue_job(db, "extraction", {"message_id": message.id})
                return result

            # Check if context scoring added ANY boost (#181).
            # Base sender match is 0.70. If the score is still 0.70 or very
            # close, there's zero content overlap — this is a completely
            # different email that just happens to be from the same sender.
            # Create a new RFQ instead of sending to review queue.
            SENDER_BASE_SCORE = 0.70
            if best.score <= SENDER_BASE_SCORE + 0.01:
                from backend.worker import enqueue_job
                result = MatchResult(
                    method="no_context_overlap",
                    reason=f"Same sender but zero content overlap with RFQ #{best.rfq_id} — new email",
                    routing_status=MessageRoutingStatus.NEW_RFQ_CREATED,
                )
                message.routing_status = result.routing_status
                db.commit()
                enqueue_job(db, "extraction", {"message_id": message.id})
                logger.info("Message %d: same sender but no overlap — treating as new RFQ", message.id)
                return result

            # Some context overlap but not enough for auto-attach — review queue
            result = MatchResult(
                confidence=best.score,
                method="weak_sender",
                reason=f"Single sender match with partial overlap (score {best.score:.2f}) — broker should decide",
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
    Try to match via [RFQ-{ref_number}] tag in the subject line.

    All outbound emails include a reference tag like [RFQ-20260409-1523-001]
    in the subject. When the recipient replies, email clients preserve it in
    the Re: subject. This gives us a deterministic match that doesn't depend
    on thread headers or sender lookup — just a simple regex on the subject.

    Supports both smart ref_number format (YYYYMMDD-HHMM-NNN) and legacy
    numeric IDs for backwards compatibility with older threads.
    """
    subject = message.subject or ""
    match = re.search(r'\[RFQ-([\w-]+)\]', subject)
    if not match:
        return MatchResult()

    ref_value = match.group(1)

    # Try ref_number lookup first (smart format), fall back to numeric ID
    rfq = db.query(RFQ).filter(RFQ.ref_number == ref_value).first()
    if not rfq and ref_value.isdigit():
        rfq = db.query(RFQ).filter(RFQ.id == int(ref_value)).first()

    if not rfq:
        logger.warning("Message %d has [RFQ-%s] tag but RFQ not found", message.id, ref_value)
        return MatchResult()

    if rfq.state in TERMINAL_STATES:
        logger.info("Message %d has [RFQ-%s] tag but RFQ is %s — skipping", message.id, ref_value, rfq.state.value)
        return MatchResult()

    return MatchResult(
        rfq_id=rfq.id,
        confidence=0.99,
        method="rfq_tag",
        reason=f"Subject contains [RFQ-{ref_value}] reference tag",
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

    # Exact email match first
    active_rfqs = (
        db.query(RFQ)
        .filter(
            RFQ.customer_email == sender_email,
            RFQ.state.notin_([s.value for s in TERMINAL_STATES]),
        )
        .all()
    )

    # Domain match fallback (#193) — if no exact match, check if someone
    # from the same company domain has an active RFQ. This handles the case
    # where tom@acme.com sends an RFQ and sarah@acme.com replies with details.
    if not active_rfqs and "@" in sender_email:
        domain = sender_email.split("@")[1]
        # Skip common free email domains — domain matching only helps for company emails
        free_domains = {"gmail.com", "yahoo.com", "hotmail.com", "outlook.com", "aol.com", "icloud.com"}
        if domain not in free_domains:
            domain_rfqs = (
                db.query(RFQ)
                .filter(
                    RFQ.customer_email.ilike(f"%@{domain}"),
                    RFQ.state.notin_([s.value for s in TERMINAL_STATES]),
                )
                .all()
            )
            if domain_rfqs:
                return [
                    MatchCandidate(
                        rfq_id=rfq.id,
                        score=0.55,  # Lower than exact match — domain match is less certain
                        method="domain",
                        reason=f"Same email domain (@{domain}) as RFQ #{rfq.id}",
                    )
                    for rfq in domain_rfqs
                ]

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
        sender_lower = (message.sender or "").lower()
        is_broker = _is_broker_sender(db, sender_lower)

        if rfq and not is_broker:
            from backend.worker import enqueue_job

            if rfq.state in (RFQState.NEEDS_CLARIFICATION, RFQState.INQUIRY):
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
            elif rfq.state in (RFQState.QUOTE_SENT, RFQState.WAITING_ON_BROKER):
                # Customer responded to our quote (#145, #180) — classify
                # as accepted, rejected, or question. Also handles the case
                # where the state is still waiting_on_broker because the
                # quote_sent transition happened after the email was sent.
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
    Handle a customer reply to a sent quote (#145, #160).

    Enqueues the quote_response agent to classify the customer's reply
    as accepted, rejected, or question — then take appropriate action.
    """
    from backend.worker import enqueue_job

    # Audit event — the broker sees the reply came in
    sender_name = message.sender.split("<")[0].strip() if "<" in (message.sender or "") else message.sender
    event = AuditEvent(
        rfq_id=rfq.id,
        event_type="customer_quote_response",
        actor="matching_service",
        description=f"Customer {sender_name} responded to quote — classifying response",
        event_data={
            "message_id": message.id,
            "sender": message.sender,
            "subject": message.subject,
        },
    )
    db.add(event)
    db.commit()

    # Enqueue the classification agent
    enqueue_job(db, "quote_response", {"message_id": message.id}, rfq_id=rfq.id)

    logger.info(
        "RFQ %d: customer responded to quote (message %d) — classification enqueued",
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

    # Find the carrier by email in the carriers table
    carrier = (
        db.query(Carrier)
        .filter(Carrier.email.ilike(sender_email))
        .first()
    )

    send_record = None
    if carrier:
        # Found carrier in table — look up their sent RFQs
        send_record = (
            db.query(CarrierRfqSend)
            .filter(
                CarrierRfqSend.carrier_id == carrier.id,
                CarrierRfqSend.status == CarrierSendStatus.SENT,
            )
            .order_by(CarrierRfqSend.sent_at.desc())
            .first()
        )
    else:
        # Carrier not in table — check if we sent an RFQ to this email (#180).
        # This handles cases where a carrier was added inline during distribution
        # or where the carriers table doesn't have their email.
        from backend.db.models import Approval, ApprovalType
        approval = (
            db.query(Approval)
            .filter(
                Approval.draft_recipient.ilike(sender_email),
                Approval.approval_type == ApprovalType.CARRIER_RFQ,
                Approval.status == ApprovalStatus.APPROVED,
            )
            .order_by(Approval.created_at.desc())
            .first()
        )
        if approval and approval.rfq_id:
            rfq = db.query(RFQ).filter(RFQ.id == approval.rfq_id).first()
            if rfq and rfq.state not in TERMINAL_STATES:
                from backend.worker import enqueue_job
                enqueue_job(db, "parse_carrier_bid", {"message_id": message.id}, rfq_id=rfq.id)
                return MatchResult(
                    rfq_id=rfq.id,
                    confidence=0.93,
                    method="carrier_approval_recipient",
                    reason=f"Sender matches carrier RFQ recipient ({sender_email})",
                    routing_status=MessageRoutingStatus.ATTACHED,
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


def _is_broker_sender(db: Session, sender_lower: str) -> bool:
    """
    Determine if a message sender is internal (the broker team), not a
    shipper or carrier.

    A sender is considered "broker" if:
      1. They match a registered User row in the database (any role), OR
      2. Their email matches the agent mailbox (agents@golteris.com), OR
      3. Their email domain matches any domain present in users.email
         (e.g., if the org has a user at @acme.com, anyone @acme.com is
         treated as broker-team)

    Used by the post-match routing logic to AVOID treating the broker's own
    reply as a carrier bid or customer clarification reply. Without this,
    if Jillian or a colleague replies internally to an RFQ thread, the
    system would try to parse their message as a carrier bid.
    """
    if not sender_lower:
        return False

    # Service mailbox — always a broker-side address
    if "agents@golteris.com" in sender_lower:
        return True

    # Extract bare email from 'Name <email>' format for domain match
    bare_email = sender_lower
    if "<" in sender_lower and ">" in sender_lower:
        bare_email = sender_lower.split("<")[1].split(">")[0]

    # 1. Exact user match
    from backend.db.models import User
    exact = db.query(User).filter(User.email == bare_email).first()
    if exact:
        return True

    # 2. Domain match — any User in our DB shares this sender's domain
    if "@" in bare_email:
        domain = bare_email.split("@", 1)[1]
        # Skip free email domains — they can't identify an org
        if domain in ("gmail.com", "yahoo.com", "hotmail.com", "outlook.com",
                      "aol.com", "icloud.com", "live.com", "msn.com"):
            return False
        # Does any User row share this domain?
        domain_match = (
            db.query(User)
            .filter(User.email.like(f"%@{domain}"))
            .first()
        )
        if domain_match:
            return True

    return False


def _is_auto_reply(message: Message) -> bool:
    """
    Detect auto-replies, out-of-office, read receipts, and other noise (#180).

    Checks subject and body for common patterns. Returns True if the message
    should be ignored (not processed through the pipeline).
    """
    subject = (message.subject or "").lower().strip()
    body = (message.body or "").lower().strip()
    sender = (message.sender or "").lower()

    # Auto-reply subject patterns
    auto_subjects = [
        "out of office",
        "automatic reply",
        "auto-reply",
        "autoreply",
        "i am out of the office",
        "i'm out of the office",
        "on vacation",
        "read receipt",
        "delivery notification",
        "undeliverable",
        "mailer-daemon",
        "delivery status notification",
        "your message was read",
    ]
    for pattern in auto_subjects:
        if pattern in subject:
            return True

    # Noreply senders
    noreply_patterns = ["noreply@", "no-reply@", "donotreply@", "mailer-daemon@", "postmaster@"]
    for pattern in noreply_patterns:
        if pattern in sender:
            return True

    # Very short body with no real content (read receipts, delivery notifications)
    if len(body) < 10 and not subject:
        return True

    return False
