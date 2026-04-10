"""
backend/services/email_ingestion.py — Email ingestion service.

Bridges the email provider layer and the database/worker layer. Fetches
new messages from a mailbox provider, persists them to the `messages` table,
deduplicates, and enqueues jobs for matching + extraction via the worker (#47).

This is the entry point of the entire pipeline:
    Email arrives → ingestion persists it → worker picks up job
    → matching attaches to RFQ → extraction creates structured fields
    → validation drafts follow-up → quote sheet packages for carriers

Called by:
    - The background worker (backend/worker.py) on each poll cycle
    - Manually for testing or demo resets

Cross-cutting constraints:
    FR-EI-1 — Persists sender, recipients, subject, body, timestamps, thread metadata, raw content
    FR-EI-2 — Supports seeded folder (demo) and live IMAP (testing/production)
    C4 — Audit event for every ingested message
"""

import logging
import os
from datetime import datetime
from typing import Optional

from sqlalchemy.orm import Session

from backend.db.models import AuditEvent, Message, MessageDirection
from backend.email.provider import InboundMessage, MailboxProvider
from backend.worker import enqueue_job

logger = logging.getLogger("golteris.services.email_ingestion")


def ingest_new_messages(
    db: Session,
    provider: MailboxProvider,
) -> list[Message]:
    """
    Fetch new messages from a mailbox provider and persist them.

    For each new message:
    1. Check for duplicates (by message_id_header)
    2. Persist to the `messages` table
    3. Enqueue a "matching" job for the worker to pick up

    The matching job triggers the pipeline: matching → extraction → validation.

    Args:
        db: SQLAlchemy session.
        provider: The mailbox provider to fetch from.

    Returns:
        List of newly persisted Message objects.
    """
    inbound = provider.fetch_new_messages()
    if not inbound:
        return []

    logger.info(
        "Fetched %d new messages from %s provider",
        len(inbound), provider.get_provider_name(),
    )

    persisted = []
    # Build set of our own mailbox addresses so we can skip self-sent emails.
    # When the system sends an outbound reply, it can land back in the same
    # mailbox (e.g., Sent Items, or delivery loop). Without this filter,
    # outbound replies get re-ingested as new inbound and re-processed.
    own_addresses = _get_own_mailbox_addresses(db)

    for msg_data in inbound:
        try:
            # Skip emails FROM our own mailbox — prevents feedback loop
            # where outbound replies get re-ingested as new inbound messages
            if _is_from_own_address(msg_data.sender, own_addresses):
                logger.debug(
                    "Skipping self-sent email from %s: %s",
                    msg_data.sender, msg_data.subject,
                )
                continue

            # Content screening — reject profanity, sexual content, spam
            if _is_inappropriate_content(msg_data):
                logger.warning(
                    "Blocked inappropriate email from %s: %s",
                    msg_data.sender, msg_data.subject,
                )
                continue

            message = _persist_message(db, msg_data)
            if message:
                # Enqueue matching job — the worker will dispatch to the
                # matching service which decides: attach to existing RFQ,
                # create new RFQ (trigger extraction), or send to review queue
                enqueue_job(db, "matching", {"message_id": message.id})

                # Audit event — visible in Recent Activity feed (C4)
                _log_ingestion_event(db, message)

                persisted.append(message)

        except Exception as e:
            logger.error(
                "Failed to ingest message from %s (subject: %s): %s",
                msg_data.sender, msg_data.subject, e,
            )

    logger.info("Ingested %d new messages", len(persisted))
    return persisted


