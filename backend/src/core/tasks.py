"""The Celery task-boundary runtime: one loop per task, both pools drained.

Every Celery task is a synchronous function that drives its async body through
its own :func:`asyncio.run` — its own short-lived event loop. Two process-wide
resources pool connections that outlive that loop: the SQLAlchemy engine
(:mod:`src.core.database`) and the Redis client (:mod:`src.core.redis`).
:func:`run_task` owns that boundary and drains both on the way out, so neither
module has to know about the other — the orchestration lives here, one level up.
"""

from __future__ import annotations

import asyncio
from collections.abc import Coroutine

from src.core.database import dispose_engine
from src.core.logcontext import reset_context
from src.core.redis import drain_redis_pool


def run_task[T](coro: Coroutine[object, object, T]) -> T:
    """Run one Celery task's async body on a private loop, then drain the pools.

    Every Celery task is a synchronous function that drives async code through
    its own :func:`asyncio.run`, i.e. its own short-lived event loop. Both the
    SQLAlchemy engine AND the process-wide Redis client, however, pool
    connections that stay bound to the loop that opened them. So a task that
    returns while leaving a connection in either pool hands the *next* task a
    socket whose transport belongs to a loop that no longer exists — and that
    task dies on its very first query with ``got Future attached to a different
    loop`` / ``Event loop is closed``, before doing any work.

    That is not hypothetical, on either pool. A nightly finreports task
    (05:00 MSK) leaked an asyncpg connection this way and killed
    ``monitoring.harvest_all`` (06:00 MSK) at its first statement, so 2026-07-27
    harvested nothing at all. And the Redis pool did the quieter version of the
    same thing: the funnel's rate-gate ``acquire`` is the first Redis op in a
    harvest, so every ``harvest_sku_window`` after the worker's first task lost
    its ``sales-funnel`` source to ``Event loop is closed`` — silently, because
    the gate only catches :class:`RedisError` and a failed source is a tolerated
    partial harvest. "Refresh all SKUs" kept reporting success with
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
                await dispose_engine()

    try:
        return asyncio.run(_run())
    finally:
        # A worker reuses its process across tasks, so any log context this task
        # bound would otherwise attribute the NEXT task's lines to this task's
        # tenant. Mis-attributed evidence is worse than none.
        reset_context()
