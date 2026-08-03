"""Async SQLAlchemy 2.0 engine, session factory, and declarative base.

This module is the single owner of the database connection lifecycle. Business
code never instantiates an engine or a session directly — it receives an
:class:`~sqlalchemy.ext.asyncio.AsyncSession` through dependency injection
(see :mod:`src.core.deps`).
"""

from __future__ import annotations

from sqlalchemy import MetaData
from sqlalchemy.ext.asyncio import (
    AsyncAttrs,
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from src.core.config import settings

# Deterministic constraint naming keeps Alembic autogenerate diffs stable and
# lets migrations drop/alter constraints by predictable names across schemas.
NAMING_CONVENTION: dict[str, str] = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(AsyncAttrs, DeclarativeBase):
    """Declarative base shared by every ORM model in the monolith.

    All module models inherit from this single base so that Alembic sees one
    unified :class:`~sqlalchemy.MetaData` graph spanning the ``auth`` and
    ``monitoring`` schemas. Per-table schema placement is done with
    ``__table_args__ = {"schema": "<name>"}`` inside each model.
    """

    metadata = MetaData(naming_convention=NAMING_CONVENTION)


# A single async engine per process. ``pool_pre_ping`` transparently recycles
# connections dropped by PostgreSQL / a load balancer, avoiding stale-socket
# errors after idle periods.
engine: AsyncEngine = create_async_engine(
    settings.database_url,
    echo=settings.debug,
    pool_pre_ping=True,
    pool_size=10,
    max_overflow=20,
    connect_args={
        # Server-side backstop against leaked transactions: if any code path
        # abandons a connection mid-transaction (e.g. a cancelled request task
        # that never reached its session cleanup), PostgreSQL terminates the
        # session after 5 minutes instead of holding row locks and a pool slot
        # forever (an incident left `idle in transaction` connections alive for
        # 22h and exhausted the pool). Generous enough for harvest tasks that
        # await WB rate-limit backoffs between statements inside one
        # transaction; `pool_pre_ping` transparently replaces any connection
        # PostgreSQL kills.
        "server_settings": {"idle_in_transaction_session_timeout": "300000"},
    },
)

# ``expire_on_commit=False`` lets us safely read attributes off returned ORM
# instances after the request-scoped session has committed and closed.
AsyncSessionLocal: async_sessionmaker[AsyncSession] = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
)


async def dispose_engine() -> None:
    """Dispose of the connection pool.

    Called on application shutdown, and at every Celery task boundary by
    :func:`src.core.tasks.run_task` — a task's private event loop must not hand
    the next task a pooled connection bound to a loop that no longer exists.
    """
    await engine.dispose()
