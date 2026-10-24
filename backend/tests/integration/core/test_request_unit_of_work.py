"""Integration tests for the request-scoped unit of work (``src.core.deps.get_db``).

This dependency is the reason a production incident left ``idle in transaction``
connections alive for 22 hours until the pool was exhausted and the API served
nothing but a frozen shell. The fix has three parts, and all three are tested
here because none of them can be observed without a real connection:

* one transaction per request — the session commits when the handler returns,
  so repository ``flush``es actually persist;
* rollback on any exception, so a failed request never half-applies a write;
* cleanup runs to completion even when the request is **cancelled** — a client
  disconnect cancels the handler mid-await, and the ``asyncio.shield`` in
  ``get_db`` lets the rollback finish instead of being cancelled at its own
  first await.

What an unshielded rollback costs today is narrower than the incident: under
SQLAlchemy 2.0 a cancelled reset hard-closes the connection, and the server
rolls the transaction back on its own when the socket drops. So the cancelled
test below cannot catch a leak — there is none to catch. It pins what the
shield still buys: the rollback really runs, and the connection goes back to the
pool alive instead of being torn down and re-opened for every disconnect.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from datetime import UTC, datetime

import anyio
import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from src.core.deps import get_db
from src.modules.users.models import User
from tests.integration.conftest import TEST_DB_NAME, _dsn
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
async def pooled_unit_of_work(monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[None]:
    """Point ``get_db`` at a pooled engine, the way production runs it.

    The tier's shared engine is a ``NullPool``, where closing a session closes
    the connection whatever state it was in — so a rollback that finished and
    one that was abandoned look the same from the server. A real pool tells
    them apart: a finished rollback checks the connection back in alive.
    """
    pooled = create_async_engine(_dsn(TEST_DB_NAME), pool_size=1, max_overflow=0)
    factory = async_sessionmaker(bind=pooled, expire_on_commit=False, autoflush=False)
    monkeypatch.setattr("src.core.deps.AsyncSessionLocal", factory)
    yield
    await pooled.dispose()


async def _backend_state(engine: AsyncEngine, pid: int) -> str | None:
    """Return the server's view of backend ``pid``, or ``None`` once it is gone."""
    async with engine.connect() as conn:
        state: str | None = await conn.scalar(
            sa.text("SELECT state FROM pg_stat_activity WHERE pid = :pid"), {"pid": pid}
        )
    return state


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
    return User(
        email=email,
        hashed_password=known_password_hash(),
        is_active=True,
        role="user",
        email_confirmed_at=datetime.now(UTC),
    )


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


async def test_a_cancelled_request_still_rolls_back_cleanly(
    pooled_unit_of_work: None, engine: AsyncEngine, cleanup_users: None
) -> None:
    """A client disconnect rolls the request back and keeps its connection.

    The cancel comes from an anyio cancel scope, as Starlette's middleware
    delivers it: the scope stays cancelled, so every later await in the cleanup
    is cancelled too — unlike a single ``task.cancel()``, which fires once and
    lets even an unshielded rollback run. Unshielded, the rollback dies at its
    first await and SQLAlchemy hard-closes the connection; the server drops the
    transaction with the socket, so nothing leaks, but nothing was rolled back
    either, and the pool pays a reconnect. Shielded, the rollback finishes in
    the background and the backend is left ``idle``, back in the pool.
    """
    backend: dict[str, int] = {}
    handler_waiting = anyio.Event()

    async def request_that_gets_cancelled() -> None:
        generator = get_db()
        session = await anext(generator)
        backend["pid"] = await session.scalar(sa.text("SELECT pg_backend_pid()"))
        session.add(_user("uow-cancelled@example.com"))
        await session.flush()
        try:
            handler_waiting.set()
            await anyio.sleep(30)  # stand-in for a slow handler
        except BaseException as cancelled:
            await generator.athrow(cancelled)
            raise

    async with anyio.create_task_group() as task_group:
        task_group.start_soon(request_that_gets_cancelled)
        await handler_waiting.wait()
        task_group.cancel_scope.cancel()

    # The shielded rollback outlives the cancelled request, so wait for the
    # backend to leave its transaction — either back to `idle` or gone.
    state = await _backend_state(engine, backend["pid"])
    with anyio.move_on_after(5):
        while state not in ("idle", None):
            await asyncio.sleep(0.02)
            state = await _backend_state(engine, backend["pid"])
    async with engine.connect() as conn:
        found = await conn.scalar(
            sa.text("SELECT count(*) FROM auth.users WHERE email = 'uow-cancelled@example.com'")
        )
    assert (state, found) == ("idle", 0)


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
