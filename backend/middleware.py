"""
backend/middleware.py — FastAPI middleware for observability (#52).

RequestIdMiddleware generates a unique request_id for each HTTP request
and injects it into the logging context (via contextvars). This means
every log line within a request automatically includes the request_id
without callers needing to pass it explicitly.

Cross-cutting constraints:
    NFR-OB-3 — Structured JSON logs include request_id on every line
"""

import time
import uuid
import logging

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from backend.logging_config import request_id_var

logger = logging.getLogger("golteris.middleware")


class RequestIdMiddleware(BaseHTTPMiddleware):
    """
    Assigns a UUID request_id to every incoming HTTP request.

    The request_id is:
    1. Set in the contextvar so all log lines include it automatically
    2. Added to the response headers (X-Request-ID) for client-side tracing
    3. Logged at the end of the request with duration for latency tracking
    """

    async def dispatch(self, request: Request, call_next) -> Response:
        req_id = str(uuid.uuid4())[:8]  # Short ID for readability
        request_id_var.set(req_id)

        start = time.perf_counter()

        response = await call_next(request)

        duration_ms = round((time.perf_counter() - start) * 1000, 1)
        response.headers["X-Request-ID"] = req_id

        # Log the request completion with duration (skip health checks to reduce noise)
        if request.url.path != "/health":
            logger.info(
                "%s %s → %d (%.1fms)",
                request.method,
                request.url.path,
                response.status_code,
                duration_ms,
                extra={"duration_ms": duration_ms, "status_code": response.status_code},
            )

        return response
