"""Async SQLAlchemy 2.0 engine, session factory, and declarative base.

This module is the single owner of the database connection lifecycle. Business
code never instantiates an engine or a session directly — it receives an
:class:`~sqlalchemy.ext.asyncio.AsyncSession` through dependency injection
(see :mod:`src.core.deps`).
"""

from __future__ import annotations

import asyncio
from collections.abc import Coroutine

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
from src.core.redis import drain_redis_pool

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
    """Dispose of the connection pool on application shutdown."""
    await engine.dispose()


def run_task[T](coro: Coroutine[object, object, T]) -> T:
    """Run one Celery task's async body on a private loop, then drain the pools.

    Every Celery task is a synchronous function that drives async code through
    its own :func:`asyncio.run`, i.e. its own short-lived event loop. Both the
    engine above AND the process-wide Redis client, however, pool connections
    that stay bound to the loop that opened them. So a task that returns while
    leaving a connection in either pool hands the *next* task a socket whose
    transport belongs to a loop that no longer exists — and that task dies on
    its very first query with ``got Future attached to a different loop`` /
    ``Event loop is closed``, before doing any work.

    (05:00 MSK) leaked an asyncpg connection this way and killed
    ``monitoring.harvest_all`` (06:00 MSK) at its first statement, so 2026-07-27
    harvested nothing at all. And the Redis pool did the quieter version of the
    same thing: the funnel's rate-gate ``acquire`` is the first Redis op in a
    harvest, so every ``harvest_sku_window`` after the worker's first task lost
    its ``sales-funnel`` source to ``Event loop is closed`` — silently, because
    the gate only catches :class:`RedisError` and a failed source is a tolerated
    partial harvest. «Обновить все SKU» kept reporting success with
    ``funnel_rows: 0``.

    Draining here rather than in each task body is the point: the invariant
    holds for every task that uses this entrypoint, including ones not written
    yet. ``tests/unit/core/test_task_loop_hygiene.py`` fails the build if a
    registered task drives ``asyncio.run`` itself instead of coming through
    here.

    Args:
        coro: The task's async body. Awaited exactly once.

    Returns:
        Whatever ``coro`` returns.
    """

    async def _run() -> T:
        try:
            return await coro
        finally:
            # Both pools must be drained even if one drain raises, or a failure
            # cleaning one poisons the next task on the other.
            try:
                await drain_redis_pool()
            finally:
                await engine.dispose()

    return asyncio.run(_run())
