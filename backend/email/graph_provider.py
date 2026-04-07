"""
backend/email/graph_provider.py — Microsoft Graph API mailbox provider.

Connects to Microsoft 365 mailboxes via the Graph API using OAuth2 client
credentials flow. This is the recommended provider for Outlook/Exchange
mailboxes since Microsoft has deprecated basic auth for IMAP.

Advantages over IMAP:
    - OAuth2 client credentials (no user password needed)
    - Can filter by recipient (only fetch emails to agents@golteris.com)
    - Can send email via the same API (Mail.Send permission)
    - Supports webhooks for real-time push notifications (future)
    - Same API works for Teams chat integration (future)

Setup:
    1. Register an app in Microsoft Entra (Azure AD)
    2. Grant Mail.Read + Mail.ReadWrite application permissions
    3. Grant admin consent
    4. Create a client secret
    5. Set env vars: MS_GRAPH_TENANT_ID, MS_GRAPH_CLIENT_ID,
       MS_GRAPH_CLIENT_SECRET, MS_GRAPH_USER_EMAIL

Called by:
    backend/services/email_ingestion.py via get_provider_from_config()

Cross-cutting constraints:
    FR-EI-1 — Persists sender, recipients, subject, body, timestamps, thread metadata
    FR-EI-2 — Supports Microsoft 365 as a live email provider
"""

import logging
import os
from datetime import datetime, timezone
from typing import Optional

import msal
import requests

from backend.email.provider import InboundMessage, MailboxProvider

logger = logging.getLogger("golteris.email.graph_provider")

GRAPH_BASE_URL = "https://graph.microsoft.com/v1.0"


