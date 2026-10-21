"""Every Celery task must drive its async body through ``run_task``.

The bug this exists to prevent, in full, because the failure is invisible in the
task that causes it:

The async engine is process-wide, but each Celery task runs its own
``asyncio.run`` — its own event loop, created and destroyed inside one task.
asyncpg connections stay bound to the loop that opened them. So a task that
returns while leaving connections in the shared pool hands the *next* task in
that worker process a connection whose transport belongs to a loop that no
longer exists. The next task dies on its first query with ``got Future attached
to a different loop``, having done nothing.

MSK) leaks, ``monitoring.harvest_all`` (06:00 MSK) is the one that crashes — so a
whole day harvests zero rows while the task at fault is recorded as a success.
The victim's own ``dispose()`` in its ``finally`` then scrubs the pool, so the
07:00 task runs fine, and the damage looks like a random nightly flake rather
than a deterministic ordering bug.

Five of the six tasks had hand-rolled the ``try/finally: await
engine.dispose()`` correctly. The sixth had not, and nothing said so. That is
why this is a lint-shaped test rather than a behavioural one: the invariant has
to hold for tasks nobody has written yet, and a reviewer cannot be the check.

The behavioural half — that ``run_task`` really does leave a reusable pool
behind — needs a live PostgreSQL and lives in
``tests/integration/celery/test_task_loop_isolation.py``.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

#: Repository-relative root of the application package.
_SRC = Path(__file__).resolve().parents[3] / "src"


def _task_modules() -> list[Path]:
    """Every module that may define Celery tasks.

    Matches both layouts in the tree: a module-level ``tasks.py`` (users) and a
    ``tasks/`` package (monitoring, finreports).
    """
    return sorted({*_SRC.glob("modules/*/tasks.py"), *_SRC.glob("modules/*/tasks/*.py")})


def _is_celery_task(node: ast.FunctionDef) -> bool:
    """Whether ``node`` carries a ``@celery_app.task(...)`` decorator."""
    for decorator in node.decorator_list:
        target = decorator.func if isinstance(decorator, ast.Call) else decorator
        if isinstance(target, ast.Attribute) and target.attr == "task":
            return True
    return False


def _calls_asyncio_run(node: ast.FunctionDef) -> bool:
    """Whether ``node``'s body calls ``asyncio.run`` anywhere, nested included."""
    return any(
        isinstance(inner, ast.Call)
        and isinstance(inner.func, ast.Attribute)
        and inner.func.attr == "run"
        and isinstance(inner.func.value, ast.Name)
        and inner.func.value.id == "asyncio"
        for inner in ast.walk(node)
    )


def _celery_tasks() -> list[tuple[str, ast.FunctionDef]]:
    """Collect ``(dotted_location, function_node)`` for every Celery task."""
    found: list[tuple[str, ast.FunctionDef]] = []
    for path in _task_modules():
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and _is_celery_task(node):
                found.append((f"{path.relative_to(_SRC)}::{node.name}", node))
    return found


def test_the_sweep_actually_finds_the_tasks() -> None:
    """Guard the guard: a glob that matches nothing would pass every test below."""
    names = [name for name, _ in _celery_tasks()]

    assert len(names) >= 6, f"expected the known task set, found {names}"
    assert any("harvest_all" in name for name in names)


@pytest.mark.parametrize(
    ("location", "node"),
    _celery_tasks(),
    ids=[name for name, _ in _celery_tasks()],
)
def test_no_task_drives_its_own_event_loop(location: str, node: ast.FunctionDef) -> None:
    """A task calling ``asyncio.run`` directly can strand pooled connections.

    Route the coroutine through ``src.core.tasks.run_task`` instead: it owns the
    loop and drains both the engine's and Redis's pools in a ``finally``, so the
    next task in the worker process starts against clean pools.
    """
    assert not _calls_asyncio_run(node), (
        f"{location} calls asyncio.run directly. Use run_task(...) from "
        f"src.core.tasks — otherwise this task can leave asyncpg/redis connections "
        f"bound to its dead event loop and the NEXT scheduled task fails on its "
        f"first query with 'got Future attached to a different loop'."
    )
