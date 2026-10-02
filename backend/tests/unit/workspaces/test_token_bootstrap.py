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
    ADVERTISING_BACKFILL_TASK_NAME,
    CATALOGUE_BACKFILL_TASK_NAME,
    DISCOVERY_TASK_NAME,
    FINANCE_TASK_NAME,
    FUNNEL_BACKFILL_TASK_NAME,
    HARVEST_SURFACES,
    PNL_BACKFILL_TASK_NAME,
    enqueue_catalogue_bootstrap,
    newly_reachable,
)
from src.modules.workspaces.models import BackfillLane, TokenKind
from tests.support.fakes import FakeRedis


def test_every_bootstrap_task_name_resolves_to_a_registered_task() -> None:
    """Both names in ``bootstrap.py`` must resolve to registered Celery tasks.

    Importing the task packages is what registers them, and is exactly what the
    worker does at startup — so this asserts the same condition the worker
    would, without needing one.
    """
    import src.modules.finreports.tasks
    import src.modules.monitoring.tasks  # noqa: F401  (import registers the tasks)

    for name in (
        DISCOVERY_TASK_NAME,
        FINANCE_TASK_NAME,
        CATALOGUE_BACKFILL_TASK_NAME,
        FUNNEL_BACKFILL_TASK_NAME,
        ADVERTISING_BACKFILL_TASK_NAME,
        PNL_BACKFILL_TASK_NAME,
    ):
        assert name in celery_app.tasks


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


@pytest.fixture(autouse=True)
def seeded(monkeypatch: pytest.MonkeyPatch) -> list[tuple[BackfillLane, ...]]:
    """Record the lane seeding instead of writing it — this tier has no DB.

    What was seeded is recorded because WHICH lanes a save resets is the
    decision under test: a lane reset is a lane walked again from scratch.
    """
    calls: list[tuple[BackfillLane, ...]] = []

    async def _record(_: uuid.UUID, *, lanes: tuple[BackfillLane, ...]) -> None:
        calls.append(lanes)

    monkeypatch.setattr("src.modules.workspaces.bootstrap.start_backfill", _record)
    return calls


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
                "countdown": options.get("countdown", 0),
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

    first = await enqueue_catalogue_bootstrap(workspace_id, HARVEST_SURFACES)
    second = await enqueue_catalogue_bootstrap(workspace_id, HARVEST_SURFACES)

    assert first is not None
    assert second is None
    # One DISCOVERY send, not one send: the finance walk rides on its callback,
    # while the two backfill lanes are separate delayed sends of their own.
    discoveries = [c for c in enqueued if c["name"] == DISCOVERY_TASK_NAME]
    assert [c["workspace_id"] for c in discoveries] == [str(workspace_id)]


async def test_the_claim_is_per_workspace(redis: FakeRedis, enqueued: list[str]) -> None:
    """One tenant's bootstrap must not swallow another's.

    A debounce keyed on anything coarser — a global flag, or the API process —
    would silently drop the second seller's harvest during a busy onboarding,
    and the symptom would be indistinguishable from the bug this whole feature
    exists to fix.
    """
    one, two = uuid.uuid4(), uuid.uuid4()

    await enqueue_catalogue_bootstrap(one, HARVEST_SURFACES)
    await enqueue_catalogue_bootstrap(two, HARVEST_SURFACES)

    discoveries = [c for c in enqueued if c["name"] == DISCOVERY_TASK_NAME]
    assert [c["workspace_id"] for c in discoveries] == [str(one), str(two)]


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

    assert await enqueue_catalogue_bootstrap(uuid.uuid4(), HARVEST_SURFACES) is None
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

    await enqueue_catalogue_bootstrap(workspace_id, HARVEST_SURFACES)

    (call,) = [c for c in enqueued if c["name"] == DISCOVERY_TASK_NAME]
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
    await enqueue_catalogue_bootstrap(uuid.uuid4(), HARVEST_SURFACES)

    (call,) = [c for c in enqueued if c["name"] == DISCOVERY_TASK_NAME]
    assert call["link_error"].task == FINANCE_TASK_NAME
    assert call["link_error"].kwargs == call["link"].kwargs


async def test_the_history_backfill_is_queued_behind_the_first_harvests(
    redis: FakeRedis, enqueued: list[dict[str, Any]]
) -> None:
    """Both backfill lanes are enqueued, and none of them starts immediately.

    The delay is the point, not a detail. The two first-run harvests chained
    above share the worker's 768 MB cgroup, and starting a third walk in the
    same second is what OOM-killed the finance child on 2026-09-07. A backfill
    that has hours of work ahead can afford to wait for them.
    """
    workspace_id = uuid.uuid4()

    await enqueue_catalogue_bootstrap(workspace_id, HARVEST_SURFACES)

    backfills = {
        c["name"]: c
        for c in enqueued
        if c["name"] in (CATALOGUE_BACKFILL_TASK_NAME, PNL_BACKFILL_TASK_NAME)
    }
    assert set(backfills) == {CATALOGUE_BACKFILL_TASK_NAME, PNL_BACKFILL_TASK_NAME}
    for call in backfills.values():
        assert call["workspace_id"] == str(workspace_id)
        assert call["countdown"] > 0


