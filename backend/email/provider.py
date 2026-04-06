"""
backend/email/provider.py — Abstract mailbox provider interface.

Every email provider (file-based, IMAP, Gmail API, etc.) implements this
interface. The ingestion service calls these methods without knowing which
provider is in use. See REQUIREMENTS.md §2.6.

The normalized message dict returned by fetch_new_messages() matches the
`messages` table schema so the ingestion service can persist it directly.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Optional


@dataclass
class InboundMessage:
    """
    A normalized inbound email message from any provider.

    Fields map directly to the `messages` table columns. The ingestion
    service persists these without transformation.
    """
    sender: str
    recipients: Optional[str] = None
    subject: Optional[str] = None
    body: str = ""
    raw_content: Optional[str] = None
    thread_id: Optional[str] = None
    in_reply_to: Optional[str] = None
    message_id_header: Optional[str] = None
    received_at: Optional[str] = None  # ISO 8601 string, parsed by ingestion service


class MailboxProvider(ABC):
    """
    Abstract base class for email mailbox providers.

    Each provider implements fetch_new_messages() to retrieve unprocessed
    inbound emails from its source (file system, IMAP server, API, etc.).
    """

    @abstractmethod
    def fetch_new_messages(self) -> list[InboundMessage]:
        """
        Fetch new (unprocessed) messages from the mailbox.

        Returns a list of normalized InboundMessage objects. Each call should
        only return messages that haven't been returned before — the provider
        is responsible for tracking what's been processed.

        Returns:
            List of new messages, empty if none.
        """
        ...

    @abstractmethod
    def get_provider_name(self) -> str:
        """Return a human-readable provider name (e.g., 'file', 'imap', 'gmail')."""
        ...
