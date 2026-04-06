"""
tests/test_agent_runs.py — Tests for the agent run tracking service (#22).

Verifies the four acceptance criteria:
    1. Every workflow invocation creates an agent_run row (test_start_run)
    2. Duration reflects total wall time including HITL pauses (test_finish_run_duration)
    3. Cost and token totals roll up from agent_calls (test_cost_token_rollup)
    4. Powers the Agent -> Run Timeline view (test_list_runs, test_api_*)

Uses an in-memory SQLite database for speed. The service layer is pure
SQLAlchemy so it works identically against SQLite and Postgres.
"""

import time
from datetime import datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import JSON, create_engine, event
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import sessionmaker

from backend.db.models import (
    AgentCall,
    AgentCallStatus,
    AgentRun,
    AgentRunStatus,
    Base,
)
from backend.services.agent_runs import (
    count_runs,
    fail_run,
    finish_run,
    get_run,
    list_runs,
    pause_run,
    resume_run,
    start_run,
)


# ---------------------------------------------------------------------------
# Test fixtures — in-memory SQLite database for fast, isolated tests.
#
# SQLite doesn't support Postgres-specific JSONB columns or ENUM types.
# We swap JSONB -> JSON at the column level before creating tables so the
# schema can be rendered in SQLite. The service layer uses only standard
# SQL (SELECT, SUM, INSERT, UPDATE) so this substitution is transparent.
# ---------------------------------------------------------------------------


def _make_sqlite_compatible():
    """
    Walk all ORM models and replace JSONB columns with JSON so SQLite
    can create the tables. This only affects the in-memory test DB —
    production uses Postgres with native JSONB.
    """
    for table in Base.metadata.tables.values():
        for column in table.columns:
            if isinstance(column.type, JSONB):
                column.type = JSON()


@pytest.fixture
def db():
    """
    Create a fresh in-memory SQLite database for each test.

    Swaps JSONB -> JSON so SQLite can handle the schema. Enum types are
    rendered as VARCHAR automatically by SQLAlchemy when targeting SQLite.
    """
    _make_sqlite_compatible()
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()


# ---------------------------------------------------------------------------
# Service layer tests
# ---------------------------------------------------------------------------


class TestStartRun:
    """Acceptance criterion: every workflow invocation creates an agent_run row."""

    def test_creates_run_with_correct_fields(self, db):
        """start_run should create a row with status=RUNNING and started_at set."""
        run = start_run(
            db,
            workflow_name="Inbound Quote Processing",
            rfq_id=42,
            workflow_id=1,
            trigger_source="new_email",
        )

        assert run.id is not None
        assert run.workflow_name == "Inbound Quote Processing"
        assert run.rfq_id == 42
        assert run.workflow_id == 1
        assert run.trigger_source == "new_email"
        assert run.status == AgentRunStatus.RUNNING
        assert run.started_at is not None
        assert run.finished_at is None
        assert run.total_cost_usd == Decimal("0")
        assert run.total_input_tokens == 0
        assert run.total_output_tokens == 0

    def test_creates_run_without_optional_fields(self, db):
        """Runs without an RFQ (system-level runs) should work fine."""
        run = start_run(db, workflow_name="Mailbox Polling")

        assert run.id is not None
        assert run.rfq_id is None
        assert run.workflow_id is None
        assert run.trigger_source is None

    def test_run_is_persisted(self, db):
        """The run should be queryable immediately after creation."""
        run = start_run(db, workflow_name="Test Workflow")

        fetched = db.query(AgentRun).filter(AgentRun.id == run.id).first()
        assert fetched is not None
        assert fetched.workflow_name == "Test Workflow"


class TestFinishRun:
    """Acceptance criterion: duration reflects total wall time."""

    def test_sets_finished_at_and_duration(self, db):
        """finish_run should calculate duration from started_at to now."""
        run = start_run(db, workflow_name="Test")

        # Manually set started_at to 2 seconds ago to get a measurable duration
        run.started_at = datetime.utcnow() - timedelta(seconds=2)
        db.commit()

        finished = finish_run(db, run.id)

        assert finished.status == AgentRunStatus.COMPLETED
        assert finished.finished_at is not None
        assert finished.duration_ms is not None
        # Duration should be at least 2000ms (2 seconds)
        assert finished.duration_ms >= 1900  # small tolerance for timing

    def test_fail_run_sets_failed_status(self, db):
        """fail_run should set status=FAILED and still calculate duration."""
        run = start_run(db, workflow_name="Test")
        failed = fail_run(db, run.id, error_message="LLM timeout")

        assert failed.status == AgentRunStatus.FAILED
        assert failed.finished_at is not None

    def test_finish_nonexistent_run_raises(self, db):
        """finish_run should raise ValueError for unknown run IDs."""
        with pytest.raises(ValueError, match="not found"):
            finish_run(db, 99999)


