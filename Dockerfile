# =============================================================================
# Golteris — Dockerfile
# =============================================================================
#
# Multi-stage build for the Golteris application.
#
# Stage 1 (frontend-build): Builds the React frontend with Vite.
#   - Installs Node dependencies
#   - Runs `npm run build` which outputs to frontend/dist/
#
# Stage 2 (backend): Sets up the Python backend.
#   - Installs Python dependencies
#   - Copies the frontend build output into the backend's serving directory
#   - Runs the FastAPI web server with Uvicorn
#
# The result is a single container that serves both the API and the frontend.
# See REQUIREMENTS.md §2.3 — "Single deploy: vite build outputs static files;
# FastAPI serves them from a /static folder on the same Render service."
#
# Usage:
#   docker build -t golteris .
#   docker run -p 8000:8000 -e DATABASE_URL=... -e ANTHROPIC_API_KEY=... golteris
#
# On Render, this Dockerfile is used automatically by the Web Service defined
# in render.yaml.
# =============================================================================

# ---------------------------------------------------------------------------
# Stage 1: Build the React frontend
# ---------------------------------------------------------------------------
FROM node:20-slim AS frontend-build

WORKDIR /app/frontend

# Copy package files first for better Docker layer caching —
# dependencies only re-install when package.json or lock file changes.
COPY frontend/package*.json ./

# Install dependencies. Using `npm ci` for reproducible builds
# (installs exactly what's in package-lock.json).
RUN npm ci

# Copy the rest of the frontend source and build it.
# Vite outputs to frontend/dist/ by default.
COPY frontend/ ./
RUN npm run build

# ---------------------------------------------------------------------------
# Stage 2: Python backend + frontend static files
# ---------------------------------------------------------------------------
FROM python:3.12-slim

WORKDIR /app

# Install system dependencies needed by psycopg2 (Postgres driver).
# These are build-time only — the slim image doesn't include them.
RUN apt-get update && \
    apt-get install -y --no-install-recommends libpq-dev gcc && \
    rm -rf /var/lib/apt/lists/*

# Copy and install Python dependencies first for layer caching.
COPY backend/requirements.txt ./backend/requirements.txt
RUN pip install --no-cache-dir -r backend/requirements.txt

# Copy the backend source code.
COPY backend/ ./backend/
COPY alembic.ini ./alembic.ini

# Copy the frontend build output from Stage 1 into the directory that
# FastAPI's static file serving expects (see backend/main.py).
COPY --from=frontend-build /app/frontend/dist ./frontend/dist

# Expose the port that Uvicorn will listen on.
# Render sets the PORT environment variable; we default to 8000.
EXPOSE 8000

# Run Alembic migrations on startup, then start the web server.
# The migration step ensures the database schema is up to date on every deploy.
# If migrations fail, the container exits and Render will not route traffic to it.
CMD alembic upgrade head && \
    uvicorn backend.main:app --host 0.0.0.0 --port ${PORT:-8000}
