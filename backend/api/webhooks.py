"""
backend/api/webhooks.py — Webhook endpoints for email push notifications (#133).

Handles Microsoft Graph change notifications so new emails appear in
Golteris within seconds instead of waiting for the poll interval.

Graph webhook flow:
    1. We create a subscription via POST /subscriptions on Graph API
    2. Graph validates our endpoint by sending GET with ?validationToken=xxx
    3. We respond with the token in plain text (200 OK)
    4. When a new email arrives, Graph POSTs a notification with the message resource
    5. We fetch that specific message and ingest it immediately

Endpoints:
    POST /api/webhooks/graph  — Receives Graph change notifications
                                Also handles validation during subscription creation

Security:
    - Validates clientState token on every notification (prevents spoofing)
    - Rejects notifications with missing or invalid clientState

Cross-cutting constraints:
    FR-EI-1 — Persists sender, recipients, subject, body, timestamps, thread metadata
    C4 — Audit event for every ingested message
"""

import logging
import os

from fastapi import APIRouter, Depends, Request, Response
from fastapi.responses import PlainTextResponse
from sqlalchemy.orm import Session

from backend.db.database import get_db

logger = logging.getLogger("golteris.webhooks.graph")

router = APIRouter(prefix="/api/webhooks", tags=["webhooks"])

# Secret token we include when creating the subscription — Graph echoes it
# back on every notification so we can verify it's legitimate.
GRAPH_WEBHOOK_SECRET = os.environ.get("GRAPH_WEBHOOK_SECRET", "golteris-graph-webhook-secret")


@router.post("/graph")
async def graph_webhook(request: Request, db: Session = Depends(get_db)):
    """
    Receive Microsoft Graph change notifications for new emails.

    This endpoint serves two purposes:
    1. **Validation** — When we create a subscription, Graph sends a POST with
       a validationToken query param. We must respond with the token in plain
       text within 10 seconds.
    2. **Notifications** — When a new email arrives, Graph sends a POST with
       a JSON body containing the changed resource. We fetch and ingest it.
    """
    # --- Subscription validation ---
    # Graph sends validationToken as a query param during subscription creation.
    # We must echo it back as plain text to prove we own the endpoint.
    validation_token = request.query_params.get("validationToken")
    if validation_token:
        logger.info("Graph webhook validation — responding with token")
        return PlainTextResponse(content=validation_token, status_code=200)

    # --- Change notification ---
    try:
        body = await request.json()
    except Exception:
        logger.error("Graph webhook — invalid JSON body")
        return Response(status_code=400)

    notifications = body.get("value", [])
    if not notifications:
        logger.debug("Graph webhook — empty notification, ignoring")
        return Response(status_code=202)

    ingested_count = 0

    for notification in notifications:
        # Verify clientState to prevent spoofed notifications
        client_state = notification.get("clientState", "")
        if client_state != GRAPH_WEBHOOK_SECRET:
            logger.warning("Graph webhook — invalid clientState, rejecting notification")
            continue

        change_type = notification.get("changeType", "")
        resource = notification.get("resource", "")

        # We only care about new messages (created)
        if change_type != "created":
            logger.debug("Graph webhook — ignoring changeType=%s", change_type)
            continue

        # resource looks like: "users/{user-id}/messages/{message-id}"
        # or "users/{user-id}/mailFolders/{folder-id}/messages/{message-id}"
        logger.info("Graph webhook — new message notification: %s", resource)

        try:
            ingested = _fetch_and_ingest_message(db, resource)
            if ingested:
                ingested_count += 1
        except Exception as e:
            logger.exception("Graph webhook — failed to process notification: %s", e)

    if ingested_count > 0:
        logger.info("Graph webhook — ingested %d new messages", ingested_count)

    # Graph requires 202 Accepted response within 30 seconds
    return Response(status_code=202)


