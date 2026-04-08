"""
backend/logging_config.py — Structured JSON logging configuration (#52).

Configures Python's logging to output structured JSON logs with context
fields (request_id, run_id, rfq_id) on every line. This enables tracing
any complaint to root cause (NFR-OB-3).

The JsonFormatter outputs each log line as a single JSON object:
    {"timestamp": "...", "level": "INFO", "logger": "golteris.api",
     "message": "...", "request_id": "abc-123", "rfq_id": 42}

Usage:
    from backend.logging_config import setup_logging
    setup_logging()  # Call once at app startup

Context fields are injected via contextvars (see middleware.py) so they
automatically appear on every log line within the same request.
"""

import json
import logging
import sys
from contextvars import ContextVar
from datetime import datetime, timezone

# Context variables for structured log fields — set by middleware, read by formatter
request_id_var: ContextVar[str] = ContextVar("request_id", default="")
run_id_var: ContextVar[int | None] = ContextVar("run_id", default=None)
rfq_id_var: ContextVar[int | None] = ContextVar("rfq_id", default=None)


class JsonFormatter(logging.Formatter):
    """
    Formats log records as single-line JSON objects.

    Includes standard fields (timestamp, level, logger, message) plus
    context fields from contextvars (request_id, run_id, rfq_id) when
    they are set by the request middleware or worker context.
    """

    def format(self, record: logging.LogRecord) -> str:
        log_entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }

        # Add context fields if set (from middleware or worker)
        req_id = request_id_var.get("")
        if req_id:
            log_entry["request_id"] = req_id

        run_id = run_id_var.get(None)
        if run_id is not None:
            log_entry["run_id"] = run_id

        rfq_id = rfq_id_var.get(None)
        if rfq_id is not None:
            log_entry["rfq_id"] = rfq_id

        # Include exception info if present
        if record.exc_info and record.exc_info[1]:
            log_entry["exception"] = self.formatException(record.exc_info)

        # Include any extra fields attached to the log record
        for key in ("duration_ms", "cost_usd", "provider", "job_type", "status_code"):
            val = getattr(record, key, None)
            if val is not None:
                log_entry[key] = val

        return json.dumps(log_entry)


def setup_logging(level: str = "INFO") -> None:
    """
    Configure the root logger with structured JSON output.

    Call once at application startup (in main.py lifespan or worker entry).
    Replaces the default text formatter with JsonFormatter for all handlers.

    Args:
        level: Logging level (default: INFO). Set via LOG_LEVEL env var.
    """
    root = logging.getLogger()
    root.setLevel(getattr(logging, level.upper(), logging.INFO))

    # Remove existing handlers to avoid duplicate output
    root.handlers.clear()

    # JSON handler → stdout (picked up by Render, Docker, etc.)
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    root.addHandler(handler)

    # Quiet noisy third-party loggers
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)
