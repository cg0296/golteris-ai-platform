"""
backend/services/graph_subscriptions.py — Microsoft Graph subscription management (#133).

Creates, renews, and deletes Graph change notification subscriptions for
real-time email push. Graph subscriptions have a max lifetime of 3 days
(4230 minutes) and must be renewed before expiry.

Subscription lifecycle:
    1. create_subscription() — called from admin API or on startup
    2. Graph validates our webhook URL (sends validationToken)
    3. Subscription active — Graph pushes notifications for new emails
    4. renew_subscription() — called before expiry (worker or scheduler)
    5. delete_subscription() — called on mailbox disconnect or app shutdown

Called by:
    - POST /api/admin/graph/subscribe (admin UI)
    - Worker scheduler (auto-renewal)

Cross-cutting constraints:
    C1 — Subscription can be stopped by the admin at any time
"""

import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Optional

import msal
import requests

logger = logging.getLogger("golteris.services.graph_subscriptions")

GRAPH_BASE_URL = "https://graph.microsoft.com/v1.0"
# Max subscription lifetime for mail resources is 4230 minutes (~2.94 days)
MAX_SUBSCRIPTION_MINUTES = 4230
# Renew when less than this many minutes remain
RENEWAL_THRESHOLD_MINUTES = 60


def create_subscription(
    webhook_url: str,
    client_state: str = "",
) -> Optional[dict]:
    """
    Create a Graph change notification subscription for new emails.

    Subscribes to the configured mailbox's messages resource. Graph will
    send POST notifications to webhook_url when new emails arrive.

    Args:
        webhook_url: The publicly accessible URL for our webhook endpoint
                     (e.g., "https://app.golteris.com/api/webhooks/graph")
        client_state: Secret token included in each notification for verification

    Returns:
        Subscription dict from Graph (id, expirationDateTime, resource) or None on failure
    """
    token = _get_token()
    if not token:
        return None

    user_email = os.environ.get("MS_GRAPH_USER_EMAIL", "")
    mail_folder = os.environ.get("MS_GRAPH_MAIL_FOLDER", "")

    if not user_email:
        logger.error("MS_GRAPH_USER_EMAIL not set — cannot create subscription")
        return None

    # Build the resource path — subscribe to messages in the configured folder
    if mail_folder:
        # Need to resolve folder ID first
        folder_id = _resolve_folder_id(token, user_email, mail_folder)
        if folder_id:
            resource = f"users/{user_email}/mailFolders/{folder_id}/messages"
        else:
            logger.warning("Folder '%s' not found — subscribing to all messages", mail_folder)
            resource = f"users/{user_email}/messages"
    else:
        resource = f"users/{user_email}/messages"

    # Expiration — max 4230 minutes from now
    expiration = datetime.now(timezone.utc) + timedelta(minutes=MAX_SUBSCRIPTION_MINUTES)

    payload = {
        "changeType": "created",
        "notificationUrl": webhook_url,
        "resource": resource,
        "expirationDateTime": expiration.isoformat(),
        "clientState": client_state,
    }

    logger.info("Creating Graph subscription: resource=%s, webhook=%s", resource, webhook_url)

    try:
        resp = requests.post(
            f"{GRAPH_BASE_URL}/subscriptions",
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=30,
        )

        if resp.status_code in (200, 201):
            sub = resp.json()
            logger.info(
                "Graph subscription created: id=%s, expires=%s",
                sub.get("id"), sub.get("expirationDateTime"),
            )
            return sub
        else:
            logger.error(
                "Graph subscription creation failed (%d): %s",
                resp.status_code, resp.text[:500],
            )
            return None

    except Exception as e:
        logger.exception("Graph subscription creation error: %s", e)
        return None