def _persist_message(db: Session, msg_data: InboundMessage) -> Optional[Message]:
    """
    Persist an inbound message to the database.

    Deduplicates by message_id_header — if a message with the same
    Message-ID already exists, it's skipped (IMAP re-fetch protection).

    Args:
        db: SQLAlchemy session.
        msg_data: The normalized inbound message from the provider.

    Returns:
        The persisted Message, or None if it's a duplicate.
    """
    # Deduplicate by Message-ID header
    if msg_data.message_id_header:
        existing = (
            db.query(Message)
            .filter(Message.message_id_header == msg_data.message_id_header)
            .first()
        )
        if existing:
            logger.debug(
                "Skipping duplicate message: %s (already message #%d)",
                msg_data.message_id_header, existing.id,
            )
            return None

    # Parse received_at if provided
    received_at = datetime.utcnow()
    if msg_data.received_at:
        try:
            received_at = datetime.fromisoformat(msg_data.received_at)
        except ValueError:
            pass

    message = Message(
        sender=msg_data.sender,
        recipients=msg_data.recipients,
        subject=msg_data.subject,
        body=msg_data.body,
        raw_content=msg_data.raw_content,
        direction=MessageDirection.INBOUND,
        thread_id=msg_data.thread_id,
        in_reply_to=msg_data.in_reply_to,
        message_id_header=msg_data.message_id_header,
        received_at=received_at,
    )
    db.add(message)
    db.commit()
    db.refresh(message)

    logger.info(
        "Persisted message #%d from %s: %s",
        message.id, message.sender, message.subject or "(no subject)",
    )

    return message


def _log_ingestion_event(db: Session, message: Message) -> None:
    """
    Log an audit event for a newly ingested message (C4).

    Uses plain English per C3 — the broker sees "New email received"
    in the activity feed, not "message_ingested" or "IMAP_FETCH_OK".
    """
    event = AuditEvent(
        rfq_id=None,  # Not linked to an RFQ yet — matching will do that
        event_type="email_received",
        actor="email_ingestion",
        description=f"New email received from {message.sender}: {message.subject or '(no subject)'}",
        event_data={
            "message_id": message.id,
            "sender": message.sender,
            "subject": message.subject,
            "has_thread_id": message.thread_id is not None,
            "has_in_reply_to": message.in_reply_to is not None,
        },
    )
    db.add(event)
    db.commit()


def _is_inappropriate_content(msg: InboundMessage) -> bool:
    """
    Screen inbound emails for profanity, sexual content, and obvious spam/pranks.

    Returns True if the message should be blocked (not ingested into the app).
    Checks subject and body against a blocklist of inappropriate terms.
    """
    # Combine subject and body for scanning
    text = f"{msg.subject or ''} {msg.body or ''}".lower()

    # Blocklist — common profanity, sexual terms, and spam indicators.
    # This is a simple keyword filter. For production, consider a proper
    # content moderation API (OpenAI moderation, Perspective API, etc.)
    blocklist = [
        # Profanity
        "fuck", "shit", "bitch", "asshole", "bastard", "damn", "crap",
        "dick", "piss", "cunt", "motherfucker", "bullshit",
        # Sexual content
        "porn", "xxx", "nude", "naked", "sex video", "onlyfans",
        "viagra", "cialis", "erectile",
        # Common spam/scam patterns
        "nigerian prince", "you have won", "claim your prize",
        "bitcoin giveaway", "double your money", "act now",
        "wire transfer immediately",
    ]

    for term in blocklist:
        if term in text:
            return True

    return False


def _get_own_mailbox_addresses(db: Session) -> set[str]:
    """
    Collect all email addresses that belong to our own mailboxes.

    Used to filter out self-sent emails so outbound replies don't get
    re-ingested as new inbound messages (feedback loop prevention).

    Includes:
    - All active mailbox addresses from the database
    - The MS_GRAPH_USER_EMAIL env var (legacy config)
    - The MS_GRAPH_FILTER_RECIPIENT env var (alias address)
    """
    addresses = set()

    # From env vars (legacy/fallback config)
    graph_user = os.environ.get("MS_GRAPH_USER_EMAIL", "")
    if graph_user:
        addresses.add(graph_user.lower())
    graph_filter = os.environ.get("MS_GRAPH_FILTER_RECIPIENT", "")
    if graph_filter:
        addresses.add(graph_filter.lower())
    imap_user = os.environ.get("IMAP_USER", "")
    if imap_user:
        addresses.add(imap_user.lower())

    # From database mailboxes
    try:
        from backend.db.models import Mailbox
        mailboxes = db.query(Mailbox).filter(Mailbox.active == True).all()
        for mb in mailboxes:
            if mb.email:
                addresses.add(mb.email.lower())
    except Exception:
        pass  # Table might not exist yet

    return addresses


