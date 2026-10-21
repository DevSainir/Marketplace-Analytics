"""Nothing bound to an event loop may be held for the life of the process.

A worker process runs task after task, each on a fresh ``asyncio.run`` loop. An
``asyncio`` primitive — ``Lock``, ``Semaphore``, ``Event``, ``Condition``,
``Queue`` — binds itself to the first loop that waits on it, so one created at
import time serves the first task that contends and raises ``… is bound to a
different event loop`` in every later one. The same goes for a Redis client
captured into a process-wide cache: its pool carries such a lock.

It never shows up where it was written. A Redis pool's lock, bound by a finance
tick, can cost the monitoring harvest its prices — and only in a process where
the finance tick happened to contend first, so it looks like a random flake. A
rule over the source is the only check that holds for code not written yet;
``test_redis_client_per_loop.py`` and the integration tier cover the Redis
client's own behaviour.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

#: Repository-relative root of the application package.
_SRC = Path(__file__).resolve().parents[3] / "src"

#: ``asyncio`` types that bind to the loop that first waits on them.
_LOOP_BOUND = frozenset(
    {"Lock", "Semaphore", "BoundedSemaphore", "Event", "Condition", "Queue", "Barrier"}
)

#: Decorators that keep a function's result for the life of the process.
_PROCESS_CACHES = frozenset({"lru_cache", "cache"})


def _python_files() -> list[Path]:
    return sorted(_SRC.rglob("*.py"))


def _builds_loop_bound_primitive(node: ast.AST) -> bool:
    """Whether ``node`` is a call such as ``asyncio.Semaphore(2)``."""
    if not isinstance(node, ast.Call):
        return False
    func = node.func
    return (
        isinstance(func, ast.Attribute)
        and isinstance(func.value, ast.Name)
        and func.value.id == "asyncio"
        and func.attr in _LOOP_BOUND
    )


def _decorator_name(decorator: ast.expr) -> str | None:
    target = decorator.func if isinstance(decorator, ast.Call) else decorator
    if isinstance(target, ast.Attribute):
        return target.attr
    if isinstance(target, ast.Name):
        return target.id
    return None


def test_no_asyncio_primitive_is_created_at_import_time() -> None:
    """A module-level ``asyncio.Lock``/``Semaphore``/… would outlive the task's loop.

    Build it inside the coroutine that uses it, or keep one per running loop.
    """
    offenders: list[str] = []
    for path in _python_files():
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for statement in tree.body:
            if not isinstance(statement, (ast.Assign, ast.AnnAssign)):
                continue
            if statement.value is not None and any(
                _builds_loop_bound_primitive(node) for node in ast.walk(statement.value)
            ):
                offenders.append(f"{path.relative_to(_SRC)}:{statement.lineno}")

    assert offenders == [], (
        f"{offenders} create an asyncio primitive at import time. It binds to the "
        "first event loop that waits on it and breaks every later Celery task in "
        "the same worker process."
    )


def test_no_process_wide_cache_holds_a_redis_client() -> None:
    """``@lru_cache`` around ``get_redis()`` would freeze one loop's client forever.

    ``get_redis()`` hands each loop its own client; caching the result pins
    whichever loop called first, which is the bug the accessor exists to stop.
    """
    offenders: list[str] = []
    for path in _python_files():
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            if not any(_decorator_name(d) in _PROCESS_CACHES for d in node.decorator_list):
                continue
            calls_accessor = any(
                isinstance(inner, ast.Call)
                and isinstance(inner.func, ast.Name)
                and inner.func.id == "get_redis"
                for inner in ast.walk(node)
            )
            if calls_accessor:
                offenders.append(f"{path.relative_to(_SRC)}:{node.name}")

    assert offenders == [], (
        f"{offenders} cache a Redis client for the life of the process. Build the "
        "holder per call — it is cheap — so every call resolves `get_redis()` anew."
    )
