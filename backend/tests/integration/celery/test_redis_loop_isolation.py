"""``run_task`` must leave a Redis pool the NEXT task can use, too.

The sibling ``test_task_loop_isolation.py`` proves this for the SQLAlchemy
engine. The Redis client in :mod:`src.core.redis` is the *other* process-wide
pool a Celery task inherits, and it strands connections across event loops in
exactly the same way — ``redis.asyncio`` binds each pooled socket to the loop
that opened it.

This failure was quieter than the engine's and so more dangerous: the funnel's
rate-gate ``acquire`` is the first Redis op in ``monitoring.harvest_sku_window``,
and the gate catches only :class:`RedisError` — not the ``RuntimeError: Event
loop is closed`` a stranded socket raises. A failed source is a tolerated
partial harvest, so every «Обновить все SKU» after the worker's first task kept
reporting success while persisting ``funnel_rows: 0``. No error, no missing
task, just no data.

Like the engine test this needs a real, *pooled* Redis and drives its own
``asyncio.run`` loops, so it cannot sit lower in the pyramid: the whole failure
lives in the interaction between loop-bound sockets and a reused pool.
"""

from __future__ import annotations

import asyncio
from collections.abc import Iterator

import pytest
from redis.asyncio import Redis

import src.core.redis as redis_module
from src.core.config import settings
from src.core.tasks import run_task
from tests.integration.conftest import TEST_REDIS_DB

#: A single-connection pool makes the leak deterministic rather than
#: probabilistic: with one slot, the second run is guaranteed to be handed back
#: the very socket the first run left bound to its dead loop.
_POOL_KWARGS = {"decode_responses": True, "max_connections": 1}


def _test_redis_url() -> str:
    """The app's Redis DSN pointed at the throwaway test index."""
    return settings.redis_url.rsplit("/", 1)[0] + f"/{TEST_REDIS_DB}"


@pytest.fixture
def pooled_redis() -> Iterator[Redis]:
    """A *pooled* Redis client standing in for the process-wide app client.

    Skips (rather than fails) when Redis is unreachable, matching every other
    integration fixture in this suite.
    """
    client: Redis = Redis.from_url(_test_redis_url(), **_POOL_KWARGS)

    async def _ping() -> None:
        try:
            await client.ping()
            await client.flushdb()
        finally:
            # Drop the probe's connection so the tests below start from an empty
            # pool — otherwise the ping's socket is the one that gets stranded.
            await client.connection_pool.disconnect()

    try:
        asyncio.run(_ping())
    except Exception as exc:  # any connect failure means "skip", like every I/O fixture here
        asyncio.run(client.aclose())
        pytest.skip(
            f"Redis is unreachable ({type(exc).__name__}: {exc}); "
            "start it with `docker compose up -d redis` to run this test."
        )
    yield client
    asyncio.run(client.aclose())


@pytest.fixture
def app_redis_is(pooled_redis: Redis, monkeypatch: pytest.MonkeyPatch) -> Redis:
    """Point the module-level client (and ``get_redis``) at the pooled client.

    ``run_task`` drains ``src.core.redis._redis`` by global lookup, and the code
    under test reaches Redis through ``get_redis()`` — patching both is what
    makes the real code path observable here.
    """
    monkeypatch.setattr(redis_module, "_redis", pooled_redis)
    monkeypatch.setattr(redis_module, "get_redis", lambda: pooled_redis)
    return pooled_redis


async def _touch_redis() -> int:
    """One trivial command, enough to pull a connection into the pool."""
    return int(await redis_module.get_redis().incr("loop-isolation:probe"))


def test_a_bare_asyncio_run_poisons_the_redis_pool_for_the_next_task(
    app_redis_is: Redis,
) -> None:
    """The negative control: reproduce the silent funnel-drop exactly.

    Two tasks, each with its own ``asyncio.run``, sharing one pooled Redis
    client and no drain between them. The second's first command dies on the
    socket the first left bound to a closed loop — which is what happened to the
    funnel's rate-gate ``acquire`` on every harvest after the worker's first.

    Without this the positive test could pass for the wrong reason: if the pool
    quietly stopped reusing connections, the drain would look load-bearing while
    doing nothing.
    """
    assert asyncio.run(_touch_redis()) == 1  # the leaker: no drain

    with pytest.raises(RuntimeError) as caught:
        asyncio.run(_touch_redis())

    assert "Event loop is closed" in str(caught.value), (
        f"expected the cross-loop failure, got: {caught.value}"
    )


def test_run_task_leaves_a_redis_pool_the_next_task_can_use(app_redis_is: Redis) -> None:
    """The fix: consecutive tasks all succeed, because each drains on the way out.

    Three in a row, not two — a drain that only worked once would still pass a
    two-call test, and beat runs many tasks through one worker every night.
    """
    assert run_task(_touch_redis()) == 1
    assert run_task(_touch_redis()) == 2
    assert run_task(_touch_redis()) == 3


def test_run_task_drains_the_redis_pool_even_when_the_task_fails(
    app_redis_is: Redis,
) -> None:
    """A crashing task must not poison its successor's Redis pool either."""

    async def _boom() -> None:
        await _touch_redis()
        raise ValueError("task exploded after touching redis")

    with pytest.raises(ValueError, match="task exploded"):
        run_task(_boom())

    assert run_task(_touch_redis()) == 2
