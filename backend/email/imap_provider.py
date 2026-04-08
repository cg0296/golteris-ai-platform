"""
backend/email/imap_provider.py — IMAP mailbox provider for real email ingestion.

Connects to any IMAP-capable mailbox (Gmail, Outlook, Yahoo, etc.) and
fetches unread messages. This is the universal fallback provider per
REQUIREMENTS.md §2.6 — any email service that supports IMAP works without
a custom integration.

Gmail setup:
    1. Enable IMAP in Gmail settings
    2. Create an app password (Security > 2-Step Verification > App passwords)
    3. Set env vars: IMAP_HOST=imap.gmail.com, IMAP_USER=you@gmail.com,
       IMAP_PASSWORD=your-app-password

Outlook setup:
    1. IMAP is enabled by default for most accounts
    2. Set env vars: IMAP_HOST=outlook.office365.com, IMAP_USER, IMAP_PASSWORD

The provider marks fetched messages as SEEN on the IMAP server so they
aren't re-fetched on the next poll cycle.

Cross-cutting constraints:
    FR-EI-1 — Persists sender, recipients, subject, body, timestamps, thread metadata
"""

import email
import email.header
import email.utils
import imaplib
import logging
import os
from datetime import datetime
from typing import Optional

from backend.email.provider import InboundMessage, MailboxProvider

logger = logging.getLogger("golteris.email.imap_provider")


