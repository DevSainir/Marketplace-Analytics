"""Alembic migration environment.

Configured for the modular monolith's multi-schema layout:

* The database URL is pulled from :mod:`src.core.config` (never hard-coded).
* Every module's models are imported so a single unified metadata graph drives
  autogenerate across the ``auth`` and ``monitoring`` schemas.
* ``include_schemas=True`` lets Alembic detect and diff non-public schemas; a
  ``CREATE SCHEMA IF NOT EXISTS`` guard runs before applying migrations.
"""

from __future__ import annotations

from logging.config import fileConfig

from sqlalchemy import engine_from_config, pool, text

# Import model modules for their side effect: registering tables on Base.metadata.
import src.modules.monitoring.models
import src.modules.users.models
from alembic import context
from src.core.config import settings
from src.core.database import Base

# All logical schemas that must exist before migrations run.
_SCHEMAS: tuple[str, ...] = ("auth", "monitoring")

config = context.config
config.set_main_option("sqlalchemy.url", settings.sync_database_url)

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def _ensure_schemas(connection: object) -> None:
    """Create every required logical schema if it does not already exist."""
    for schema in _SCHEMAS:
        connection.execute(text(f'CREATE SCHEMA IF NOT EXISTS "{schema}"'))  # type: ignore[attr-defined]


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode, emitting SQL to stdout."""
    context.configure(
        url=settings.sync_database_url,
        target_metadata=target_metadata,
        literal_binds=True,
        include_schemas=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode against a live connection."""
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        _ensure_schemas(connection)
        connection.commit()
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            include_schemas=True,
            compare_type=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