def _fetch_and_ingest_message(db: Session, resource: str) -> bool:
    """
    Fetch a specific message from Graph API and ingest it.

    The resource path from the notification tells us exactly which message
    to fetch, so we don't need to scan the entire mailbox.

    Args:
        db: SQLAlchemy session
        resource: Graph resource path (e.g., "users/{id}/messages/{id}")

    Returns:
        True if a message was ingested, False if skipped (duplicate, filtered, etc.)
    """
    import requests
    import msal

    tenant_id = os.environ.get("MS_GRAPH_TENANT_ID", "")
    client_id = os.environ.get("MS_GRAPH_CLIENT_ID", "")
    client_secret = os.environ.get("MS_GRAPH_CLIENT_SECRET", "")
    filter_recipient = os.environ.get("MS_GRAPH_FILTER_RECIPIENT", "")

    if not client_id or not tenant_id:
        logger.error("Graph API not configured — cannot process webhook notification")
        return False

    # Get access token
    app = msal.ConfidentialClientApplication(
        client_id,
        authority=f"https://login.microsoftonline.com/{tenant_id}",
        client_credential=client_secret,
    )
    result = app.acquire_token_for_client(scopes=["https://graph.microsoft.com/.default"])
    token = result.get("access_token")
    if not token:
        logger.error("Graph auth failed for webhook processing")
        return False

    # Fetch the specific message
    url = f"https://graph.microsoft.com/v1.0/{resource}"
    params = {
        "$select": "id,subject,from,toRecipients,ccRecipients,body,receivedDateTime,conversationId,internetMessageId,internetMessageHeaders,isRead"
    }
    resp = requests.get(url, headers={"Authorization": f"Bearer {token}"}, params=params)

    if resp.status_code != 200:
        logger.error("Graph webhook — failed to fetch message: %d %s", resp.status_code, resp.text[:200])
        return False

    raw_msg = resp.json()

    # Apply recipient filter if configured (same logic as the poll provider)
    if filter_recipient:
        from backend.email.graph_provider import GraphMailboxProvider
        provider = GraphMailboxProvider()
        if not provider._is_addressed_to(raw_msg, filter_recipient):
            logger.debug("Graph webhook — message not addressed to %s, skipping", filter_recipient)
            # Mark as read so it doesn't clog the unread count
            _mark_as_read(token, resource)
            return False

    # Parse the message using the existing Graph provider
    from backend.email.graph_provider import GraphMailboxProvider
    provider = GraphMailboxProvider()
    parsed = provider._parse_message(raw_msg)

    if not parsed:
        logger.error("Graph webhook — failed to parse message")
        return False

    # Ingest using the existing service (handles dedup, persist, enqueue jobs)
    from backend.services.email_ingestion import ingest_new_messages
    from backend.email.provider import MailboxProvider, InboundMessage

    # Create a minimal provider that returns just this one message
    class SingleMessageProvider(MailboxProvider):
        def __init__(self, msg: InboundMessage):
            self._msg = msg
            self._consumed = False

        def fetch_new_messages(self) -> list[InboundMessage]:
            if self._consumed:
                return []
            self._consumed = True
            return [self._msg]

        def send_message(self, to, subject, body, reply_to_message_id=None):
            raise NotImplementedError("Webhook provider does not send")

        def get_provider_name(self):
            return "graph-webhook"

    messages = ingest_new_messages(db, SingleMessageProvider(parsed))

    # Mark as read on Graph so it doesn't show up in polling too
    if messages:
        _mark_as_read(token, resource)

    return len(messages) > 0


def _mark_as_read(token: str, resource: str) -> None:
    """Mark a message as read on Graph to prevent re-processing by the poller."""
    import requests
    try:
        # Extract the message URL from the resource path
        url = f"https://graph.microsoft.com/v1.0/{resource}"
        requests.patch(
            url,
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            json={"isRead": True},
        )
    except Exception as e:
        logger.error("Graph webhook — failed to mark message as read: %s", e)
