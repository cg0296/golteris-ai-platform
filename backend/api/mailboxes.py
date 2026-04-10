"""
backend/api/mailboxes.py — Mailbox management API endpoints (#48).

CRUD for email mailbox connections. The broker configures which inboxes
Golteris monitors and which provider to use for each.

Endpoints:
    GET    /api/mailboxes          — List all configured mailboxes
    POST   /api/mailboxes          — Add a new mailbox connection
    DELETE /api/mailboxes/:id      — Remove a mailbox connection
    POST   /api/mailboxes/:id/test — Test connectivity to a mailbox

Cross-cutting constraints:
    C1 — Each mailbox has an active flag; the worker only polls active mailboxes
    FR-EI-2 — Supports any email provider via the provider_type field
"""

import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session
from typing import Optional

from backend.db.database import get_db
from backend.db.models import Mailbox, MailboxProviderType

logger = logging.getLogger("golteris.api.mailboxes")

router = APIRouter(prefix="/api/mailboxes", tags=["mailboxes"])


class CreateMailboxRequest(BaseModel):
    """Request body for creating a new mailbox connection."""
    name: str
    email: str
    provider_type: str  # "imap", "gmail", "graph", "file"
    config: dict = {}
    poll_interval_seconds: int = 60


class UpdateMailboxRequest(BaseModel):
    """Request body for updating a mailbox."""
    name: Optional[str] = None
    active: Optional[bool] = None
    config: Optional[dict] = None
    poll_interval_seconds: Optional[int] = None


@router.get("")
def list_mailboxes(db: Session = Depends(get_db)):
    """
    List all configured mailboxes with their status and last poll time.

    Used by the Settings page to show connected email providers.
    """
    mailboxes = db.query(Mailbox).order_by(Mailbox.created_at.desc()).all()
    return {
        "mailboxes": [_serialize_mailbox(m) for m in mailboxes],
        "total": len(mailboxes),
    }


@router.post("")
def create_mailbox(body: CreateMailboxRequest, db: Session = Depends(get_db)):
    """
    Add a new mailbox connection.

    Validates the provider type and stores the config. The worker will
    start polling this mailbox on its next cycle if active=True.
    """
    # Validate provider type
    try:
        provider_type = MailboxProviderType(body.provider_type)
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid provider type: {body.provider_type}. Must be one of: {[t.value for t in MailboxProviderType]}"
        )

    mailbox = Mailbox(
        name=body.name,
        email=body.email,
        provider_type=provider_type,
        config=body.config,
        poll_interval_seconds=body.poll_interval_seconds,
    )
    db.add(mailbox)
    db.commit()
    db.refresh(mailbox)

    logger.info("Created mailbox '%s' (%s) with provider %s", body.name, body.email, body.provider_type)
    return _serialize_mailbox(mailbox)


@router.patch("/{mailbox_id}")
def update_mailbox(mailbox_id: int, body: UpdateMailboxRequest, db: Session = Depends(get_db)):
    """
    Update a mailbox's settings (name, active status, config, poll interval).

    C1: Toggling active to False stops the worker from polling this mailbox.
    """
    mailbox = db.query(Mailbox).filter(Mailbox.id == mailbox_id).first()
    if not mailbox:
        raise HTTPException(status_code=404, detail="Mailbox not found")

    if body.name is not None:
        mailbox.name = body.name
    if body.active is not None:
        mailbox.active = body.active
    if body.config is not None:
        mailbox.config = body.config
    if body.poll_interval_seconds is not None:
        mailbox.poll_interval_seconds = body.poll_interval_seconds

    db.commit()
    db.refresh(mailbox)

    logger.info("Updated mailbox #%d '%s'", mailbox_id, mailbox.name)
    return _serialize_mailbox(mailbox)


@router.delete("/{mailbox_id}")
def delete_mailbox(mailbox_id: int, db: Session = Depends(get_db)):
    """
    Remove a mailbox connection.

    Stops polling and deletes the configuration. Does not delete
    messages that were already ingested from this mailbox.
    """
    mailbox = db.query(Mailbox).filter(Mailbox.id == mailbox_id).first()
    if not mailbox:
        raise HTTPException(status_code=404, detail="Mailbox not found")

    db.delete(mailbox)
    db.commit()

    logger.info("Deleted mailbox #%d '%s'", mailbox_id, mailbox.name)
    return {"status": "ok", "message": f"Mailbox '{mailbox.name}' removed"}


