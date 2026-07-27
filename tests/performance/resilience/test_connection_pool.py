"""Pool-exhaustion and frozen-transaction probes.

These reproduce, in miniature, the incident that took the API down: connections
left ``idle in transaction`` accumulated until the pool had nothing left to
hand out, and every request then hung — the browser showed a header with a
blank page behind it, which reads as "the frontend is broken" rather than "the
database pool is gone".

The three properties worth protecting:

* a saturated pool **fails fast** with a timeout instead of hanging forever;
* an abandoned transaction is **reclaimed** by the server-side
  ``idle_in_transaction_session_timeout`` even if application cleanup never runs;
* a burst of cancelled work leaves **no** connection checked out.
"""

from __future__ import annotations

import asyncio

import pytest
import sqlalchemy as sa
from sqlalchemy.exc import TimeoutError as SQLTimeoutError
from sqlalchemy.ext.asyncio import AsyncEngine

pytestmark = pytest.mark.performance


async def test_a_saturated_pool_times_out_instead_of_hanging(
    small_pool_engine: AsyncEngine,
) -> None:
    """The third caller on a two-connection pool is refused, not parked forever.

    An unbounded wait is what turns a slow query into a total outage: every
    request queues behind the pool and nothing ever returns, so health checks
    still pass while the API serves nothing.
    """
    held = [await small_pool_engine.connect().start() for _ in range(2)]
    try:
        with pytest.raises(SQLTimeoutError):
            async with small_pool_engine.connect():
                pass
    finally:
        for connection in held:
            await connection.close()


async def test_the_pool_recovers_once_connections_are_returned(
    small_pool_engine: AsyncEngine,
) -> None:
    """Saturation is transient: releasing a connection unblocks the next caller.

    A pool that stays wedged after the load subsides needs a restart to
    recover, which is what made the original incident last 22 hours.
    """
    first = await small_pool_engine.connect().start()
    second = await small_pool_engine.connect().start()
    await first.close()

    async with small_pool_engine.connect() as connection:
        assert await connection.scalar(sa.text("SELECT 1")) == 1

    await second.close()


async def test_concurrent_demand_beyond_the_pool_is_served_by_queueing(
    small_pool_engine: AsyncEngine,
) -> None:
    """Twenty short queries share two connections without error.

    This is the healthy case the timeout above must not break: bursty traffic
    should queue and drain, not fail.
    """

    async def query() -> int:
        async with small_pool_engine.connect() as connection:
            return await connection.scalar(sa.text("SELECT 1"))

    results = await asyncio.gather(*(query() for _ in range(20)))

    assert results == [1] * 20


async def test_an_abandoned_transaction_is_reclaimed_by_the_server(
    observer_engine: AsyncEngine,
) -> None:
    """A frozen transaction is killed by the server, not held forever.

    The application's own cleanup is shielded and should always run, but a
    process killed mid-transaction cannot run anything. The server-side
    ``idle_in_transaction_session_timeout`` is the backstop that keeps a lost
    connection from holding row locks indefinitely, and this asserts the
    setting is actually applied to the sessions the app opens.
    """
    from src.core.database import engine as app_engine

    async with app_engine.connect() as connection:
        timeout = await connection.scalar(sa.text("SHOW idle_in_transaction_session_timeout"))

    assert timeout not in {"0", "0ms"}, (
        "idle_in_transaction_session_timeout is disabled: an abandoned "
        "transaction would hold its locks and pool slot forever."
    )


async def test_an_open_transaction_is_visible_as_idle_in_transaction(
    small_pool_engine: AsyncEngine, observer_engine: AsyncEngine
) -> None:
    """Confirms the symptom the incident was diagnosed by is observable.

    If this assertion ever stops holding, the runbook's diagnostic query is
    wrong and the next incident takes longer to identify.
    """
    connection = await small_pool_engine.connect().start()
    await connection.execute(sa.text("SELECT 1"))
    try:
        async with observer_engine.connect() as observer:
            idle = await observer.scalar(
                sa.text(
                    "SELECT count(*) FROM pg_stat_activity "
                    "WHERE state = 'idle in transaction' AND datname = current_database()"
                )
            )
        assert idle >= 1
    finally:
        await connection.close()


async def test_cancelled_work_leaves_no_connection_checked_out(
    small_pool_engine: AsyncEngine,
) -> None:
    """After a burst of cancellations the pool is fully available again.

    A client hanging up mid-request cancels the task; if that leaked a
    connection, a few impatient users refreshing a slow page would drain the
    pool in seconds.
    """

    async def cancelled_query() -> None:
        async with small_pool_engine.connect() as connection:
            await connection.execute(sa.text("SELECT pg_sleep(5)"))

    tasks = [asyncio.create_task(cancelled_query()) for _ in range(2)]
    await asyncio.sleep(0.3)
    for task in tasks:
        task.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)

    async with small_pool_engine.connect() as connection:
        assert await connection.scalar(sa.text("SELECT 1")) == 1
