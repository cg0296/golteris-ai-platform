"""
backend/email/gmail_provider.py — Gmail API mailbox provider (#48).

Connects to Gmail using OAuth2 (user consent flow) for reading and sending
email. This is the recommended provider for Gmail mailboxes since Google
has deprecated IMAP basic auth for most accounts.

Advantages over IMAP:
    - OAuth2 (no app passwords needed)
    - Faster message retrieval (API vs IMAP protocol)
    - Can use push notifications via Google Pub/Sub (future)
    - History-based sync (only fetch what's new since last check)

Setup:
    1. Create a Google Cloud project
    2. Enable the Gmail API
    3. Create OAuth2 credentials (Desktop or Web app)
    4. Run the consent flow to get a refresh token
    5. Store credentials in the mailbox config JSONB

Called by:
    backend/services/email_ingestion.py via get_provider_from_config()

Cross-cutting constraints:
    FR-EI-1 — Persists sender, recipients, subject, body, timestamps, thread metadata
    FR-EI-2 — Supports Gmail as a live email provider
"""

import base64
import logging
from datetime import datetime, timezone
from email.mime.text import MIMEText
from typing import Optional

from backend.email.provider import InboundMessage, MailboxProvider

logger = logging.getLogger("golteris.email.gmail_provider")


class GmailMailboxProvider(MailboxProvider):
    """
    Fetches unread emails from Gmail via the Gmail API.

    Uses OAuth2 user credentials (refresh token). The token is refreshed
    automatically on each request via the google-auth library.

    Config dict (stored in mailboxes.config JSONB):
        client_id: OAuth2 client ID
        client_secret: OAuth2 client secret
        refresh_token: Long-lived refresh token from consent flow
        user_email: Gmail address (for sender identification on outbound)
    """

    def __init__(
        self,
        client_id: str = "",
        client_secret: str = "",
        refresh_token: str = "",
        user_email: str = "",
    ):
        self.client_id = client_id
        self.client_secret = client_secret
        self.refresh_token = refresh_token
        self.user_email = user_email

    def fetch_new_messages(self) -> list[InboundMessage]:
        """
        Fetch unread messages from Gmail inbox using the Gmail API.

        Queries for unread messages in INBOX, fetches full message data,
        parses into InboundMessage objects, and marks them as read.

        Returns:
            List of new InboundMessage objects, empty if none or on error.
        """
        if not self.refresh_token or not self.client_id:
            logger.warning("Gmail API not configured — skipping")
            return []

        try:
            service = self._get_service()
            if not service:
                return []

            # List unread messages in INBOX
            results = service.users().messages().list(
                userId="me",
                q="is:unread in:inbox",
                maxResults=25,
            ).execute()

            message_ids = results.get("messages", [])
            if not message_ids:
                return []

            logger.info("Gmail API found %d unread messages", len(message_ids))
            messages = []

            for msg_ref in message_ids:
                try:
                    # Fetch full message data
                    msg_data = service.users().messages().get(
                        userId="me",
                        id=msg_ref["id"],
                        format="full",
                    ).execute()

                    parsed = self._parse_message(msg_data)
                    if parsed:
                        messages.append(parsed)

                    # Mark as read by removing UNREAD label
                    service.users().messages().modify(
                        userId="me",
                        id=msg_ref["id"],
                        body={"removeLabelIds": ["UNREAD"]},
                    ).execute()

                except Exception as e:
                    logger.error("Failed to process Gmail message %s: %s", msg_ref["id"], e)

            if messages:
                logger.info("Ingested %d messages from Gmail", len(messages))
            return messages

        except Exception as e:
            logger.exception("Gmail API error: %s", e)
            return []

    def send_message(
        self,
        to: str,
        subject: str,
        body: str,
        reply_to_message_id: str | None = None,
    ) -> dict:
        """
        Send an email via Gmail API (#25).

        C2 CONSTRAINT: Only called by email_send service after approval check.

        Args:
            to: Recipient email address
            subject: Email subject
            body: Email body (plain text)
            reply_to_message_id: For threading, the original message's Message-ID

        Returns:
            Dict with success, message_id, and error fields.
        """
        try:
            service = self._get_service()
            if not service:
                return {"success": False, "message_id": None, "error": "Gmail API not configured"}

            # Build MIME message
            msg = MIMEText(body)
            msg["to"] = to
            msg["from"] = self.user_email
            msg["subject"] = subject
            if reply_to_message_id:
                msg["In-Reply-To"] = reply_to_message_id
                msg["References"] = reply_to_message_id

            # Encode as base64url per Gmail API spec
            raw = base64.urlsafe_b64encode(msg.as_bytes()).decode("utf-8")

            result = service.users().messages().send(
                userId="me",
                body={"raw": raw},
            ).execute()

            sent_id = result.get("id", "")
            logger.info("Email sent via Gmail to %s: %s (id=%s)", to, subject, sent_id)
            return {"success": True, "message_id": sent_id, "error": None}

        except Exception as e:
            logger.error("Gmail send failed: %s", e)
            return {"success": False, "message_id": None, "error": str(e)}

    def get_provider_name(self) -> str:
        return "gmail"

    def _get_service(self):
        """
        Build the Gmail API service using OAuth2 credentials.

        Creates a Credentials object from the refresh token and builds
        the Gmail API client. Tokens are refreshed automatically.

        Returns:
            Gmail API service object, or None on failure.
        """
        try:
            from google.oauth2.credentials import Credentials
            from googleapiclient.discovery import build

            creds = Credentials(
                token=None,
                refresh_token=self.refresh_token,
                client_id=self.client_id,
                client_secret=self.client_secret,
                token_uri="https://oauth2.googleapis.com/token",
            )

            return build("gmail", "v1", credentials=creds)

        except ImportError:
            logger.error("google-api-python-client not installed — run: pip install google-api-python-client google-auth")
            return None
        except Exception as e:
            logger.error("Gmail auth failed: %s", e)
            return None

    def _parse_message(self, msg_data: dict) -> Optional[InboundMessage]:
        """
        Parse a Gmail API message object into an InboundMessage.

        Extracts headers (From, To, Subject, Date, Message-ID, In-Reply-To)
        and the plain text body from the message payload.
        """
        try:
            headers = {
                h["name"].lower(): h["value"]
                for h in msg_data.get("payload", {}).get("headers", [])
            }

            sender = headers.get("from", "")
            recipients = headers.get("to", "")
            cc = headers.get("cc", "")
            if cc:
                recipients = f"{recipients}, {cc}" if recipients else cc
            subject = headers.get("subject", "")
            message_id = headers.get("message-id", "")
            in_reply_to = headers.get("in-reply-to", "")
            date_str = headers.get("date", "")
            thread_id = msg_data.get("threadId")

            # Parse date to ISO 8601
            received_at = None
            if date_str:
                try:
                    from email.utils import parsedate_to_datetime
                    parsed = parsedate_to_datetime(date_str)
                    received_at = parsed.isoformat()
                except Exception:
                    pass

            # Extract body — prefer plain text
            body = self._extract_body(msg_data.get("payload", {}))

            return InboundMessage(
                sender=sender,
                recipients=recipients,
                subject=subject,
                body=body,
                raw_content=str(msg_data),
                thread_id=thread_id,
                in_reply_to=in_reply_to if in_reply_to else None,
                message_id_header=message_id if message_id else None,
                received_at=received_at,
            )

        except Exception as e:
            logger.error("Failed to parse Gmail message: %s", e)
            return None

    def _extract_body(self, payload: dict) -> str:
        """
        Extract plain text body from Gmail API message payload.

        Walks the MIME parts looking for text/plain first, falls back
        to text/html (stripped of tags). Gmail's API returns base64url
        encoded body data.
        """
        mime_type = payload.get("mimeType", "")

        # Simple message (not multipart)
        if mime_type == "text/plain":
            data = payload.get("body", {}).get("data", "")
            if data:
                return base64.urlsafe_b64decode(data).decode("utf-8", errors="replace")

        # Multipart — walk parts looking for text/plain
        parts = payload.get("parts", [])
        plain_body = None
        html_body = None

        for part in parts:
            part_type = part.get("mimeType", "")
            data = part.get("body", {}).get("data", "")

            if part_type == "text/plain" and data and plain_body is None:
                plain_body = base64.urlsafe_b64decode(data).decode("utf-8", errors="replace")
            elif part_type == "text/html" and data and html_body is None:
                html_body = base64.urlsafe_b64decode(data).decode("utf-8", errors="replace")
            elif part.get("parts"):
                # Nested multipart — recurse
                nested = self._extract_body(part)
                if nested and plain_body is None:
                    plain_body = nested

        if plain_body:
            return plain_body

        if html_body:
            import re
            return re.sub(r"<[^>]+>", "", html_body).strip()

        return ""
