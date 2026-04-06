"""
tests/test_quote_sheet.py — Tests for quote sheet generation (#16).

Verifies the three acceptance criteria:
    1. A sample inbound email can produce a usable structured sheet
    2. The generated output contains the fields the broker needs
    3. The output is stable enough for demo use
"""

from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import JSON, create_engine
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import sessionmaker

from backend.agents.quote_sheet import QUOTE_SHEET_TOOL, generate_quote_sheet
from backend.db.models import AuditEvent, Base, RFQ, RFQState
from backend.llm.provider import LLMResponse


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


def _create_rfq(db, state=RFQState.READY_TO_QUOTE, **kwargs) -> RFQ:
    defaults = {
        "customer_name": "Tom Reynolds",
        "customer_company": "Acme Logistics",
        "customer_email": "tom@acme.com",
        "origin": "Dallas, TX",
        "destination": "Atlanta, GA",
        "equipment_type": "Flatbed",
        "truck_count": 1,
        "commodity": "Steel coils",
        "weight_lbs": 42000,
        "pickup_date": datetime(2026, 4, 15),
        "delivery_date": datetime(2026, 4, 17),
        "special_requirements": "Tarping required",
        "state": state,
    }
    defaults.update(kwargs)
    rfq = RFQ(**defaults)
    db.add(rfq)
    db.commit()
    db.refresh(rfq)
    return rfq


def _mock_sheet_response(rfq_id: int) -> LLMResponse:
    """Build a mock LLM response with a realistic quote sheet."""
    return LLMResponse(
        content=None,
        tool_calls=[{
            "name": "generate_quote_sheet",
            "input": {
                "reference_id": f"BLT-2026-{rfq_id:04d}",
                "summary": "1 flatbed, Dallas TX to Atlanta GA, steel coils",
                "lanes": [{
                    "origin": "Dallas, TX",
                    "destination": "Atlanta, GA",
                    "equipment": "Flatbed (48ft)",
                    "truck_count": 1,
                    "commodity": "Steel coils",
                    "weight_lbs": 42000,
                    "pickup_date": "2026-04-15",
                    "delivery_date": "2026-04-17",
                }],
                "special_requirements": "Tarping required",
                "notes": None,
                "response_deadline": "2026-04-12",
            },
        }],
        input_tokens=800,
        output_tokens=250,
        model="claude-sonnet-4-6",
    )


# ---------------------------------------------------------------------------
# Tool schema tests
# ---------------------------------------------------------------------------


class TestToolSchema:
    def test_schema_requires_core_fields(self):
        required = QUOTE_SHEET_TOOL.input_schema["required"]
        assert "reference_id" in required
        assert "summary" in required
        assert "lanes" in required

    def test_lane_schema_requires_core_fields(self):
        lane_required = QUOTE_SHEET_TOOL.input_schema["properties"]["lanes"]["items"]["required"]
        assert "origin" in lane_required
        assert "destination" in lane_required
        assert "equipment" in lane_required
        assert "truck_count" in lane_required
        assert "commodity" in lane_required


# ---------------------------------------------------------------------------
# Quote sheet generation tests
# ---------------------------------------------------------------------------


