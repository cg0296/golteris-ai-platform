"""
tests/test_email_ingestion.py — Tests for email ingestion (#12).

Verifies the four acceptance criteria:
    1. A new inbound email creates a persisted message record
    2. Thread metadata is stored when available
    3. Failures are logged clearly enough for operator debugging
    4. Implementation is limited to one mailbox for the MVP

Also tests the file provider and deduplication.
"""

import json
import os
import tempfile
from pathlib import Path

import pytest
from sqlalchemy import JSON, create_engine
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import sessionmaker
from unittest.mock import patch

from backend.db.models import AuditEvent, Base, Message, MessageDirection
from backend.email.file_provider import FileMailboxProvider
from backend.email.provider import InboundMessage
from backend.services.email_ingestion import _persist_message, ingest_new_messages


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_sqlite_compatible():
    for table in Base.metadata.tables.values():
        for column in table.columns:
            if isinstance(column.type, JSONB):
                column.type = JSON()


@pytest.fixture
def db():
    _make_sqlite_compatible()
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()


@pytest.fixture
def seed_dir():
    """Create a temporary directory with sample email JSON files."""
    with tempfile.TemporaryDirectory() as tmpdir:
        # Write two sample emails
        email_1 = {
            "sender": "tom@acme.com",
            "recipients": "quotes@beltmann.com",
            "subject": "Quote Request - Flatbed",
            "body": "Need a rate on a flatbed from Dallas to Atlanta.",
            "message_id_header": "<test-001@acme.com>",
            "thread_id": None,
            "in_reply_to": None,
        }
        email_2 = {
            "sender": "sarah@global.com",
            "recipients": "quotes@beltmann.com",
            "subject": "Re: Project Quote",
            "body": "Here's the updated info you requested.",
            "message_id_header": "<test-002@global.com>",
            "thread_id": "thread-001",
            "in_reply_to": "<orig-001@beltmann.com>",
        }

        Path(tmpdir, "email_01.json").write_text(json.dumps(email_1))
        Path(tmpdir, "email_02.json").write_text(json.dumps(email_2))

        yield tmpdir


# ---------------------------------------------------------------------------
# FileMailboxProvider tests
# ---------------------------------------------------------------------------


class TestFileMailboxProvider:
    def test_fetches_all_new_files(self, seed_dir):
        provider = FileMailboxProvider(seed_dir)
        messages = provider.fetch_new_messages()

        assert len(messages) == 2
        assert messages[0].sender == "tom@acme.com"
        assert messages[1].sender == "sarah@global.com"

    def test_tracks_processed_files(self, seed_dir):
        provider = FileMailboxProvider(seed_dir)

        # First fetch — gets both
        messages_1 = provider.fetch_new_messages()
        assert len(messages_1) == 2

        # Second fetch — gets none (already processed)
        messages_2 = provider.fetch_new_messages()
        assert len(messages_2) == 0

    def test_survives_restart(self, seed_dir):
        """Processed tracking persists across provider instances."""
        provider_1 = FileMailboxProvider(seed_dir)
        provider_1.fetch_new_messages()

        # New instance reads the .processed.json file
        provider_2 = FileMailboxProvider(seed_dir)
        messages = provider_2.fetch_new_messages()
        assert len(messages) == 0

    def test_reset_allows_reingestion(self, seed_dir):
        provider = FileMailboxProvider(seed_dir)
        provider.fetch_new_messages()

        provider.reset()
        messages = provider.fetch_new_messages()
        assert len(messages) == 2

    def test_preserves_thread_metadata(self, seed_dir):
        provider = FileMailboxProvider(seed_dir)
        messages = provider.fetch_new_messages()

        # email_02 has thread metadata
        reply = [m for m in messages if m.sender == "sarah@global.com"][0]
        assert reply.thread_id == "thread-001"
        assert reply.in_reply_to == "<orig-001@beltmann.com>"
        assert reply.message_id_header == "<test-002@global.com>"

    def test_nonexistent_dir_returns_empty(self):
        provider = FileMailboxProvider("/nonexistent/path")
        messages = provider.fetch_new_messages()
        assert messages == []

    def test_skips_invalid_json(self, seed_dir):
        """Invalid JSON files are skipped, not crash the provider."""
        Path(seed_dir, "bad_file.json").write_text("not valid json {{{")

        provider = FileMailboxProvider(seed_dir)
        messages = provider.fetch_new_messages()
        # Should get 2 valid files, skip the bad one
        assert len(messages) == 2


# ---------------------------------------------------------------------------
# Ingestion service tests
# ---------------------------------------------------------------------------


class TestIngestNewMessages:
    @patch("backend.services.email_ingestion.enqueue_job")
    def test_persists_message_and_enqueues_job(self, mock_enqueue, db, seed_dir):
        """New message should be persisted and a matching job enqueued."""
        provider = FileMailboxProvider(seed_dir)
        messages = ingest_new_messages(db, provider)

        assert len(messages) == 2
        # Check persistence
        all_msgs = db.query(Message).all()
        assert len(all_msgs) == 2
        assert all_msgs[0].direction == MessageDirection.INBOUND

        # Check job enqueue — one matching job per message
        assert mock_enqueue.call_count == 2
        mock_enqueue.assert_any_call(db, "matching", {"message_id": messages[0].id})

    @patch("backend.services.email_ingestion.enqueue_job")
    def test_deduplicates_by_message_id(self, mock_enqueue, db, seed_dir):
        """Same message_id_header should not create duplicate records."""
        provider = FileMailboxProvider(seed_dir)
        ingest_new_messages(db, provider)

        # Reset the provider to re-fetch
        provider.reset()
        messages_2 = ingest_new_messages(db, provider)

        # Should be 0 — both were already persisted
        assert len(messages_2) == 0
        all_msgs = db.query(Message).all()
        assert len(all_msgs) == 2  # Still just 2, no duplicates

    @patch("backend.services.email_ingestion.enqueue_job")
    def test_creates_audit_events(self, mock_enqueue, db, seed_dir):
        """Each ingested message should create an audit event."""
        provider = FileMailboxProvider(seed_dir)
        ingest_new_messages(db, provider)

        events = db.query(AuditEvent).filter(
            AuditEvent.event_type == "email_received"
        ).all()
        assert len(events) == 2
        assert "New email received" in events[0].description

    @patch("backend.services.email_ingestion.enqueue_job")
    def test_stores_thread_metadata(self, mock_enqueue, db, seed_dir):
        """Thread metadata should be persisted in the message record."""
        provider = FileMailboxProvider(seed_dir)
        messages = ingest_new_messages(db, provider)

        reply = [m for m in messages if m.sender == "sarah@global.com"][0]
        assert reply.thread_id == "thread-001"
        assert reply.in_reply_to == "<orig-001@beltmann.com>"
        assert reply.message_id_header == "<test-002@global.com>"


# ---------------------------------------------------------------------------
# Persist message tests
# ---------------------------------------------------------------------------


class TestPersistMessage:
    def test_creates_message_record(self, db):
        msg = InboundMessage(
            sender="test@example.com",
            subject="Test",
            body="Hello",
            message_id_header="<unique@example.com>",
        )
        result = _persist_message(db, msg)
        assert result is not None
        assert result.id is not None
        assert result.sender == "test@example.com"
        assert result.direction == MessageDirection.INBOUND

    def test_returns_none_for_duplicate(self, db):
        msg = InboundMessage(
            sender="test@example.com",
            body="Hello",
            message_id_header="<dup@example.com>",
        )
        _persist_message(db, msg)
        result = _persist_message(db, msg)
        assert result is None  # Duplicate skipped
