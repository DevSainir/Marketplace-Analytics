"""The one string in the token-bootstrap path that no type checker can follow.

``workspaces.bootstrap`` addresses the discovery task by its registered name
rather than importing it, because ``workspaces.contract`` imports
``workspaces.services`` and ``monitoring.contract`` imports
``monitoring.services`` which imports ``workspaces.contract`` — a direct import
would close that cycle.

The price is a string. Renaming ``monitoring.discover_workspace`` without
touching ``bootstrap.py`` would leave a token save silently enqueueing a task
that no worker answers: no exception, no failed request, and a seller waiting
for a harvest that will never run until the nightly pass. This test is what
turns that into a red build.
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest

from src.core.celery_app import celery_app
from src.modules.workspaces.bootstrap import (
    DISCOVERY_TASK_NAME,
    FINANCE_TASK_NAME,
    enqueue_catalogue_bootstrap,
)
from tests.support.fakes import FakeRedis


def test_every_bootstrap_task_name_resolves_to_a_registered_task() -> None:
    """Both names in ``bootstrap.py`` must resolve to registered Celery tasks.

    Importing the task packages is what registers them, and is exactly what the
    worker does at startup — so this asserts the same condition the worker
    would, without needing one.
    """
    import src.modules.finreports.tasks
    import src.modules.monitoring.tasks  # noqa: F401  (import registers the tasks)

    assert DISCOVERY_TASK_NAME in celery_app.tasks
    assert FINANCE_TASK_NAME in celery_app.tasks


def test_both_bootstrap_tasks_accept_the_keyword_the_bootstrap_sends() -> None:
    """``send_task`` cannot type-check its kwargs, so pin the parameter name.

    The bootstrap sends ``workspace_id`` as a string to both tasks. One that
    renamed the parameter would fail inside the worker — far from the change
    that broke it, and only for real sellers, since nothing enqueues these
    tasks in a test run.
    """
    from src.modules.finreports.tasks import harvest_finance
    from src.modules.monitoring.tasks import discover_workspace

    for task in (discover_workspace, harvest_finance):
        assert "workspace_id" in task.__wrapped__.__code__.co_varnames


@pytest.fixture
def redis(monkeypatch: pytest.MonkeyPatch) -> FakeRedis:
    """Back the debounce with the shared in-memory Redis fake."""
    fake = FakeRedis()
    monkeypatch.setattr("src.modules.workspaces.bootstrap.get_redis", lambda: fake)
    return fake


@pytest.fixture
def enqueued(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    """Capture what was handed to Celery, without a broker.

    One entry per ``send_task``, carrying the task name, the workspace id and
    the callbacks — the chain lives in those, so a fixture that dropped them
    could not tell "sent behind discovery" from "not sent at all".
    """
    calls: list[dict[str, Any]] = []

    def _send_task(name: str, kwargs: dict[str, Any] | None = None, **options: Any) -> Any:
        calls.append(
            {
                "name": name,
                "workspace_id": (kwargs or {})["workspace_id"],
                "link": options.get("link"),
                "link_error": options.get("link_error"),
            }
        )
        return type("Task", (), {"id": f"task-{len(calls)}"})()

    monkeypatch.setattr("src.modules.workspaces.bootstrap.celery_app.send_task", _send_task)
    return calls


async def test_a_burst_of_saves_costs_one_harvest(redis: FakeRedis, enqueued: list[str]) -> None:
    """The debounce, which is the only thing standing between a settings form
    and thirteen concurrent catalogue harvests.

    A primary workspace holds thirteen token kinds. An owner pasting them one
    at a time saves the form repeatedly, each save legitimately adding a kind
    that was not there before — so the "newly configured" check in the router
    does NOT cover this, and every one of those saves would otherwise enqueue a
    full harvest racing the others for WB's shared rate budget.
    """
    workspace_id = uuid.uuid4()

    first = await enqueue_catalogue_bootstrap(workspace_id)
    second = await enqueue_catalogue_bootstrap(workspace_id)

    assert first is not None
    assert second is None
    # One send: the finance walk rides on the discovery task's callback.
    assert [call["workspace_id"] for call in enqueued] == [str(workspace_id)]


async def test_the_claim_is_per_workspace(redis: FakeRedis, enqueued: list[str]) -> None:
    """One tenant's bootstrap must not swallow another's.

    A debounce keyed on anything coarser — a global flag, or the API process —
    would silently drop the second seller's harvest during a busy onboarding,
    and the symptom would be indistinguishable from the bug this whole feature
    exists to fix.
    """
    one, two = uuid.uuid4(), uuid.uuid4()

    await enqueue_catalogue_bootstrap(one)
    await enqueue_catalogue_bootstrap(two)

    assert [call["workspace_id"] for call in enqueued] == [str(one), str(two)]


async def test_a_redis_that_is_gone_neither_raises_nor_enqueues(
    monkeypatch: pytest.MonkeyPatch, enqueued: list[str]
) -> None:
    """Celery's broker IS this Redis, so a claim that cannot be written means
    the enqueue below it cannot succeed either.

    Returning ``None`` quietly is the honest outcome: the caller's token is
    stored, and the nightly harvest remains the backstop.
    """
    from redis.exceptions import RedisError

    class _DeadRedis:
        async def set(self, *_: Any, **__: Any) -> bool:
            raise RedisError("connection refused")

    monkeypatch.setattr("src.modules.workspaces.bootstrap.get_redis", lambda: _DeadRedis())

    assert await enqueue_catalogue_bootstrap(uuid.uuid4()) is None
    assert enqueued == []


async def test_the_finance_walk_waits_for_discovery_to_finish(
    redis: FakeRedis, enqueued: list[dict[str, Any]]
) -> None:
    """The two first-run harvests must not be in flight at the same time.

    Started together they were, and the worker's 768 MB cgroup — sized for one
    harvest at a time — had the kernel OOM-kill the finance child on the first
    outside signup (2026-09-07). Celery does not retry a ``WorkerLostError``,
    so the workspace kept a full catalogue and an empty P&L.

    The chain is what prevents it, and the callback carries the workspace id:
    a signature built without it would run the finance walk over every tenant.
    """
    workspace_id = uuid.uuid4()

    await enqueue_catalogue_bootstrap(workspace_id)

    (call,) = enqueued
    assert call["name"] == DISCOVERY_TASK_NAME
    assert call["link"].task == FINANCE_TASK_NAME
    assert call["link"].kwargs == {"workspace_id": str(workspace_id)}
    # Immutable, or discovery's returned row counts arrive as the finance
    # task's first positional argument and it fails on an unexpected argument.
    assert call["link"].immutable


async def test_a_failed_discovery_still_leaves_the_seller_a_p_and_l(
    redis: FakeRedis, enqueued: list[dict[str, Any]]
) -> None:
    """``link`` alone would make the finance walk hostage to the other one.

    Discovery walks WB's advertising and analytics surfaces; the finance walk
    reads the statistics host and needs nothing discovery produces. A WB outage
    on one must not cost the seller the other, so the same signature is
    attached to both outcomes — Celery fires exactly one of them.
    """
    await enqueue_catalogue_bootstrap(uuid.uuid4())

    (call,) = enqueued
    assert call["link_error"].task == FINANCE_TASK_NAME
    assert call["link_error"].kwargs == call["link"].kwargs