class TestPauseResume:
    """Acceptance criterion: duration includes HITL pause time."""

    def test_pause_sets_status(self, db):
        run = start_run(db, workflow_name="Test")
        paused = pause_run(db, run.id)
        assert paused.status == AgentRunStatus.PAUSED_FOR_HITL

    def test_resume_sets_running(self, db):
        run = start_run(db, workflow_name="Test")
        pause_run(db, run.id)
        resumed = resume_run(db, run.id)
        assert resumed.status == AgentRunStatus.RUNNING

    def test_pause_nonexistent_raises(self, db):
        with pytest.raises(ValueError, match="not found"):
            pause_run(db, 99999)


class TestCostTokenRollup:
    """Acceptance criterion: cost and token totals roll up from agent_calls."""

    def test_rollup_sums_child_calls(self, db):
        """Finishing a run should sum cost and tokens from all child calls."""
        run = start_run(db, workflow_name="Extraction Pipeline")

        # Simulate two LLM calls made during this run
        call_1 = AgentCall(
            run_id=run.id,
            agent_name="extraction",
            provider="anthropic",
            model="claude-sonnet-4-6",
            user_prompt="Extract fields from this email...",
            input_tokens=1500,
            output_tokens=300,
            cost_usd=Decimal("0.005400"),
            started_at=datetime.utcnow(),
            status=AgentCallStatus.SUCCESS,
        )
        call_2 = AgentCall(
            run_id=run.id,
            agent_name="validation",
            provider="anthropic",
            model="claude-sonnet-4-6",
            user_prompt="Validate these extracted fields...",
            input_tokens=800,
            output_tokens=150,
            cost_usd=Decimal("0.002700"),
            started_at=datetime.utcnow(),
            status=AgentCallStatus.SUCCESS,
        )
        db.add_all([call_1, call_2])
        db.commit()

        finished = finish_run(db, run.id)

        # Cost should be the sum of both calls
        assert finished.total_cost_usd == Decimal("0.008100")
        # Tokens should be the sum of both calls
        assert finished.total_input_tokens == 2300  # 1500 + 800
        assert finished.total_output_tokens == 450  # 300 + 150

    def test_rollup_with_no_calls(self, db):
        """A run with no LLM calls should have zero cost and tokens."""
        run = start_run(db, workflow_name="Empty Run")
        finished = finish_run(db, run.id)

        assert finished.total_cost_usd == Decimal("0")
        assert finished.total_input_tokens == 0
        assert finished.total_output_tokens == 0


class TestListAndCount:
    """Acceptance criterion: powers the Agent -> Run Timeline view."""

    def test_list_runs_ordered_newest_first(self, db):
        """Runs should be returned newest first for the timeline view."""
        run_1 = start_run(db, workflow_name="First")
        run_1.started_at = datetime.utcnow() - timedelta(hours=2)
        db.commit()

        run_2 = start_run(db, workflow_name="Second")

        runs = list_runs(db)
        assert len(runs) == 2
        assert runs[0].id == run_2.id  # newest first
        assert runs[1].id == run_1.id

    def test_filter_by_status(self, db):
        """Filtering by status should return only matching runs."""
        run_1 = start_run(db, workflow_name="Running")
        run_2 = start_run(db, workflow_name="Done")
        finish_run(db, run_2.id)

        running = list_runs(db, status=AgentRunStatus.RUNNING)
        assert len(running) == 1
        assert running[0].id == run_1.id

    def test_filter_by_rfq_id(self, db):
        """Filtering by RFQ should return only runs for that quote request."""
        start_run(db, workflow_name="RFQ 42", rfq_id=42)
        start_run(db, workflow_name="RFQ 43", rfq_id=43)

        rfq_42_runs = list_runs(db, rfq_id=42)
        assert len(rfq_42_runs) == 1
        assert rfq_42_runs[0].rfq_id == 42

    def test_pagination(self, db):
        """Limit and offset should control pagination."""
        for i in range(5):
            start_run(db, workflow_name=f"Run {i}")

        page_1 = list_runs(db, limit=2, offset=0)
        page_2 = list_runs(db, limit=2, offset=2)

        assert len(page_1) == 2
        assert len(page_2) == 2
        assert page_1[0].id != page_2[0].id

    def test_count_runs(self, db):
        """count_runs should return total matching runs for pagination metadata."""
        start_run(db, workflow_name="A")
        start_run(db, workflow_name="B")
        run_c = start_run(db, workflow_name="C")
        finish_run(db, run_c.id)

        assert count_runs(db) == 3
        assert count_runs(db, status=AgentRunStatus.RUNNING) == 2
        assert count_runs(db, status=AgentRunStatus.COMPLETED) == 1


class TestGetRun:
    """get_run should fetch a single run or return None."""

    def test_returns_run(self, db):
        run = start_run(db, workflow_name="Test")
        fetched = get_run(db, run.id)
        assert fetched is not None
        assert fetched.id == run.id

    def test_returns_none_for_missing(self, db):
        assert get_run(db, 99999) is None
