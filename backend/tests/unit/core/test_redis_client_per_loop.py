"""No Redis client is ever shared by two event loops.

A Celery worker process runs many tasks, each on its own ``asyncio.run`` loop.
``redis.asyncio`` pools are loop-bound in two ways: each pooled socket belongs to
the loop that opened it, and the pool's own ``asyncio.Lock`` binds itself to the
first loop that ever has to *wait* on it. Draining the sockets at a task boundary
(``drain_redis_pool``) fixes the first and leaves the second: once one task makes
two Redis calls at the same instant, every later task in that process that does
the same dies with ``<asyncio.locks.Lock …> is bound to a different event loop``.

That is how a workspace can lose its whole price snapshot for a day: the morning
harvest's ``prices``, ``adverts-v2`` and ``ad-write-offs`` sources reach their
rate buckets together, in a process an earlier finance tick has already bound.

So the accessor itself hands every loop its own client. These tests hold that
without a network — building a client opens no connection — and the live-Redis
half, with the concurrency that actually failed, is
``tests/integration/celery/test_redis_loop_isolation.py``.
"""

from __future__ import annotations

import asyncio

import pytest

from src.core import redis as core_redis
from src.core.redis import get_redis

pytestmark = pytest.mark.unit


async def _client_seen_inside_a_loop() -> object:
    """Whatever ``get_redis()`` hands code running on the current loop."""
    return get_redis()


def test_each_event_loop_gets_its_own_client() -> None:
    """Two tasks — two ``asyncio.run`` loops — never share one client.

    A shared client means a shared pool, and a shared pool means a lock that
    serves only whichever loop contended on it first.
    """
    first_task = asyncio.run(_client_seen_inside_a_loop())

    second_task = asyncio.run(_client_seen_inside_a_loop())

    assert second_task is not first_task


def test_one_loop_keeps_one_client() -> None:
    """Within one loop every caller gets the same client, so one pool serves it.

    Per-loop, not per-call: a client per call would open a connection per
    command and defeat the pool entirely.
    """

    async def _twice() -> tuple[object, object]:
        return get_redis(), get_redis()

    first, second = asyncio.run(_twice())

    assert first is second


def test_a_client_swapped_in_by_a_test_is_served_on_every_loop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Replacing ``src.core.redis._redis`` still redirects every caller, on any loop.

    The component tier's ``redis_store`` and the users tier's fixture rely on
    that one seam; a per-loop client that ignored it would send those tests to a
    live Redis they are forbidden to reach.
    """
    swapped_in = object()
    monkeypatch.setattr(core_redis, "_redis", swapped_in)

    seen = [asyncio.run(_client_seen_inside_a_loop()) for _ in range(2)]

    assert seen == [swapped_in, swapped_in]
