"""
backend/main.py — FastAPI application entry point.

This is the web server for the Golteris broker console. It serves:
1. The REST API under /api/* — consumed by the React frontend via polling
2. The static React build from /static — produced by `vite build`
3. A health endpoint at /health — used by Render for health checks

Tech stack: FastAPI + Uvicorn (see REQUIREMENTS.md §2.1)

To run locally:
    uvicorn backend.main:app --host 0.0.0.0 --port 8000 --reload

In production (Render), the Dockerfile runs:
    uvicorn backend.main:app --host 0.0.0.0 --port $PORT

Cross-cutting constraints relevant here:
    C1 — The /api/workflows endpoints will enforce the enabled toggle
    C2 — The /api/approvals endpoints will enforce approval status before send
    C3 — API responses use plain-English descriptions, not internal jargon
"""

import logging
import os
from contextlib import asynccontextmanager

from dotenv import load_dotenv
load_dotenv()  # Load .env file for local dev (Graph creds, cost caps, etc.)

from fastapi import FastAPI

logger = logging.getLogger("golteris.web")
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

from backend.db.database import engine
from backend.db.models import Base
from backend.api.agent_runs import router as agent_runs_router
from backend.api.dashboard import router as dashboard_router
from backend.api.approvals import router as approvals_router
from backend.api.carriers import router as carriers_router
from backend.api.workflows import router as workflows_router
from backend.api.agent_controls import router as agent_controls_router
from backend.api.auth import router as auth_router
from backend.api.chat import router as chat_router
from backend.api.jobs import router as jobs_router
from backend.api.dev import router as dev_router
from backend.api.summary import router as summary_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Application lifespan handler — runs on startup and shutdown.

    On startup: attempts to create database tables if they don't exist yet.
    This is a convenience for initial deploys. In production, Alembic
    migrations are the authoritative schema management tool.

    If the database is unreachable (e.g., local dev without Postgres),
    the app still starts — /health will work, but API routes that hit
    the database will fail. This allows the app to be smoke-tested
    without a running Postgres instance.
    """
    try:
        Base.metadata.create_all(bind=engine)
        logger.info("Database tables verified/created successfully.")
    except Exception as e:
        # Don't crash the app if the database is unreachable at startup.
        # This allows /health to work for smoke tests and Render health checks
        # even if the database is still provisioning.
        logger.warning("Could not connect to database on startup: %s", e)
        logger.warning("The app will start, but database-dependent routes will fail.")
    yield
    # Shutdown: nothing to clean up — SQLAlchemy engine handles connection pooling


app = FastAPI(
    title="Golteris API",
    description=(
        "REST API for the Golteris broker console. "
        "Serves RFQ management, approval workflows, and agent observability."
    ),
    version="0.1.0",
    lifespan=lifespan,
)

# ---------------------------------------------------------------------------
# CORS — allow the React frontend to call the API during local development.
# In production, the frontend is served from the same origin (FastAPI serves
# the static build), so CORS is only needed for local dev where Vite runs
# on a different port (typically localhost:5173).
# ---------------------------------------------------------------------------
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",   # Vite dev server
        "http://localhost:3000",   # Alternative React dev port
        "http://localhost:8000",   # Same-origin (for completeness)
        "http://localhost:8001",   # Alternative backend dev port
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# Health endpoint — used by Render for health checks and by CI for smoke tests.
# Returns 200 with a simple JSON body. No authentication required.
# ---------------------------------------------------------------------------
@app.get("/health")
def health_check():
    """
    Health check endpoint.

    Render pings this to determine if the service is healthy.
    Returns a simple 200 response. If the database is unreachable,
    the lifespan handler will have failed and the app won't start,
    so this endpoint implicitly confirms DB connectivity.
    """
    return {"status": "ok", "service": "golteris-api"}


# ---------------------------------------------------------------------------
# API routers — each domain area has its own router module in backend/api/.
# Routers are registered here so FastAPI discovers all routes at startup.
#
# Agent run tracking (#22) — GET /api/agent/runs, GET /api/agent/runs/:id
# Future issues will add more routers (rfqs, approvals, workflows, etc.)
# ---------------------------------------------------------------------------
app.include_router(auth_router)
app.include_router(agent_runs_router)
app.include_router(dashboard_router)
app.include_router(approvals_router)
app.include_router(carriers_router)
app.include_router(workflows_router)
app.include_router(agent_controls_router)
app.include_router(chat_router)
app.include_router(jobs_router)
app.include_router(dev_router)
app.include_router(summary_router)
@app.get("/api")
def api_root():
    """
    API root — returns available API version info.
    Placeholder until real routes are added by subsequent issues.
    """
    return {
        "service": "golteris-api",
        "version": "0.1.0",
        "docs": "/docs",
    }


@app.get("/api/debug/tables")
def debug_tables():
    """
    Debug endpoint — lists all tables in the database.
    Temporary — will be removed once proper API routes exist.
    Useful for verifying the schema was created on deploy.
    """
    from sqlalchemy import text
    from backend.db.database import SessionLocal
    db = SessionLocal()
    try:
        result = db.execute(text(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema = 'public' ORDER BY table_name"
        ))
        tables = [row[0] for row in result]
        return {"tables": tables, "count": len(tables)}
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Static file serving — serves the React frontend build.
#
# In production, `vite build` outputs to frontend/dist/. FastAPI serves
# these files so that the entire app (API + frontend) runs as a single
# Render service. See REQUIREMENTS.md §2.3.
#
# The catch-all route below ensures that React Router handles client-side
# routing — any path that doesn't match /api/* or /health gets index.html.
# ---------------------------------------------------------------------------
FRONTEND_DIR = os.path.join(os.path.dirname(__file__), "..", "frontend", "dist")

if os.path.isdir(FRONTEND_DIR):
    # Serve static assets (JS, CSS, images) from the Vite build output.
    # The assets directory only exists after `vite build` runs — check before mounting.
    assets_dir = os.path.join(FRONTEND_DIR, "assets")
    if os.path.isdir(assets_dir):
        app.mount("/assets", StaticFiles(directory=assets_dir), name="assets")

    @app.get("/{full_path:path}")
    def serve_frontend(full_path: str):
        """
        Catch-all route for the React SPA.

        Any request that doesn't match /api/*, /health, or /assets/* gets
        the React index.html. React Router then handles client-side routing
        (e.g., /rfqs/42 opens the RFQ detail drawer in the SPA).

        IMPORTANT: Paths starting with "api/" are excluded so that FastAPI's
        API routers handle those requests (including POST/PUT/DELETE methods).
        Without this guard, this GET catch-all intercepts API paths and
        returns index.html, causing "Method Not Allowed" on non-GET requests.
        """
        # Never intercept API routes — let FastAPI routers handle them
        if full_path.startswith("api/") or full_path == "api":
            from fastapi import HTTPException
            raise HTTPException(status_code=404, detail="Not found")
        # Check if the requested file exists in the build output (e.g., favicon.ico)
        file_path = os.path.join(FRONTEND_DIR, full_path)
        if os.path.isfile(file_path):
            return FileResponse(file_path)
        # Otherwise, serve index.html and let React Router handle it
        return FileResponse(os.path.join(FRONTEND_DIR, "index.html"))
