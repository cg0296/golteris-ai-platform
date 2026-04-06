"""
backend/email/file_provider.py — File-based mailbox provider for dev and demo.

Reads JSON email files from a seed directory (e.g., seed/beltmann/shipper_emails/).
Tracks which files have been processed via a .processed JSON file in the same
directory so files aren't re-ingested on restart.

This is the demo fallback — if IMAP isn't configured or the network is flaky,
the demo runs on pre-loaded seed data.

Usage:
    provider = FileMailboxProvider("seed/beltmann/shipper_emails")
    messages = provider.fetch_new_messages()
"""

import json
import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Optional

from backend.email.provider import InboundMessage, MailboxProvider

logger = logging.getLogger("golteris.email.file_provider")


class FileMailboxProvider(MailboxProvider):
    """
    Reads JSON email files from a directory.

    Each JSON file must have: sender, recipients, subject, body, message_id_header.
    Optional: thread_id, in_reply_to, received_at.

    Processed files are tracked in a .processed.json file in the seed directory.
    This persists across restarts so the same seed emails aren't re-ingested.
    """

    def __init__(self, seed_dir: str):
        """
        Args:
            seed_dir: Path to the directory containing JSON email files.
        """
        self.seed_dir = Path(seed_dir)
        self.processed_file = self.seed_dir / ".processed.json"
        self._processed: set[str] = self._load_processed()

    def fetch_new_messages(self) -> list[InboundMessage]:
        """
        Scan the seed directory for unprocessed JSON files.

        Returns one InboundMessage per new file. Files that have already
        been returned (tracked in .processed.json) are skipped.
        """
        if not self.seed_dir.is_dir():
            logger.warning("Seed directory does not exist: %s", self.seed_dir)
            return []

        messages = []
        for file_path in sorted(self.seed_dir.glob("*.json")):
            # Skip the tracking file itself
            if file_path.name == ".processed.json":
                continue

            if file_path.name in self._processed:
                continue

            try:
                data = json.loads(file_path.read_text(encoding="utf-8"))
                msg = InboundMessage(
                    sender=data["sender"],
                    recipients=data.get("recipients"),
                    subject=data.get("subject"),
                    body=data.get("body", ""),
                    raw_content=json.dumps(data),
                    thread_id=data.get("thread_id"),
                    in_reply_to=data.get("in_reply_to"),
                    message_id_header=data.get("message_id_header"),
                    received_at=datetime.utcnow().isoformat(),
                )
                messages.append(msg)

                # Mark as processed
                self._processed.add(file_path.name)
                logger.info("Ingested seed email: %s (%s)", file_path.name, data.get("subject", ""))

            except (json.JSONDecodeError, KeyError) as e:
                logger.error("Failed to parse seed email %s: %s", file_path.name, e)

        # Persist processed set so it survives restarts
        self._save_processed()

        return messages

    def get_provider_name(self) -> str:
        return "file"

    def reset(self) -> None:
        """
        Clear the processed tracking file — re-ingests all seed emails.

        Useful for demo resets and testing.
        """
        self._processed.clear()
        if self.processed_file.exists():
            self.processed_file.unlink()
        logger.info("File provider reset — all seed emails will be re-ingested")

    def _load_processed(self) -> set[str]:
        """Load the set of already-processed filenames."""
        if self.processed_file.exists():
            try:
                data = json.loads(self.processed_file.read_text(encoding="utf-8"))
                return set(data.get("processed", []))
            except (json.JSONDecodeError, KeyError):
                return set()
        return set()

    def _save_processed(self) -> None:
        """Persist the processed set to disk."""
        self.processed_file.write_text(
            json.dumps({"processed": sorted(self._processed)}, indent=2),
            encoding="utf-8",
        )
