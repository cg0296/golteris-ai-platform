# Procfile — Process definitions for Render (fallback if not using render.yaml).
#
# web:    FastAPI server serving the API and React frontend build.
# worker: Background job processor and mailbox poller.
#
# Render uses this to know which processes to run for each service type.

web: alembic upgrade head && uvicorn backend.main:app --host 0.0.0.0 --port ${PORT:-8000}
worker: alembic upgrade head && python -m backend.worker
