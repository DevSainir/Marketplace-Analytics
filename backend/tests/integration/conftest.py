"""Integration-tier fixtures: a real PostgreSQL database and a real Redis.

Design decisions worth knowing before you add a test here:

* **A dedicated database.** Everything runs against ``marketplace_test`` (or
  ``TEST_POSTGRES_DB``), created on demand next to the dev database. Tests never
  touch ``marketplace`` — it holds real harvested WB data.
* **Schema from the models, not from Alembic.** ``Base.metadata.create_all`` is
  ~100× faster than replaying every migration, and it is the models that the
  repositories are written against. The migrations get their own dedicated test
  (``test_migrations.py``) which is the right place to prove they still produce
  that schema.
* **One transaction per test, always rolled back.** Tests share a schema but
  never share rows, so they stay order-independent and leave nothing behind.
* **Auto-skip, never auto-fail.** If Postgres or Redis is unreachable the
  affected tests skip with a clear reason, so ``pytest`` on a laptop without
  docker still exits 0. CI supplies both services and therefore runs them all.
* **Redis DB 15.** A throwaway index, flushed per test, so a run can never
  clobber the dev cache on index 0.
"""

from __future__ import annotations

import asyncio
import os
from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import (
    AsyncConnection,
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool

# Importing every model module registers its tables on the shared metadata;
# without this, create_all() would build an empty schema.
import src.modules.finreports.models
import src.modules.monitoring.models
import src.modules.organizations.models
import src.modules.users.models
from src.core.config import settings
from src.core.database import Base
from src.modules.organizations.models import Organization, Subscription

import src.modules.workspaces.models  # noqa: F401  isort:skip

#: Logical schemas the monolith owns; mirrors ``alembic/env.py``.
SCHEMAS: tuple[str, ...] = (
    "auth",
    "monitoring",
    "workspaces",
    "finreports",
    "ab_tests",
    "organizations",
    "guide",
)

#: Name of the throwaway database. Overridable so CI can shard runs.
TEST_DB_NAME: str = os.getenv("TEST_POSTGRES_DB", "marketplace_test")

#: Redis logical database reserved for tests (never the app's index 0).
TEST_REDIS_DB: int = int(os.getenv("TEST_REDIS_DB", "15"))


def _dsn(database: str) -> str:
    """Build an asyncpg DSN for a database on the configured Postgres host.

    Args:
        database: The database name to connect to.

    Returns:
        A ``postgresql+asyncpg://`` URL reusing the app's credentials/host.
    """
    return settings.database_url.rsplit("/", 1)[0] + f"/{database}"


async def _provision_test_database() -> None:
    """Create the test database (if absent) and build the schema in it.

    Raises:
        OSError: Propagated when Postgres is unreachable, so the caller can
            turn it into a skip rather than a failure.
    """
    admin = create_async_engine(_dsn("postgres"), poolclass=NullPool, isolation_level="AUTOCOMMIT")
    try:
        async with admin.connect() as conn:
            exists = await conn.scalar(
                sa.text("SELECT 1 FROM pg_database WHERE datname = :name"),
                {"name": TEST_DB_NAME},
            )
            if not exists:
                await conn.execute(sa.text(f'CREATE DATABASE "{TEST_DB_NAME}"'))
    finally:
        await admin.dispose()

    engine = create_async_engine(_dsn(TEST_DB_NAME), poolclass=NullPool)
    try:
        async with engine.begin() as conn:
            for schema in SCHEMAS:
                await conn.execute(sa.text(f'CREATE SCHEMA IF NOT EXISTS "{schema}"'))
            await conn.run_sync(Base.metadata.create_all)
    finally:
        await engine.dispose()


@pytest.fixture(scope="session")
def postgres_ready() -> bool:
    """Provision the test database once per session; skip the tier if absent.

    Returns:
        ``True`` when the database is ready (the value is incidental — the
        fixture's real job is the skip).
    """
    try:
        asyncio.run(_provision_test_database())
    except Exception as exc:
        pytest.skip(
            f"PostgreSQL is unreachable ({type(exc).__name__}: {exc}); "
            "start it with `docker compose up -d postgres` to run this tier.",
            allow_module_level=True,
        )
    return True


@pytest.fixture(scope="session")
def engine(postgres_ready: bool) -> Iterator[AsyncEngine]:
    """Yield a session-wide async engine bound to the test database.

    ``NullPool`` is deliberate: each test runs in its own event loop, and a
    pooled asyncpg connection created in one loop cannot be reused in the next.
    """
    test_engine = create_async_engine(_dsn(TEST_DB_NAME), poolclass=NullPool)
    yield test_engine
    asyncio.run(test_engine.dispose())


@pytest.fixture
async def db_connection(engine: AsyncEngine) -> AsyncIterator[AsyncConnection]:
    """Yield a connection wrapped in a transaction that is always rolled back.

    Everything a test writes — including anything committed by a nested session
    — disappears when this transaction unwinds.
    """
    async with engine.connect() as connection:
        transaction = await connection.begin()
        try:
            yield connection
        finally:
            await transaction.rollback()


@pytest.fixture
def session_factory(db_connection: AsyncConnection) -> async_sessionmaker[AsyncSession]:
    """A session factory whose sessions join the test's outer transaction.

    ``join_transaction_mode="create_savepoint"`` turns a session ``commit()``
    into a savepoint release, so production code that commits (the breach
    handler opens its own session on purpose) behaves normally while the outer
    rollback still cleans up.
    """
    return async_sessionmaker(
        bind=db_connection,
        expire_on_commit=False,
        autoflush=False,
        join_transaction_mode="create_savepoint",
    )


@pytest.fixture
async def db_session(
    session_factory: async_sessionmaker[AsyncSession],
) -> AsyncIterator[AsyncSession]:
    """Yield the request-scoped session repositories and services are built on."""
    async with session_factory() as session:
        yield session


@pytest.fixture
async def redis_client(monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[Any]:
    """Yield a Redis client on the throwaway test index, flushed per test.

    The shared client in :mod:`src.core.redis` is swapped for this one, so code
    under test (the rate limiter, the revocation watermark) hits the test index
    rather than the app's.
    """
    from redis.asyncio import Redis

    from src.core import redis as core_redis

    url = settings.redis_url.rsplit("/", 1)[0] + f"/{TEST_REDIS_DB}"
    client = Redis.from_url(url, decode_responses=True)
    try:
        await client.ping()
    except Exception as exc:
        await client.aclose()
        pytest.skip(
            f"Redis is unreachable ({type(exc).__name__}: {exc}); "
            "start it with `docker compose up -d redis` to run this test."
        )

    await client.flushdb()
    monkeypatch.setattr(core_redis, "_redis", client)
    monkeypatch.setattr(core_redis, "get_redis", lambda: client)
    try:
        yield client
    finally:
        await client.flushdb()
        await client.aclose()


@pytest.fixture
async def api_client(
    session_factory: async_sessionmaker[AsyncSession],
) -> AsyncIterator[Any]:
    """Yield an httpx client for the real app, bound to the test transaction.

    ``get_db`` is overridden so every request runs against the same rolled-back
    connection as the test body — a route can write a row and the test can read
    it back through ``db_session`` without a commit escaping.
    """
    import httpx

    from main import app
    from src.core.deps import get_db

    async def _test_db() -> AsyncIterator[AsyncSession]:
        async with session_factory() as session:
            try:
                yield session
                await session.commit()
            except BaseException:
                await session.rollback()
                raise

    app.dependency_overrides[get_db] = _test_db
    transport = httpx.ASGITransport(app=app)
    try:
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            yield client
    finally:
        app.dependency_overrides.pop(get_db, None)


@pytest.fixture
async def organization(db_session: AsyncSession) -> Organization:
    """A persisted, non-primary organisation to hang a tenant's rows off.

    Every workspace now belongs to one (``organization_id`` is NOT NULL), so a
    test that needs a workspace needs one of these first. Non-primary by
    default: the primary flag unlocks the internal-only features, and a test
    that gets it by accident would be asserting against the wrong tenant.

    It comes **paid up**, because activation always leaves a subscription row
    and since 2026-09-09 an organisation without one reaches nothing at all:
    the ramp reads a missing row as ``expired``, and every tenant-scoped route
    then refuses. A fixture without a term would not be a plain organisation —
    it would be a lapsed tenant, and a test using it for something else (an
    audit entry, a workspace, an A/B row) would be asserting against a 403 it
    never meant to ask for. A test that wants the lapsed case says so, by
    moving ``expires_at`` back the way ``test_token_persistence`` does.
    """
    org = Organization(name="Тестовая организация", is_primary=False)
    db_session.add(org)
    await db_session.flush()
    now = datetime.now(UTC)
    db_session.add(
        Subscription(
            organization_id=org.id,
            started_at=now - timedelta(days=1),
            expires_at=now + timedelta(days=30),
            grace_days=settings.subscription_grace_days,
        )
    )
    await db_session.flush()
    return org
