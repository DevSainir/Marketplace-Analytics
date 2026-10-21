"""``run_task`` must leave a pool the NEXT task can use.

This is the behavioural half of the guard whose static half lives in
``tests/unit/core/test_task_loop_hygiene.py``. That one proves no task calls
``asyncio.run`` directly; this one proves that routing through ``run_task``
actually fixes the thing the direct call broke.

It needs a real PostgreSQL and a real *pooled* engine, which is why it cannot go
lower in the pyramid: the whole failure lives in the interaction between
asyncpg's loop-bound connections and SQLAlchemy's pool. A fake pool would hand
back a fake connection and prove nothing.

Note the deliberate departure from ``conftest.engine``, which uses ``NullPool``
precisely to dodge this hazard in the test fixtures. Pooling is the mechanism
under test here, so these tests build their own pooled engine.
"""

from __future__ import annotations

import asyncio

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from sqlalchemy.pool import NullPool

import src.core.database as database_module
from src.core.tasks import run_task
from tests.integration.conftest import TEST_DB_NAME, _dsn

pytestmark = pytest.mark.usefixtures("postgres_ready")


@pytest.fixture
def pooled_engine() -> AsyncEngine:
    """A *pooled* engine standing in for the process-wide application engine.

    ``pool_size=1`` makes the failure deterministic rather than probabilistic:
    with a single slot, the second run is guaranteed to be handed back the very
    connection the first run left behind.
    """
    return create_async_engine(_dsn(TEST_DB_NAME), pool_size=1, max_overflow=0)


async def _touch_database() -> int:
    """One trivial query, enough to pull a connection into the pool.

    Returns the *server-side* backend PID rather than a constant, so a test can
    clean up the exact connection it stranded. See :func:`_terminate`.
    """
    async with database_module.AsyncSessionLocal() as session:
        return int((await session.execute(sa.text("SELECT pg_backend_pid()"))).scalar_one())


def _terminate(pid: int) -> None:
    """Kill a stranded backend, by PID, from a connection of its own.

    The negative-control test below deliberately abandons a connection mid
    transaction — that is the bug it reproduces. PostgreSQL keeps that backend
    alive and ``pg_stat_activity`` reports it as ``idle in transaction``, which
    is precisely the symptom
    ``core/test_request_unit_of_work.py::test_no_connection_is_left_idle_in_transaction``
    scans the whole database for. Left behind, this file would fail that test
    from two directories away, and only when the two run in the same session.

    Terminating by exact PID rather than sweeping all idle-in-transaction
    backends keeps the cleanup from ever reaching into a fixture that is
    legitimately holding a transaction open.
    """
    admin = create_async_engine(_dsn(TEST_DB_NAME), poolclass=NullPool)

    async def _kill() -> None:
        try:
            async with admin.connect() as conn:
                await conn.execute(sa.text("SELECT pg_terminate_backend(:pid)"), {"pid": pid})
        finally:
            await admin.dispose()

    asyncio.run(_kill())


@pytest.fixture
def app_engine_is(pooled_engine: AsyncEngine, monkeypatch: pytest.MonkeyPatch) -> AsyncEngine:
    """Point the module-level engine AND session factory at the pooled engine.

    ``run_task`` disposes the engine through ``dispose_engine``, which reads
    ``src.core.database.engine`` by global lookup, so patching the attribute is
    what makes the real code path observable here.
    """
    monkeypatch.setattr(database_module, "engine", pooled_engine)
    monkeypatch.setattr(
        database_module,
        "AsyncSessionLocal",
        sa.orm.sessionmaker(  # type: ignore[call-overload]
            bind=pooled_engine,
            class_=database_module.AsyncSession,
            expire_on_commit=False,
        ),
    )
    return pooled_engine


def test_a_bare_asyncio_run_poisons_the_pool_for_the_next_task(
    app_engine_is: AsyncEngine,
) -> None:
    """The negative control: reproduce the 2026-07-27 harvest failure exactly.

    Two tasks, each with its own ``asyncio.run``, sharing one pooled engine and
    no disposal between them — which is what a nightly finreports task
    (05:00 MSK) and ``monitoring.harvest_all`` (06:00 MSK) were. The second dies
    on its first query, having harvested nothing.

    Without this test the positive one below could pass for the wrong reason —
    e.g. if the pool quietly stopped reusing connections, ``run_task`` would
    look correct while doing nothing.
    """
    stranded_pid = asyncio.run(_touch_database())  # the leaker: no dispose
    try:
        with pytest.raises(RuntimeError) as caught:
            asyncio.run(_touch_database())

        message = str(caught.value)
        assert "attached to a different loop" in message or "Event loop is closed" in message, (
            f"expected the cross-loop failure, got: {message}"
        )
    finally:
        # Order matters: drop the pool's reference first, then kill the backend
        # the pool can no longer reach.
        asyncio.run(app_engine_is.dispose())
        _terminate(stranded_pid)


def test_run_task_leaves_a_pool_the_next_task_can_use(app_engine_is: AsyncEngine) -> None:
    """The fix: consecutive tasks both succeed, because each drains on the way out.

    Three in a row, not two — a dispose that only worked once would still pass a
    two-call test, and beat runs five tasks through one worker every night.
    """
    assert run_task(_touch_database()) > 0
    assert run_task(_touch_database()) > 0
    assert run_task(_touch_database()) > 0


def test_run_task_drains_the_pool_even_when_the_task_fails(
    app_engine_is: AsyncEngine,
) -> None:
    """A crashing task must not poison its successor either.

    This is the ordering that actually happened: ``harvest_all`` raised, and the
    07:00 cohort task ran fine *because* the dispose in the ``finally`` had
    scrubbed the pool anyway. That accident is what made the bug look like a
    random nightly flake instead of a deterministic one — so it is worth
    holding on purpose.
    """

    async def _boom() -> None:
        await _touch_database()
        raise ValueError("task exploded after touching the database")

    with pytest.raises(ValueError, match="task exploded"):
        run_task(_boom())

    assert run_task(_touch_database()) > 0