async def test_a_broker_failure_costs_the_backfill_but_not_the_token(
    redis: FakeRedis, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A dead broker must not turn a saved token into a failed request.

    The seller's actual ask is "store my credential". Everything this module
    enqueues is a courtesy attached to it, so an enqueue that explodes has to
    come back as ``None`` — the scheduled passes remain the backstop.
    """

    def _explode(*_: Any, **__: Any) -> Any:
        raise RuntimeError("broker is gone")

    monkeypatch.setattr("src.modules.workspaces.bootstrap.celery_app.send_task", _explode)

    assert await enqueue_catalogue_bootstrap(uuid.uuid4(), HARVEST_SURFACES) is None


def test_a_feedback_token_reaches_nothing_the_bootstrap_reads() -> None:
    """«Вопросы и отзывы» feeds no harvest and no lane.

    Added to «Демо» on 2026-10-02, it reset all four lanes and re-walked
    the whole history for rows the кабинет already held.
    """
    assert newly_reachable(["content", "finance"], ["content", "finance", "feedback"]) == set()


def test_a_category_token_beside_unified_reaches_nothing_new() -> None:
    """``unified`` already stands in for every surface, so nothing is unlocked."""
    assert newly_reachable(["unified"], ["unified", "finance"]) == set()


def test_unified_reaches_only_what_the_category_tokens_did_not() -> None:
    reached = newly_reachable(["content", "analytics"], ["content", "analytics", "unified"])

    assert TokenKind.FINANCE in reached
    assert TokenKind.CONTENT not in reached


async def test_a_surface_nothing_reads_enqueues_nothing_and_resets_no_lane(
    redis: FakeRedis,
    enqueued: list[dict[str, Any]],
    seeded: list[tuple[BackfillLane, ...]],
) -> None:
    """Defence in depth behind the router's filter: the helper filters too."""
    result = await enqueue_catalogue_bootstrap(uuid.uuid4(), {TokenKind.FEEDBACK})

    assert result is None
    assert enqueued == []
    assert seeded == []


async def test_a_finance_token_walks_the_p_and_l_and_nothing_else(
    redis: FakeRedis,
    enqueued: list[dict[str, Any]],
    seeded: list[tuple[BackfillLane, ...]],
) -> None:
    """Only the lane the new surface feeds is reset; the others keep their history."""
    await enqueue_catalogue_bootstrap(uuid.uuid4(), {TokenKind.FINANCE})

    assert seeded == [(BackfillLane.PNL,)]
    backfills = [c["name"] for c in enqueued if c["name"] != DISCOVERY_TASK_NAME]
    assert backfills == [PNL_BACKFILL_TASK_NAME]


async def test_a_promotion_token_starts_the_advertising_lane_without_the_catalogue(
    redis: FakeRedis,
    enqueued: list[dict[str, Any]],
    seeded: list[tuple[BackfillLane, ...]],
) -> None:
    """The catalogue lane would start funnel and advertising both — so it is
    not the way in when only advertising has something new to read."""
    await enqueue_catalogue_bootstrap(uuid.uuid4(), {TokenKind.PROMOTION})

    assert seeded == [(BackfillLane.ADVERTISING,)]
    backfills = [c["name"] for c in enqueued if c["name"] != DISCOVERY_TASK_NAME]
    assert backfills == [ADVERTISING_BACKFILL_TASK_NAME]


async def test_a_second_surface_inside_the_debounce_still_gets_its_lane(
    redis: FakeRedis,
    enqueued: list[dict[str, Any]],
    seeded: list[tuple[BackfillLane, ...]],
) -> None:
    """The claim is per lane: «Аналитика» saved, then «Финансы» five minutes
    later, must not lose the P&L walk to the first save's claim."""
    workspace_id = uuid.uuid4()

    await enqueue_catalogue_bootstrap(workspace_id, {TokenKind.ANALYTICS})
    await enqueue_catalogue_bootstrap(workspace_id, {TokenKind.FINANCE})

    assert seeded == [(BackfillLane.FUNNEL,), (BackfillLane.PNL,)]
    names = [c["name"] for c in enqueued]
    assert names.count(DISCOVERY_TASK_NAME) == 1
    assert names.count(PNL_BACKFILL_TASK_NAME) == 1
