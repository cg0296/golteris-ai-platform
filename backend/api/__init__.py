"""
backend/api/ — FastAPI routers for the Golteris REST API.

Each module defines a router for a specific domain area (rfqs, approvals,
agent runs, etc.). Routers are registered in backend/main.py via
app.include_router().

All routes are prefixed with /api/ and return JSON responses.
Cross-cutting constraints (C3 — plain English, C4 — visible reasoning)
apply to every response.
"""