class TestGenerateQuoteSheet:

    @patch("backend.agents.quote_sheet.call_llm")
    @patch("backend.agents.quote_sheet.start_run")
    @patch("backend.agents.quote_sheet.finish_run")
    def test_happy_path_generates_sheet(self, mock_finish, mock_start, mock_llm, db):
        """Complete RFQ in ready_to_quote -> structured quote sheet."""
        rfq = _create_rfq(db)

        mock_run = MagicMock()
        mock_run.id = 1
        mock_start.return_value = mock_run
        mock_llm.return_value = _mock_sheet_response(rfq.id)

        sheet = generate_quote_sheet(db, rfq.id)

        assert sheet is not None
        assert sheet["reference_id"] == f"BLT-2026-{rfq.id:04d}"
        assert "flatbed" in sheet["summary"].lower()
        assert "Dallas" in sheet["summary"]
        assert len(sheet["lanes"]) == 1
        assert sheet["lanes"][0]["origin"] == "Dallas, TX"
        assert sheet["lanes"][0]["destination"] == "Atlanta, GA"
        assert sheet["lanes"][0]["truck_count"] == 1
        assert sheet["lanes"][0]["commodity"] == "Steel coils"
        assert sheet["special_requirements"] == "Tarping required"

    @patch("backend.agents.quote_sheet.call_llm")
    @patch("backend.agents.quote_sheet.start_run")
    @patch("backend.agents.quote_sheet.finish_run")
    def test_multi_truck_generates_sheet(self, mock_finish, mock_start, mock_llm, db):
        """Multi-truck RFQ should produce a sheet with correct truck count."""
        rfq = _create_rfq(
            db,
            origin="Houston, TX",
            destination="Memphis, TN",
            equipment_type="Flatbed",
            truck_count=3,
            commodity="Construction equipment",
            weight_lbs=44000,
            special_requirements="Tarping required, Oversize permits needed",
        )

        mock_run = MagicMock()
        mock_run.id = 2
        mock_start.return_value = mock_run
        mock_llm.return_value = LLMResponse(
            content=None,
            tool_calls=[{
                "name": "generate_quote_sheet",
                "input": {
                    "reference_id": f"BLT-2026-{rfq.id:04d}",
                    "summary": "3 flatbeds, Houston TX to Memphis TN, construction equipment",
                    "lanes": [{
                        "origin": "Houston, TX",
                        "destination": "Memphis, TN",
                        "equipment": "Flatbed",
                        "truck_count": 3,
                        "commodity": "Construction equipment",
                        "weight_lbs": 44000,
                        "pickup_date": "2026-04-20",
                        "delivery_date": "2026-04-25",
                    }],
                    "special_requirements": "Tarping required. Oversize permits needed.",
                    "notes": "All 3 trucks same pickup window",
                    "response_deadline": None,
                },
            }],
            input_tokens=900,
            output_tokens=280,
            model="claude-sonnet-4-6",
        )

        sheet = generate_quote_sheet(db, rfq.id)

        assert sheet is not None
        assert sheet["lanes"][0]["truck_count"] == 3
        assert "Oversize" in sheet["special_requirements"]

    def test_refuses_needs_clarification_state(self, db):
        """RFQ in needs_clarification should NOT generate a sheet."""
        rfq = _create_rfq(db, state=RFQState.NEEDS_CLARIFICATION)
        result = generate_quote_sheet(db, rfq.id)
        assert result is None

    def test_refuses_nonexistent_rfq(self, db):
        result = generate_quote_sheet(db, 99999)
        assert result is None

    @patch("backend.agents.quote_sheet.call_llm")
    @patch("backend.agents.quote_sheet.start_run")
    @patch("backend.agents.quote_sheet.finish_run")
    def test_audit_event_created(self, mock_finish, mock_start, mock_llm, db):
        """Quote sheet generation should log a plain-English audit event (C3)."""
        rfq = _create_rfq(db)

        mock_run = MagicMock()
        mock_run.id = 3
        mock_start.return_value = mock_run
        mock_llm.return_value = _mock_sheet_response(rfq.id)

        generate_quote_sheet(db, rfq.id)

        events = db.query(AuditEvent).filter(AuditEvent.rfq_id == rfq.id).all()
        assert len(events) == 1
        assert events[0].event_type == "quote_sheet_generated"
        assert events[0].actor == "quote_sheet_agent"
        assert "Quote sheet prepared" in events[0].description

    @patch("backend.agents.quote_sheet.call_llm")
    @patch("backend.agents.quote_sheet.start_run")
    @patch("backend.agents.quote_sheet.finish_run")
    @patch("backend.agents.quote_sheet.fail_run")
    def test_no_tool_call_fails_gracefully(self, mock_fail, mock_finish, mock_start, mock_llm, db):
        rfq = _create_rfq(db)

        mock_run = MagicMock()
        mock_run.id = 4
        mock_start.return_value = mock_run
        mock_llm.return_value = LLMResponse(
            content="Here's a quote sheet...", tool_calls=[],
            input_tokens=500, output_tokens=200, model="claude-sonnet-4-6",
        )

        result = generate_quote_sheet(db, rfq.id)
        assert result is None
        mock_fail.assert_called_once()

    @patch("backend.agents.quote_sheet.call_llm")
    @patch("backend.agents.quote_sheet.start_run")
    @patch("backend.agents.quote_sheet.finish_run")
    def test_sheet_contains_all_carrier_fields(self, mock_finish, mock_start, mock_llm, db):
        """The sheet must contain everything a carrier needs to quote."""
        rfq = _create_rfq(db)

        mock_run = MagicMock()
        mock_run.id = 5
        mock_start.return_value = mock_run
        mock_llm.return_value = _mock_sheet_response(rfq.id)

        sheet = generate_quote_sheet(db, rfq.id)

        # Carrier-essential fields
        assert "reference_id" in sheet
        assert "summary" in sheet
        assert "lanes" in sheet
        lane = sheet["lanes"][0]
        assert "origin" in lane
        assert "destination" in lane
        assert "equipment" in lane
        assert "truck_count" in lane
        assert "commodity" in lane