@router.post("/{mailbox_id}/test")
def test_mailbox(mailbox_id: int, db: Session = Depends(get_db)):
    """
    Test connectivity to a mailbox by attempting to fetch messages.

    Returns success/failure with any error details. Does not persist
    fetched messages — this is purely a connectivity check.
    """
    mailbox = db.query(Mailbox).filter(Mailbox.id == mailbox_id).first()
    if not mailbox:
        raise HTTPException(status_code=404, detail="Mailbox not found")

    try:
        provider = _create_provider(mailbox)
        messages = provider.fetch_new_messages()
        return {
            "status": "ok",
            "provider": provider.get_provider_name(),
            "messages_found": len(messages),
            "message": f"Connected successfully — found {len(messages)} new messages",
        }
    except Exception as e:
        logger.error("Mailbox test failed for #%d: %s", mailbox_id, e)
        return {
            "status": "error",
            "provider": mailbox.provider_type.value,
            "messages_found": 0,
            "message": f"Connection failed: {str(e)}",
        }


def _create_provider(mailbox: Mailbox):
    """
    Instantiate a MailboxProvider from a Mailbox database record.

    Maps the provider_type to the correct implementation class and
    passes the config JSONB as constructor kwargs.
    """
    config = mailbox.config or {}

    if mailbox.provider_type == MailboxProviderType.IMAP:
        from backend.email.imap_provider import IMAPMailboxProvider
        return IMAPMailboxProvider(
            host=config.get("host", ""),
            port=config.get("port", 993),
            username=config.get("username", ""),
            password=config.get("password", ""),
            folder=config.get("folder", "INBOX"),
        )

    elif mailbox.provider_type == MailboxProviderType.GMAIL:
        from backend.email.gmail_provider import GmailMailboxProvider
        return GmailMailboxProvider(
            client_id=config.get("client_id", ""),
            client_secret=config.get("client_secret", ""),
            refresh_token=config.get("refresh_token", ""),
            user_email=mailbox.email,
        )

    elif mailbox.provider_type == MailboxProviderType.GRAPH:
        from backend.email.graph_provider import GraphMailboxProvider
        return GraphMailboxProvider(
            tenant_id=config.get("tenant_id", ""),
            client_id=config.get("client_id", ""),
            client_secret=config.get("client_secret", ""),
            user_email=config.get("user_email", mailbox.email),
            filter_recipient=config.get("filter_recipient", ""),
            mail_folder=config.get("folder", ""),
        )

    elif mailbox.provider_type == MailboxProviderType.FILE:
        from backend.email.file_provider import FileMailboxProvider
        return FileMailboxProvider(
            seed_dir=config.get("seed_dir", "seed/shipper_emails"),
        )

    else:
        raise ValueError(f"Unknown provider type: {mailbox.provider_type}")


def _serialize_mailbox(mailbox: Mailbox) -> dict:
    """
    Convert a Mailbox to a JSON-safe dict for the API response.

    Redacts sensitive fields (passwords, secrets, tokens) from the config
    to prevent exposure in API responses shown in the browser.
    """
    # Redact sensitive config fields — show that they're set but not the values
    safe_config = {}
    sensitive_keys = {"password", "client_secret", "refresh_token", "token"}
    for key, value in (mailbox.config or {}).items():
        if key in sensitive_keys and value:
            safe_config[key] = "••••••••"
        else:
            safe_config[key] = value

    return {
        "id": mailbox.id,
        "name": mailbox.name,
        "email": mailbox.email,
        "provider_type": mailbox.provider_type.value,
        "config": safe_config,
        "active": mailbox.active,
        "poll_interval_seconds": mailbox.poll_interval_seconds,
        "last_polled_at": mailbox.last_polled_at.isoformat() if mailbox.last_polled_at else None,
        "last_error": mailbox.last_error,
        "created_at": mailbox.created_at.isoformat() if mailbox.created_at else None,
    }
