"""
backend/db/database.py — Database connection and session management.

This module provides the SQLAlchemy engine, session factory, and a dependency
function for FastAPI route injection. All database access in the application
goes through the session provided by get_db().

Connection string comes from the DATABASE_URL environment variable.
See .env.example for the expected format.
"""

import os

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

# DATABASE_URL must be set in the environment (see .env.example).
# For local dev: postgresql://golteris:golteris@localhost:5432/golteris
# For Render: automatically provided by the managed Postgres add-on.
DATABASE_URL = os.environ.get("DATABASE_URL", "postgresql://golteris:golteris@localhost:5432/golteris")

# Create the SQLAlchemy engine. pool_pre_ping=True ensures stale connections
# are detected and recycled, which matters on managed Postgres (Render) where
# connections can be killed by the provider.
engine = create_engine(DATABASE_URL, pool_pre_ping=True)

# Session factory — each call to SessionLocal() creates a new database session.
# autocommit=False and autoflush=False give us explicit transaction control,
# which is important for the SELECT ... FOR UPDATE SKIP LOCKED job queue pattern.
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def get_db():
    """
    FastAPI dependency that provides a database session.

    Usage in a route:
        @app.get("/api/rfqs")
        def list_rfqs(db: Session = Depends(get_db)):
            ...

    The session is automatically closed when the request finishes,
    even if an exception occurs.
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