def _is_from_own_address(sender: str, own_addresses: set[str]) -> bool:
    """
    Check if a message sender matches one of our own mailbox addresses.

    Handles the "Display Name <email>" format that Graph returns.
    """
    if not sender or not own_addresses:
        return False

    # Extract bare email from "Display Name <email>" format
    import re
    match = re.search(r'<([^>]+)>', sender)
    email = (match.group(1) if match else sender).strip().lower()

    return email in own_addresses


def get_providers_from_db(db: Session) -> list[MailboxProvider]:
    """
    Get all active mailbox providers from the database (#48).

    Reads the mailboxes table and instantiates a provider for each active
    mailbox. The worker calls this to poll all configured inboxes.

    Args:
        db: SQLAlchemy session.

    Returns:
        List of configured MailboxProvider instances for active mailboxes.
    """
    from backend.db.models import Mailbox
    from backend.api.mailboxes import _create_provider

    try:
        mailboxes = db.query(Mailbox).filter(Mailbox.active == True).all()
        if mailboxes:
            providers = []
            for mb in mailboxes:
                try:
                    provider = _create_provider(mb)
                    providers.append(provider)
                    logger.info("Loaded mailbox '%s' (%s) with %s provider", mb.name, mb.email, mb.provider_type.value)
                except Exception as e:
                    logger.error("Failed to create provider for mailbox '%s': %s", mb.name, e)
            if providers:
                return providers
    except Exception as e:
        # Table might not exist yet (fresh install) — fall through to env vars
        logger.debug("Could not read mailboxes table: %s", e)

    # Fall back to env-var config if no database mailboxes are configured
    return [get_provider_from_config()]


def get_provider_from_config() -> MailboxProvider:
    """
    Create a mailbox provider from environment variables (legacy fallback).

    Used when no mailboxes are configured in the database. This preserves
    backwards compatibility with the original env-var-only setup.

    Priority order:
    1. Microsoft Graph API (if MS_GRAPH_CLIENT_ID is set) — for Microsoft 365
    2. IMAP (if IMAP_HOST is set) — for Gmail, Yahoo, any IMAP server
    3. Seed file provider — demo fallback

    Returns:
        A configured MailboxProvider instance.
    """
    # Check if Microsoft Graph is configured
    graph_client_id = os.environ.get("MS_GRAPH_CLIENT_ID", "")
    graph_user = os.environ.get("MS_GRAPH_USER_EMAIL", "")

    if graph_client_id and graph_user:
        from backend.email.graph_provider import GraphMailboxProvider
        filter_recipient = os.environ.get("MS_GRAPH_FILTER_RECIPIENT", "")
        logger.info("Using Graph API provider: %s (filter: %s)", graph_user, filter_recipient or "none")
        return GraphMailboxProvider()

    # Check if IMAP is configured
    imap_host = os.environ.get("IMAP_HOST", "")
    imap_user = os.environ.get("IMAP_USER", "")

    if imap_host and imap_user:
        from backend.email.imap_provider import IMAPMailboxProvider
        logger.info("Using IMAP provider: %s@%s", imap_user, imap_host)
        return IMAPMailboxProvider()

    # Fall back to seed file provider
    from backend.email.file_provider import FileMailboxProvider
    seed_dir = os.environ.get("SEED_EMAIL_DIR", "seed/shipper_emails")
    logger.info("Using file provider: %s", seed_dir)
    return FileMailboxProvider(seed_dir)