class GraphMailboxProvider(MailboxProvider):
    """
    Fetches unread emails from a Microsoft 365 mailbox via Graph API.

    Uses OAuth2 client credentials flow — no user interaction needed.
    Marks messages as read after fetching so they aren't re-processed.
    Can optionally filter by recipient address (e.g., only emails sent
    to agents@golteris.com, ignoring personal mail in the same inbox).
    """

    def __init__(
        self,
        tenant_id: Optional[str] = None,
        client_id: Optional[str] = None,
        client_secret: Optional[str] = None,
        user_email: Optional[str] = None,
        filter_recipient: Optional[str] = None,
        mail_folder: Optional[str] = None,
    ):
        """
        Args:
            tenant_id: Azure AD tenant ID (default: MS_GRAPH_TENANT_ID env var)
            client_id: App registration client ID (default: MS_GRAPH_CLIENT_ID env var)
            client_secret: App client secret (default: MS_GRAPH_CLIENT_SECRET env var)
            user_email: The mailbox to read from (default: MS_GRAPH_USER_EMAIL env var)
            filter_recipient: If set, only fetch emails sent TO this address.
                Useful when the mailbox has an alias (e.g., agents@golteris.com)
                and you only want emails addressed to that alias, not all mail.
            mail_folder: If set, only fetch from this folder name (e.g., "agent-golteris").
                When an Outlook rule routes alias emails to a dedicated folder,
                this is cleaner than scanning the entire mailbox.
        """
        self.tenant_id = tenant_id or os.environ.get("MS_GRAPH_TENANT_ID", "")
        self.client_id = client_id or os.environ.get("MS_GRAPH_CLIENT_ID", "")
        self.client_secret = client_secret or os.environ.get("MS_GRAPH_CLIENT_SECRET", "")
        self.user_email = user_email or os.environ.get("MS_GRAPH_USER_EMAIL", "")
        self.filter_recipient = filter_recipient or os.environ.get("MS_GRAPH_FILTER_RECIPIENT", "")
        self.mail_folder = mail_folder or os.environ.get("MS_GRAPH_MAIL_FOLDER", "")
        self._token_cache: Optional[str] = None
        self._folder_id: Optional[str] = None

    def fetch_new_messages(self) -> list[InboundMessage]:
        """
        Fetch unread messages from the mailbox via Graph API.

        Filters for unread messages, optionally filtered by recipient.
        After fetching, marks each message as read so it won't be
        re-fetched on the next poll.

        Returns:
            List of new InboundMessage objects, empty if none or on error.
        """
        if not self.client_id or not self.user_email:
            logger.warning("Graph API not configured — skipping")
            return []

        token = self._get_access_token()
        if not token:
            return []

        messages = []

        try:
            # Build the query — fetch unread messages, newest first
            # Select only the fields we need to minimize payload
            params = {
                "$top": "25",
                "$select": "id,subject,from,toRecipients,ccRecipients,body,receivedDateTime,conversationId,internetMessageId,internetMessageHeaders",
                "$filter": "isRead eq false",
                "$orderby": "receivedDateTime desc",
            }

            # If a specific folder is configured (e.g., "agent-golteris" from an
            # Outlook rule), only fetch from that folder. Otherwise scan all mail.
            if self.mail_folder:
                folder_id = self._resolve_folder_id(token)
                if folder_id:
                    url = f"{GRAPH_BASE_URL}/users/{self.user_email}/mailFolders/{folder_id}/messages"
                else:
                    logger.warning("Folder '%s' not found — falling back to all messages", self.mail_folder)
                    url = f"{GRAPH_BASE_URL}/users/{self.user_email}/messages"
            else:
                url = f"{GRAPH_BASE_URL}/users/{self.user_email}/messages"

            response = requests.get(
                url,
                headers={"Authorization": f"Bearer {token}"},
                params=params,
            )

            if response.status_code != 200:
                logger.error("Graph API error %d: %s", response.status_code, response.text[:500])
                return []

            raw_messages = response.json().get("value", [])
            logger.info("Graph API returned %d unread messages", len(raw_messages))

            for raw_msg in raw_messages:
                # Filter by recipient if configured
                if self.filter_recipient and not self._is_addressed_to(raw_msg, self.filter_recipient):
                    continue

                parsed = self._parse_message(raw_msg)
                if parsed:
                    messages.append(parsed)

                    # Mark as read so we don't re-fetch
                    self._mark_as_read(token, raw_msg["id"])

        except requests.RequestException as e:
            logger.error("Graph API request failed: %s", e)
        except Exception as e:
            logger.exception("Unexpected Graph API error: %s", e)

        if messages:
            logger.info("Ingested %d messages from Graph API", len(messages))

        return messages

    def send_message(
        self,
        to: str,
        subject: str,
        body: str,
        reply_to_message_id: str | None = None,
    ) -> dict:
        """
        Send an email via Microsoft Graph API's /sendMail endpoint (#25).

        Uses the same OAuth2 client credentials as fetch. Requires
        Mail.Send application permission in the Entra app registration.

        C2 CONSTRAINT: Only called by email_send service after approval check.

        Args:
            to: Recipient email address
            subject: Email subject
            body: Email body (plain text)
            reply_to_message_id: For threading, the original message's internet message ID

        Returns:
            Dict with success, message_id, and error fields.
        """
        if not self.client_id or not self.user_email:
            return {"success": False, "message_id": None, "error": "Graph API not configured"}

        token = self._get_access_token()
        if not token:
            return {"success": False, "message_id": None, "error": "Failed to get Graph access token"}

        try:
            # Build the Graph API sendMail payload
            mail_payload: dict = {
                "message": {
                    "subject": subject,
                    "body": {
                        "contentType": "Text",
                        "content": body,
                    },
                    "toRecipients": [
                        {"emailAddress": {"address": to}}
                    ],
                },
                "saveToSentItems": True,
            }

            # If replying to a thread, use Graph's conversationId-based threading.
            # Note: Graph API rejects In-Reply-To as a custom header — it requires
            # custom headers to start with "x-". Thread linking is handled by Graph
            # automatically when the conversation is in the same mailbox.
            # We skip the header and let Graph handle threading natively.

            url = f"{GRAPH_BASE_URL}/users/{self.user_email}/sendMail"
            resp = requests.post(
                url,
                headers={
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/json",
                },
                json=mail_payload,
                timeout=30,
            )

            if resp.status_code == 202:
                # 202 Accepted — email queued for delivery by Graph
                logger.info("Email sent via Graph to %s: %s", to, subject)
                return {"success": True, "message_id": None, "error": None}
            else:
                error_detail = resp.text[:500]
                logger.error("Graph sendMail failed (%d): %s", resp.status_code, error_detail)
                return {"success": False, "message_id": None, "error": f"Graph API {resp.status_code}: {error_detail}"}

        except requests.RequestException as e:
            logger.error("Graph sendMail request error: %s", e)
            return {"success": False, "message_id": None, "error": str(e)}

    def get_provider_name(self) -> str:
        return "graph"

    def _get_access_token(self) -> Optional[str]:
        """
        Get an OAuth2 access token using client credentials flow.

        Tokens are cached by MSAL and refreshed automatically.
        """
        try:
            app = msal.ConfidentialClientApplication(
                self.client_id,
                authority=f"https://login.microsoftonline.com/{self.tenant_id}",
                client_credential=self.client_secret,
            )
            result = app.acquire_token_for_client(
                scopes=["https://graph.microsoft.com/.default"]
            )

            if "access_token" in result:
                return result["access_token"]

            logger.error("Graph auth failed: %s", result.get("error_description"))
            return None

        except Exception as e:
            logger.exception("Graph auth error: %s", e)
            return None

    def _parse_message(self, raw: dict) -> Optional[InboundMessage]:
        """
        Parse a Graph API message object into an InboundMessage.

        Extracts all fields needed for the messages table including
        thread metadata for the matching service.
        """
        try:
            # Sender
            from_data = raw.get("from", {}).get("emailAddress", {})
            sender = from_data.get("address", "")
            sender_name = from_data.get("name", "")
            if sender_name:
                sender = f"{sender_name} <{sender}>"

            # Recipients (To + Cc)
            to_list = [
                r.get("emailAddress", {}).get("address", "")
                for r in raw.get("toRecipients", [])
            ]
            cc_list = [
                r.get("emailAddress", {}).get("address", "")
                for r in raw.get("ccRecipients", [])
            ]
            recipients = ", ".join(to_list + cc_list)

            # Subject
            subject = raw.get("subject", "")

            # Body — prefer text content, Graph returns HTML by default
            body_data = raw.get("body", {})
            body = body_data.get("content", "")
            if body_data.get("contentType") == "html":
                # Strip HTML tags for plain text extraction
                import re
                body = re.sub(r"<[^>]+>", "", body)
                body = body.strip()

            # Thread metadata
            conversation_id = raw.get("conversationId")
            internet_message_id = raw.get("internetMessageId")

            # Extract In-Reply-To from internet message headers
            in_reply_to = None
            headers = raw.get("internetMessageHeaders", [])
            for header in headers:
                if header.get("name", "").lower() == "in-reply-to":
                    in_reply_to = header.get("value")
                    break

            # Received timestamp
            received_str = raw.get("receivedDateTime", "")

            return InboundMessage(
                sender=sender,
                recipients=recipients,
                subject=subject,
                body=body,
                raw_content=str(raw),
                thread_id=conversation_id,
                in_reply_to=in_reply_to,
                message_id_header=internet_message_id,
                received_at=received_str,
            )

        except Exception as e:
            logger.error("Failed to parse Graph message: %s", e)
            return None

    def _resolve_folder_id(self, token: str) -> Optional[str]:
        """
        Look up the Graph folder ID for a folder name (e.g., "agent-golteris").

        Caches the result so we only do this lookup once per provider instance.
        """
        if self._folder_id:
            return self._folder_id

        try:
            response = requests.get(
                f"{GRAPH_BASE_URL}/users/{self.user_email}/mailFolders",
                headers={"Authorization": f"Bearer {token}"},
                params={"$select": "id,displayName"},
            )
            if response.status_code == 200:
                for folder in response.json().get("value", []):
                    if folder.get("displayName", "").lower() == self.mail_folder.lower():
                        self._folder_id = folder["id"]
                        logger.info("Resolved folder '%s' -> %s", self.mail_folder, self._folder_id[:20])
                        return self._folder_id
        except Exception as e:
            logger.error("Failed to resolve folder '%s': %s", self.mail_folder, e)

        return None

    def _mark_as_read(self, token: str, message_id: str) -> None:
        """
        Mark a message as read on the server so it won't be re-fetched.

        Uses the Mail.ReadWrite permission to PATCH the isRead property.
        """
        try:
            requests.patch(
                f"{GRAPH_BASE_URL}/users/{self.user_email}/messages/{message_id}",
                headers={
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/json",
                },
                json={"isRead": True},
            )
        except Exception as e:
            logger.error("Failed to mark message as read: %s", e)

    def _is_addressed_to(self, raw_msg: dict, target_email: str) -> bool:
        """
        Check if a message was originally addressed to a specific email.

        Microsoft aliases resolve to the primary mailbox address in the
        toRecipients field, so we check the raw internet 'To' header
        which preserves the original address (e.g., agents@golteris.com
        even though Graph shows Curt@goldentechsolutionsllc.com).

        Falls back to checking toRecipients and ccRecipients if the
        internet header isn't available.
        """
        target = target_email.lower()

        # Check the raw internet To header first — preserves the original
        # address before alias resolution
        for header in raw_msg.get("internetMessageHeaders", []):
            if header.get("name", "").lower() == "to":
                if target in header.get("value", "").lower():
                    return True

        # Fall back to Graph's resolved toRecipients/ccRecipients
        for recipient in raw_msg.get("toRecipients", []):
            if recipient.get("emailAddress", {}).get("address", "").lower() == target:
                return True
        for recipient in raw_msg.get("ccRecipients", []):
            if recipient.get("emailAddress", {}).get("address", "").lower() == target:
                return True
        return False
