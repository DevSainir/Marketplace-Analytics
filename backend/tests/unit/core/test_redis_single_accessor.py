"""Every Redis user must resolve the client through ``get_redis()``.

This is an architecture rule with a bruise behind it. The client is a module
global, and callers reach it by *calling* ``get_redis()`` rather than by holding
a reference from import time — which is precisely what makes one swap of
``src.core.redis._redis`` redirect the whole process. A helper that reaches past
the accessor (``await _redis.set(...)``) silently opts out of that swap.

It has cost real time twice, and neither time failed honestly. The replay-grace
store and "log out everywhere" both reached a **live** Redis from the component
tier, which forbids it; what the suite reported was ``Event loop is closed`` and
``got Future attached to a different loop`` from a second event loop, which
describes the symptom and says nothing about the cause.

So the invariant is checked here rather than remembered: the private client is
read in exactly one place, and no other module names it at all.
"""

from __future__ import annotations

import ast
from pathlib import Path

_SRC = Path(__file__).resolve().parents[3] / "src"
_REDIS_MODULE = _SRC / "core" / "redis.py"

#: The one function allowed to read the private client.
_ACCESSOR = "get_redis"


def _python_files() -> list[Path]:
    """Return every source file in ``src/``."""
    return sorted(p for p in _SRC.rglob("*.py") if "__pycache__" not in p.parts)


def _names_in(node: ast.AST) -> set[str]:
    """Return every identifier referenced anywhere under a node."""
    return {child.id for child in ast.walk(node) if isinstance(child, ast.Name)}


def test_only_the_accessor_reads_the_private_client() -> None:
    """Inside ``core/redis.py``, ``_redis`` is read by ``get_redis`` and nobody else.

    A second reader is not a style problem: it is a code path that a test cannot
    redirect, so it reaches a real Redis from a tier that must never touch one.
    """
    tree = ast.parse(_REDIS_MODULE.read_text(encoding="utf-8"))

    offenders = [
        node.name
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)
        and node.name != _ACCESSOR
        and "_redis" in _names_in(node)
    ]

    assert offenders == [], (
        f"{offenders} read `_redis` directly. Call `get_redis()` instead — it is "
        "the single seam every test swaps, and reaching past it makes this code "
        "path unfakeable."
    )


def test_no_other_module_names_the_private_client() -> None:
    """Only ``core/redis.py`` may name ``_redis`` at all.

    Matched as an identifier rather than as text, because ``get_redis`` contains
    the substring and a naive search reports every well-behaved caller as a
    violation — which it did on the first draft of this file.

    Importing the client instead of the accessor would freeze it at import time,
    so a later swap would not reach that module: the same failure by another
    route.
    """
    offenders: list[str] = []
    for path in _python_files():
        if path == _REDIS_MODULE:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        referenced = _names_in(tree) | {
            alias.name
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom)
            for alias in node.names
        }
        if "_redis" in referenced:
            offenders.append(str(path.relative_to(_SRC)))

    assert offenders == [], (
        f"{offenders} name `_redis`. Import and call `get_redis()` instead; the "
        "client is private to src/core/redis.py."
    )


def test_no_other_module_builds_its_own_async_client() -> None:
    """The ASYNC client is CONSTRUCTED once, in ``core/redis.py``, and nowhere else.

    A second one carries its own pool and its own event-loop binding — the exact
    hazard :func:`~src.core.redis.drain_redis_pool` exists to manage — and has no
    seam, so a test cannot redirect it.

    Constructing it is the violation; **importing the type is not**. Several
    modules import ``Redis`` purely to annotate a client they are handed
    (``single_flight(..., redis: Redis)``, ``HarvestControlService(redis=...)``),
    which is the better pattern of the two: injected, so the caller decides, and
    fakeable without patching anything at all. A rule that flagged those would be
    pushing good code towards the accessor for no reason.

    Two Celery tasks build a **sync** ``redis.Redis`` on purpose (``cohorts.py``,
    ``discovery.py``): they hold a lock across a task whose event loop is
    short-lived, and binding the shared async pool to that loop is the failure
    they are avoiding. This rule is about the async client, so it leaves them
    alone.
    """
    offenders: list[str] = []
    for path in _python_files():
        if path == _REDIS_MODULE:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        async_names = {
            alias.asname or alias.name
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom) and node.module == "redis.asyncio"
            for alias in node.names
        }
        if not async_names:
            continue
        builds = any(
            isinstance(node.func, ast.Attribute)
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id in async_names
            and node.func.attr in {"from_url", "from_pool"}
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
        )
        if builds:
            offenders.append(str(path.relative_to(_SRC)))

    assert offenders == [], (
        f"{offenders} construct their own async Redis client. Take one through "
        "`get_redis()`, or accept it as an argument, so the process keeps one "
        "pool and one seam."
    )
