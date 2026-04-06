"""
Alembic environment configuration.

This file tells Alembic how to connect to the database and which models
to use for auto-generating migrations. It imports all models from
backend.db.models so that Alembic's autogenerate can detect schema changes.

See: https://alembic.sqlalchemy.org/en/latest/tutorial.html
"""

import os
import sys
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

# Add the project root to the Python path so we can import backend.db.models
# regardless of where Alembic is invoked from.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", ".."))

from backend.db.models import Base  # noqa: E402 — must come after sys.path fix

# Alembic Config object — provides access to values in alembic.ini
config = context.config

# Set the database URL from the environment variable if available.
# This allows the same alembic.ini to work in dev, CI, and production.
database_url = os.environ.get("DATABASE_URL")
if database_url:
    config.set_main_option("sqlalchemy.url", database_url)

# Set up Python logging from the alembic.ini [loggers] section
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# This is the metadata that Alembic uses to detect schema changes.
# It comes from our Base class which all models inherit from.
target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """
    Run migrations in 'offline' mode — generates SQL without connecting to the DB.
    Useful for generating migration scripts that a DBA can review before applying.
    """
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """
    Run migrations in 'online' mode — connects to the DB and applies changes.
    This is the normal mode used by `alembic upgrade head`.
    """
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