def renew_subscription(subscription_id: str) -> Optional[dict]:
    """
    Renew an existing Graph subscription before it expires.

    Extends the expiration by the maximum allowed duration.

    Args:
        subscription_id: The Graph subscription ID to renew

    Returns:
        Updated subscription dict or None on failure
    """
    token = _get_token()
    if not token:
        return None

    new_expiration = datetime.now(timezone.utc) + timedelta(minutes=MAX_SUBSCRIPTION_MINUTES)

    try:
        resp = requests.patch(
            f"{GRAPH_BASE_URL}/subscriptions/{subscription_id}",
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            },
            json={"expirationDateTime": new_expiration.isoformat()},
            timeout=30,
        )

        if resp.status_code == 200:
            sub = resp.json()
            logger.info("Graph subscription renewed: id=%s, expires=%s", subscription_id, sub.get("expirationDateTime"))
            return sub
        else:
            logger.error("Graph subscription renewal failed (%d): %s", resp.status_code, resp.text[:300])
            return None

    except Exception as e:
        logger.exception("Graph subscription renewal error: %s", e)
        return None


def delete_subscription(subscription_id: str) -> bool:
    """
    Delete a Graph subscription (stop receiving notifications).

    Args:
        subscription_id: The Graph subscription ID to delete

    Returns:
        True if deleted successfully
    """
    token = _get_token()
    if not token:
        return False

    try:
        resp = requests.delete(
            f"{GRAPH_BASE_URL}/subscriptions/{subscription_id}",
            headers={"Authorization": f"Bearer {token}"},
            timeout=30,
        )

        if resp.status_code == 204:
            logger.info("Graph subscription deleted: %s", subscription_id)
            return True
        else:
            logger.error("Graph subscription delete failed (%d): %s", resp.status_code, resp.text[:300])
            return False

    except Exception as e:
        logger.exception("Graph subscription delete error: %s", e)
        return False


def get_subscription(subscription_id: str) -> Optional[dict]:
    """Get the current state of a Graph subscription."""
    token = _get_token()
    if not token:
        return None

    try:
        resp = requests.get(
            f"{GRAPH_BASE_URL}/subscriptions/{subscription_id}",
            headers={"Authorization": f"Bearer {token}"},
            timeout=30,
        )
        if resp.status_code == 200:
            return resp.json()
        return None
    except Exception:
        return None


def needs_renewal(expiration_str: str) -> bool:
    """Check if a subscription needs renewal (less than RENEWAL_THRESHOLD_MINUTES remaining)."""
    try:
        expiry = datetime.fromisoformat(expiration_str.replace("Z", "+00:00"))
        remaining = (expiry - datetime.now(timezone.utc)).total_seconds() / 60
        return remaining < RENEWAL_THRESHOLD_MINUTES
    except Exception:
        return True  # If we can't parse, renew to be safe


def _get_token() -> Optional[str]:
    """Get a Graph API access token using client credentials."""
    tenant_id = os.environ.get("MS_GRAPH_TENANT_ID", "")
    client_id = os.environ.get("MS_GRAPH_CLIENT_ID", "")
    client_secret = os.environ.get("MS_GRAPH_CLIENT_SECRET", "")

    if not client_id:
        logger.error("Graph API not configured — MS_GRAPH_CLIENT_ID missing")
        return None

    try:
        app = msal.ConfidentialClientApplication(
            client_id,
            authority=f"https://login.microsoftonline.com/{tenant_id}",
            client_credential=client_secret,
        )
        result = app.acquire_token_for_client(scopes=["https://graph.microsoft.com/.default"])
        return result.get("access_token")
    except Exception as e:
        logger.exception("Graph auth error: %s", e)
        return None


def _resolve_folder_id(token: str, user_email: str, folder_name: str) -> Optional[str]:
    """Look up a Graph mail folder ID by name."""
    try:
        resp = requests.get(
            f"{GRAPH_BASE_URL}/users/{user_email}/mailFolders",
            headers={"Authorization": f"Bearer {token}"},
            params={"$select": "id,displayName"},
        )
        if resp.status_code == 200:
            for folder in resp.json().get("value", []):
                if folder.get("displayName", "").lower() == folder_name.lower():
                    return folder["id"]
    except Exception as e:
        logger.error("Failed to resolve folder '%s': %s", folder_name, e)
    return None
