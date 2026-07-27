"""Integration tests for the request-scoped unit of work (``src.core.deps.get_db``).

This dependency is the reason a production incident left ``idle in transaction``
connections alive for 22 hours until the pool was exhausted and the API served
nothing but a frozen shell. The fix has three parts, and all three are tested
here because none of them can be observed without a real connection:

* one transaction per request — the session commits when the handler returns,
  so repository ``flush``es actually persist;
* rollback on any exception, so a failed request never half-applies a write;
* cleanup runs even when the request task is **cancelled** — a client
  disconnect cancels the handler mid-await, and unshielded cleanup would be
  cancelled at its own first await, leaking the connection with its transaction
  still open.

The last one is the whole point of the ``asyncio.shield`` in ``get_db``, and a
mock cannot demonstrate it: it needs a connection that can genuinely be left
checked out.
"""

from __future__ import annotations

import asyncio

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from src.core.deps import get_db
from src.modules.users.models import User
from tests.support.auth import known_password_hash


@pytest.fixture
def unit_of_work(
    engine: AsyncEngine, monkeypatch: pytest.MonkeyPatch
) -> async_sessionmaker[AsyncSession]:
    """Point ``get_db`` at the test database with real, committing sessions.

    Unlike the rest of the tier these sessions are *not* joined to a rolled-back
    outer transaction — the behaviour under test is the commit/rollback itself,
    so it has to be real. Each test cleans up the rows it writes.
    """
    factory = async_sessionmaker(bind=engine, expire_on_commit=False, autoflush=False)
    monkeypatch.setattr("src.core.deps.AsyncSessionLocal", factory)
    return factory


@pytest.fixture
async def cleanup_users(
    engine: AsyncEngine,
) -> None:
    """Remove any user rows this module committed."""
    yield
    async with engine.begin() as conn:
        await conn.execute(sa.text("DELETE FROM auth.users WHERE email LIKE 'uow-%'"))


def _user(email: str) -> User:
    """Build a user row tagged so the cleanup fixture can find it."""
    return User(email=email, hashed_password=known_password_hash(), is_active=True, role="user")


async def test_a_successful_request_commits_its_writes(
    unit_of_work: async_sessionmaker[AsyncSession], engine: AsyncEngine, cleanup_users: None
) -> None:
    """Without the commit, every repository flush would be silently discarded.

    This is not theoretical: a session that closes without committing rolls
    back, so *no* API write would ever persist.
    """
    generator = get_db()
    session = await anext(generator)
    session.add(_user("uow-committed@example.com"))
    await session.flush()

    with pytest.raises(StopAsyncIteration):
        await anext(generator)

    async with engine.connect() as conn:
        found = await conn.scalar(
            sa.text("SELECT count(*) FROM auth.users WHERE email = 'uow-committed@example.com'")
        )
    assert found == 1


async def test_a_failing_request_rolls_its_writes_back(
    unit_of_work: async_sessionmaker[AsyncSession], engine: AsyncEngine, cleanup_users: None
) -> None:
    """A handler that raises must leave nothing behind.

    Half-applied writes are how a 500 turns into corrupt data rather than a
    retryable error.
    """
    generator = get_db()
    session = await anext(generator)
    session.add(_user("uow-rolledback@example.com"))
    await session.flush()

    with pytest.raises(RuntimeError):
        await generator.athrow(RuntimeError("handler blew up"))

    async with engine.connect() as conn:
        found = await conn.scalar(
            sa.text("SELECT count(*) FROM auth.users WHERE email = 'uow-rolledback@example.com'")
        )
    assert found == 0


async def test_the_session_holds_no_transaction_after_a_successful_request(
    unit_of_work: async_sessionmaker[AsyncSession],
) -> None:
    """The connection returns to the pool; a leak here exhausts it in hours.

    ``in_transaction()`` is the property that reflects a released connection —
    ``is_active`` only reports whether the session is in partial-rollback state
    and stays ``True`` on a perfectly closed session.
    """
    generator = get_db()
    session = await anext(generator)
    await session.execute(sa.text("SELECT 1"))
    assert session.in_transaction() is True

    with pytest.raises(StopAsyncIteration):
        await anext(generator)

    assert session.in_transaction() is False


async def test_a_cancelled_request_still_releases_its_connection(
    unit_of_work: async_sessionmaker[AsyncSession], engine: AsyncEngine, cleanup_users: None
) -> None:
    """A client disconnect must not leak an open transaction.

    The middleware runs handlers inside an anyio cancel scope, so a disconnect
    cancels the task mid-await. Unshielded, the rollback would be cancelled at
    its own first await and the connection would sit ``idle in transaction``,
    holding row locks until the server-side timeout — the exact incident that
    took the API down.
    """
    session_holder: dict[str, AsyncSession] = {}

    async def request_that_gets_cancelled() -> None:
        generator = get_db()
        session = await anext(generator)
        session_holder["session"] = session
        session.add(_user("uow-cancelled@example.com"))
        await session.flush()
        try:
            await asyncio.sleep(30)  # stand-in for a slow handler
        except asyncio.CancelledError:
            await generator.athrow(asyncio.CancelledError())
            raise

    task = asyncio.create_task(request_that_gets_cancelled())
    await asyncio.sleep(0.2)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert session_holder["session"].in_transaction() is False
    async with engine.connect() as conn:
        found = await conn.scalar(
            sa.text("SELECT count(*) FROM auth.users WHERE email = 'uow-cancelled@example.com'")
        )
    assert found == 0


async def test_no_connection_is_left_idle_in_transaction(
    unit_of_work: async_sessionmaker[AsyncSession], engine: AsyncEngine, cleanup_users: None
) -> None:
    """After a burst of cancelled requests, the server reports no stuck sessions.

    This asserts the symptom the incident was diagnosed by, straight from
    ``pg_stat_activity`` — the closest a test can get to reproducing it.
    """

    async def cancelled_request() -> None:
        generator = get_db()
        session = await anext(generator)
        await session.execute(sa.text("SELECT 1"))
        try:
            await asyncio.sleep(30)
        except asyncio.CancelledError:
            await generator.athrow(asyncio.CancelledError())
            raise

    tasks = [asyncio.create_task(cancelled_request()) for _ in range(5)]
    await asyncio.sleep(0.3)
    for task in tasks:
        task.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)

    async with engine.connect() as conn:
        stuck = await conn.scalar(
            sa.text(
                "SELECT count(*) FROM pg_stat_activity "
                "WHERE state = 'idle in transaction' AND datname = current_database()"
            )
        )
    assert stuck == 0