class IMAPMailboxProvider(MailboxProvider):
    """
    Fetches unread emails from an IMAP mailbox.

    Connects on each fetch_new_messages() call and disconnects after.
    This is intentional — the worker polls on a cron interval (every ~60s),
    and keeping a persistent IMAP connection open across polls adds complexity
    (keepalives, reconnection logic) without benefit for the polling model.
    """

    def __init__(
        self,
        host: Optional[str] = None,
        port: int = 993,
        username: Optional[str] = None,
        password: Optional[str] = None,
        folder: str = "INBOX",
        use_ssl: bool = True,
    ):
        """
        Args:
            host: IMAP server hostname (default: IMAP_HOST env var)
            port: IMAP port (default: 993 for SSL)
            username: Login username (default: IMAP_USER env var)
            password: Login password (default: IMAP_PASSWORD env var)
            folder: IMAP folder to poll (default: INBOX)
            use_ssl: Whether to use SSL (default: True)
        """
        self.host = host or os.environ.get("IMAP_HOST", "")
        self.port = port
        self.usernamename = username or os.environ.get("IMAP_USER", "")
        self.password = password or os.environ.get("IMAP_PASSWORD", "")
        self.folder = folder
        self.use_ssl = use_ssl

    def fetch_new_messages(self) -> list[InboundMessage]:
        """
        Connect to IMAP, fetch all UNSEEN messages, parse and return them.

        Marks each fetched message as SEEN on the server so it won't be
        returned again on the next poll.

        Returns:
            List of new InboundMessage objects, empty if none or on error.
        """
        if not self.host or not self.usernamename:
            logger.warning("IMAP not configured — skipping (set IMAP_HOST and IMAP_USER)")
            return []

        messages = []
        conn = None

        try:
            # Connect to the IMAP server
            if self.use_ssl:
                conn = imaplib.IMAP4_SSL(self.host, self.port)
            else:
                conn = imaplib.IMAP4(self.host, self.port)

            conn.login(self.usernamename, self.password)
            conn.select(self.folder)

            # Search for unread messages
            status, data = conn.search(None, "UNSEEN")
            if status != "OK" or not data[0]:
                return []

            message_ids = data[0].split()
            logger.info("Found %d unread messages in %s", len(message_ids), self.folder)

            for msg_id in message_ids:
                try:
                    msg = self._fetch_and_parse(conn, msg_id)
                    if msg:
                        messages.append(msg)
                except Exception as e:
                    logger.error("Failed to parse IMAP message %s: %s", msg_id, e)

        except imaplib.IMAP4.error as e:
            logger.error("IMAP error: %s", e)
        except ConnectionError as e:
            logger.error("IMAP connection failed: %s", e)
        except Exception as e:
            logger.exception("Unexpected IMAP error: %s", e)
        finally:
            if conn:
                try:
                    conn.close()
                    conn.logout()
                except Exception:
                    pass

        return messages

    def send_message(
        self,
        to: str,
        subject: str,
        body: str,
        reply_to_message_id: str | None = None,
    ) -> dict:
        """
        Send an email via SMTP using the same credentials as IMAP (#25).

        Derives the SMTP host from the IMAP host (most providers use the same
        hostname with different ports). Uses STARTTLS on port 587.

        C2 CONSTRAINT: Only called by email_send service after approval check.
        """
        import smtplib
        from email.mime.text import MIMEText

        # Derive SMTP host from IMAP host (imap.gmail.com → smtp.gmail.com, etc.)
        smtp_host = self.host.replace("imap.", "smtp.")

        try:
            msg = MIMEText(body)
            msg["Subject"] = subject
            msg["From"] = self.username
            msg["To"] = to
            if reply_to_message_id:
                msg["In-Reply-To"] = reply_to_message_id

            with smtplib.SMTP(smtp_host, 587, timeout=30) as server:
                server.starttls()
                server.login(self.username, self.password)
                server.sendmail(self.username, [to], msg.as_string())

            logger.info("Email sent via SMTP to %s: %s", to, subject)
            return {"success": True, "message_id": msg["Message-ID"], "error": None}

        except smtplib.SMTPException as e:
            logger.error("SMTP send failed: %s", e)
            return {"success": False, "message_id": None, "error": str(e)}

    def get_provider_name(self) -> str:
        return "imap"

    def _fetch_and_parse(self, conn: imaplib.IMAP4, msg_id: bytes) -> Optional[InboundMessage]:
        """
        Fetch a single message by ID and parse it into an InboundMessage.

        Extracts:
        - sender (From header)
        - recipients (To + Cc headers)
        - subject (decoded from MIME encoding)
        - body (plain text preferred, falls back to HTML stripped)
        - thread metadata (Message-ID, In-Reply-To, References)
        - received_at (Date header, parsed to ISO 8601)
        """
        status, data = conn.fetch(msg_id, "(RFC822)")
        if status != "OK" or not data[0]:
            return None

        raw_bytes = data[0][1]
        raw_str = raw_bytes.decode("utf-8", errors="replace")
        msg = email.message_from_bytes(raw_bytes)

        # Extract headers
        sender = self._decode_header(msg.get("From", ""))
        recipients = self._decode_header(msg.get("To", ""))
        cc = self._decode_header(msg.get("Cc", ""))
        if cc:
            recipients = f"{recipients}, {cc}" if recipients else cc

        subject = self._decode_header(msg.get("Subject", ""))
        message_id = msg.get("Message-ID", "")
        in_reply_to = msg.get("In-Reply-To", "")
        references = msg.get("References", "")

        # Parse date
        date_str = msg.get("Date", "")
        received_at = None
        if date_str:
            parsed = email.utils.parsedate_to_datetime(date_str)
            if parsed:
                received_at = parsed.isoformat()

        # Extract body — prefer plain text, fall back to HTML
        body = self._extract_body(msg)

        # Build thread_id from References header (first message in thread)
        # or from In-Reply-To if no References
        thread_id = None
        if references:
            # First Message-ID in References is the thread root
            thread_id = references.strip().split()[0]
        elif in_reply_to:
            thread_id = in_reply_to.strip()

        return InboundMessage(
            sender=sender,
            recipients=recipients,
            subject=subject,
            body=body,
            raw_content=raw_str,
            thread_id=thread_id,
            in_reply_to=in_reply_to.strip() if in_reply_to else None,
            message_id_header=message_id.strip() if message_id else None,
            received_at=received_at,
        )

    def _extract_body(self, msg: email.message.Message) -> str:
        """
        Extract the message body, preferring plain text over HTML.

        For multipart messages, walks the MIME tree looking for text/plain
        first. If none found, falls back to text/html (stripped of tags
        for basic readability).
        """
        if not msg.is_multipart():
            payload = msg.get_payload(decode=True)
            charset = msg.get_content_charset() or "utf-8"
            return payload.decode(charset, errors="replace") if payload else ""

        plain_body = None
        html_body = None

        for part in msg.walk():
            content_type = part.get_content_type()
            if content_type == "text/plain" and plain_body is None:
                payload = part.get_payload(decode=True)
                charset = part.get_content_charset() or "utf-8"
                plain_body = payload.decode(charset, errors="replace") if payload else ""
            elif content_type == "text/html" and html_body is None:
                payload = part.get_payload(decode=True)
                charset = part.get_content_charset() or "utf-8"
                html_body = payload.decode(charset, errors="replace") if payload else ""

        if plain_body:
            return plain_body

        if html_body:
            # Basic HTML tag stripping — good enough for extraction.
            # A real HTML-to-text converter would be better but adds a dependency.
            import re
            return re.sub(r"<[^>]+>", "", html_body)

        return ""

    def _decode_header(self, header_value: str) -> str:
        """
        Decode a MIME-encoded header value (handles =?UTF-8?Q?...?= etc.).
        """
        if not header_value:
            return ""

        decoded_parts = email.header.decode_header(header_value)
        result = []
        for part, charset in decoded_parts:
            if isinstance(part, bytes):
                result.append(part.decode(charset or "utf-8", errors="replace"))
            else:
                result.append(part)
        return " ".join(result)
