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
from src.modules.workspaces.bootstrap import DISCOVERY_TASK_NAME, enqueue_catalogue_bootstrap
from tests.support.fakes import FakeRedis


def test_the_bootstrap_addresses_a_task_that_actually_exists() -> None:
    """The name in ``bootstrap.py`` must resolve to a registered Celery task.

    Importing the monitoring task package is what registers it, and is exactly
    what the worker does at startup — so this asserts the same condition the
    worker would, without needing one.
    """
    import src.modules.monitoring.tasks  # noqa: F401  (import registers the tasks)

    assert DISCOVERY_TASK_NAME in celery_app.tasks


def test_the_discovery_task_accepts_the_keyword_the_bootstrap_sends() -> None:
    """``send_task`` cannot type-check its kwargs, so pin the parameter name.

    The bootstrap sends ``workspace_id`` as a string. A task that renamed the
    parameter would fail inside the worker — far from the change that broke it,
    and only for real sellers, since nothing enqueues this task in a test run.
    """
    from src.modules.monitoring.tasks import discover_workspace

    parameters = discover_workspace.__wrapped__.__code__.co_varnames
    assert "workspace_id" in parameters


@pytest.fixture
def redis(monkeypatch: pytest.MonkeyPatch) -> FakeRedis:
    """Back the debounce with the shared in-memory Redis fake."""
    fake = FakeRedis()
    monkeypatch.setattr("src.modules.workspaces.bootstrap.get_redis", lambda: fake)
    return fake


@pytest.fixture
def enqueued(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Capture the workspace ids handed to Celery, without a broker."""
    calls: list[str] = []

    def _send_task(name: str, kwargs: dict[str, Any] | None = None, **_: Any) -> Any:
        calls.append((kwargs or {})["workspace_id"])
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
    assert enqueued == [str(workspace_id)]


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

    assert enqueued == [str(one), str(two)]


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
