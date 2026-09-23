"""Component tests for the manual «Обновить» surface (``/v1/finreports/harvest``).

The button exists because the hourly schedule cannot cover every hour: a report
WB publishes at 02:00 waits for the 08:00 tick, and a worker that was down for
its tick waits for the next one. What must never happen is that pressing it
starts a second harvest on top of a running one — the walk paces itself against
a ~1 req/min WB surface, and two of them racing is how the storage claim once
came out covering 70 of 910 days.

So the guard is proved from the transport side here: a click while a harvest is
in flight enqueues nothing at all. That the *task* also refuses to overlap (the
half that actually keeps them apart, since the check above is advisory and can
be raced) is proved in ``tests/unit/finreports/test_harvest_single_flight.py``.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, date, datetime
from typing import Any

import httpx
import pytest

from src.modules.finreports.deps import get_harvest_control_service
from src.modules.finreports.repos import LatestReportHeader
from src.modules.finreports.services import HarvestState
from src.modules.finreports.services.freshness_record import (
    FreshnessOutcome,
    FreshnessVerdict,
)
from src.modules.users.deps import get_user_repo
from src.modules.workspaces.contract import WORKSPACE_HEADER
from src.modules.workspaces.deps import get_workspace_repo
from src.modules.workspaces.models import Workspace
from tests.support.auth import auth_headers
from tests.support.fakes import FakeUserRepository, FakeWorkspaceRepository

SETTLED_THROUGH = date(2026, 8, 9)
LATEST_REPORT = LatestReportHeader(
    report_id=969371534,
    date_from=date(2026, 8, 3),
    date_to=SETTLED_THROUGH,
    harvested_at=datetime(2026, 8, 11, 6, 14, tzinfo=UTC),
)
LAST_CHECK = FreshnessVerdict(
    outcome=FreshnessOutcome.WB_EMPTY,
    checked_at=datetime(2026, 8, 12, 9, 0, tzinfo=UTC),
    probe_from=date(2026, 8, 10),
    probe_to=date(2026, 8, 11),
)


class _StubHarvestControl:
    """Reports a canned harvest state and records who asked."""

    def __init__(self) -> None:
        """Start idle, settled through :data:`SETTLED_THROUGH`."""
        self.running = False
        self.calls: list[dict[str, Any]] = []
        self.latest_report: LatestReportHeader | None = LATEST_REPORT
        self.last_check: FreshnessVerdict | None = LAST_CHECK
        #: Seconds WB's settlement bucket says to wait; 0 means "ask now".
        self.retry_after = 0.0

    async def settlement_retry_after(self, **kwargs: Any) -> float:
        """Echo the canned WB rate-limit wait."""
        self.calls.append(kwargs)
        return self.retry_after

    async def get_state(self, **kwargs: Any) -> HarvestState:
        """Echo the caller's scope back through a canned state."""
        self.calls.append(kwargs)
        return HarvestState(
            running=self.running,
            latest_settled=SETTLED_THROUGH,
            latest_report=self.latest_report,
            last_check=self.last_check,
        )


class _SpyTask:
    """Stands in for ``harvest_finance.delay``, recording every enqueue."""

    def __init__(self) -> None:
        """Start with nothing enqueued."""
        self.enqueued = 0
        self.calls: list[dict[str, Any]] = []

    def delay(self, **kwargs: Any) -> Any:
        """Record an enqueue and hand back a task id."""
        self.enqueued += 1
        self.calls.append(kwargs)
        return type("_Result", (), {"id": "task-42"})()


@pytest.fixture
def control() -> _StubHarvestControl:
    """The stub service the routes are wired to."""
    return _StubHarvestControl()


@pytest.fixture
def task(monkeypatch: pytest.MonkeyPatch) -> _SpyTask:
    """Replace the Celery task at the router, so nothing reaches a broker."""
    spy = _SpyTask()
    monkeypatch.setattr("src.modules.finreports.routers.harvest.harvest_finance", spy)
    return spy


@pytest.fixture(autouse=True)
def tail_task(monkeypatch: pytest.MonkeyPatch) -> _SpyTask:
    """The same, for the provisional daily tail the click also enqueues.

    Autouse, unlike ``task``, because the click enqueues this one whether or not
    the case under test is about it: every POST to the route reaches it. Left
    opt-in, the four cases written before the tail existed went on asking for
    ``task`` alone and drove the REAL Celery task — which passes wherever a
    broker happens to answer and fails in CI, where nothing resolves the name
    ``redis`` from that job. A component test must not depend on either.
    """
    spy = _SpyTask()
    monkeypatch.setattr("src.modules.finreports.routers.harvest.harvest_daily_tail", spy)
    return spy


@pytest.fixture(autouse=True)
def _wire(
    override: Callable[[Any, Any], None],
    user_repo: FakeUserRepository,
    workspace_repo: FakeWorkspaceRepository,
    control: _StubHarvestControl,
) -> None:
    """Wire identity, tenancy and the stub harvest-control service."""
    override(get_user_repo, user_repo)
    override(get_workspace_repo, workspace_repo)
    override(get_harvest_control_service, control)


@pytest.fixture
def headers(user: Any, workspace: Workspace) -> dict[str, str]:
    """Authenticated headers carrying the active workspace."""
    return {**auth_headers(user.id), WORKSPACE_HEADER: str(workspace.id)}


async def test_pressing_refresh_while_idle_enqueues_a_harvest(
    client: httpx.AsyncClient, headers: dict[str, str], task: _SpyTask
) -> None:
    """The whole point of the button: WB published, fetch it now."""
    response = await client.post("/api/v1/finreports/harvest", headers=headers)

    assert response.status_code == 202
    assert response.json()["status"] == "started"
    assert task.enqueued == 1


async def test_the_harvest_is_scoped_to_the_caller_own_workspace(
    client: httpx.AsyncClient,
    headers: dict[str, str],
    task: _SpyTask,
    workspace: Workspace,
) -> None:
    """One tenant's click must not enqueue a walk across every other tenant.

    The button used to enqueue the FLEET harvest: whoever pressed it spent every
    other seller's WB rate budget and held the shared harvest lock for the length
    of a platform-wide walk, so the cost of one click grew with the number of
    customers and was paid by all of them.
    """
    await client.post("/api/v1/finreports/harvest", headers=headers)

    assert task.calls == [{"workspace_id": str(workspace.id), "reconcile": True}]


async def test_the_click_walks_behind_our_coverage_not_only_ahead_of_it(
    client: httpx.AsyncClient,
    headers: dict[str, str],
    task: _SpyTask,
) -> None:
    """The button exists for the case where the schedule already got it wrong.

    Enqueued as an ordinary gated tick, a click answered whatever the hourly
    schedule had just answered — and the moment somebody presses «Обновить» is
    precisely the moment that answer is not to be trusted. On 2026-09-14 the
    click was logged as «settled through 13.09 — nothing newer can exist yet,
    skipping» over a week WB had published that morning.

    ``reconcile`` is what makes the click ignore the gate and re-read the days
    behind our coverage as well as the ones after it.
    """
    await client.post("/api/v1/finreports/harvest", headers=headers)

    assert task.calls[0]["reconcile"] is True


async def test_a_click_inside_wbs_rate_window_answers_instead_of_queueing_a_wait(
    client: httpx.AsyncClient,
    headers: dict[str, str],
    control: _StubHarvestControl,
    task: _SpyTask,
) -> None:
    """WB will not take a settlement request, so nothing is enqueued to wait for it.

    Prod 2026-09-09: a click landed inside the endpoint's ~15-minute window, the
    harvest was enqueued anyway, and its first act was to sit still for 383
    seconds before asking. Seven minutes of «Обновляем…» over a walk that could
    not have done anything sooner. The bucket knew the number before any of that,
    and the wait is worth more to the caller than to the queue.
    """
    control.retry_after = 391.0

    response = await client.post("/api/v1/finreports/harvest", headers=headers)

    assert response.status_code == 202
    assert response.json()["status"] == "rate_limited"
    assert response.json()["retry_after_seconds"] == 391
    assert task.enqueued == 0


async def test_a_running_harvest_is_reported_ahead_of_the_rate_limit(
    client: httpx.AsyncClient,
    headers: dict[str, str],
    control: _StubHarvestControl,
) -> None:
    """The running harvest is usually what emptied the bucket, and it is the better news.

    Both are true at once for most of a run — the walk holds the lock and has
    just spent the token. «Ограничение по запросам» alone would say only that
    nothing can start, where «уже идёт» says the work the caller wants is
    already happening.
    """
    control.running = True
    control.retry_after = 391.0

    response = await client.post("/api/v1/finreports/harvest", headers=headers)

    assert response.json()["status"] == "already_running"


async def test_an_open_bucket_enqueues_the_harvest_as_before(
    client: httpx.AsyncClient, headers: dict[str, str], task: _SpyTask
) -> None:
    """The rate check is a gate, not a new refusal: an open bucket still harvests."""
    response = await client.post("/api/v1/finreports/harvest", headers=headers)

    assert response.json()["status"] == "started"
    assert response.json()["retry_after_seconds"] is None
    assert task.enqueued == 1


async def test_pressing_refresh_during_a_harvest_enqueues_nothing(
    client: httpx.AsyncClient,
    headers: dict[str, str],
    control: _StubHarvestControl,
    task: _SpyTask,
) -> None:
    """A running harvest must not be joined by a second one.

    Not merely "the second run no-ops": nothing is queued at all, so an
    impatient seller clicking through a 20-minute walk cannot pile up a run per
    click behind it.
    """
    control.running = True

    response = await client.post("/api/v1/finreports/harvest", headers=headers)

    assert response.status_code == 202
    assert response.json()["status"] == "already_running"
    assert response.json()["task_id"] is None
    assert task.enqueued == 0


async def test_repeated_clicks_during_a_harvest_stay_at_zero_enqueues(
    client: httpx.AsyncClient,
    headers: dict[str, str],
    control: _StubHarvestControl,
    task: _SpyTask,
) -> None:
    """The guard holds for every click, not just the first."""
    control.running = True

    for _ in range(5):
        await client.post("/api/v1/finreports/harvest", headers=headers)

    assert task.enqueued == 0


async def test_the_status_poll_reports_liveness_and_coverage(
    client: httpx.AsyncClient, headers: dict[str, str], control: _StubHarvestControl
) -> None:
    """Both halves matter: `running` ends the spinner, `latest_settled` says why.

    A finished run that moved nothing is a success — WB had no new report — and
    only the settlement date tells that apart from a run that pulled a week.
    """
    control.running = True

    response = await client.get("/api/v1/finreports/harvest", headers=headers)

    assert response.status_code == 200
    assert response.json()["running"] is True
    assert response.json()["latest_settled"] == "2026-08-09"


async def test_the_poll_carries_what_we_hold_and_when_we_last_asked(
    client: httpx.AsyncClient, headers: dict[str, str]
) -> None:
    """Both halves of the freshness line, or neither is worth showing.

    «Новых отчётов нет» means nothing without «и мы спросили 12 минут назад»: a
    confident "nothing new" that is six hours stale is a dead harvester wearing
    the same words. So the report we hold and the last verdict travel together.
    """
    response = await client.get("/api/v1/finreports/harvest", headers=headers)

    body = response.json()
    assert body["latest_report"] == {
        "report_id": 969371534,
        "date_from": "2026-08-03",
        "date_to": "2026-08-09",
        "harvested_at": "2026-08-11T06:14:00Z",
    }
    assert body["last_check"] == {
        "outcome": "wb_empty",
        "checked_at": "2026-08-12T09:00:00Z",
        "probe_from": "2026-08-10",
        "probe_to": "2026-08-11",
    }


async def test_a_failed_probe_travels_as_a_failure(
    client: httpx.AsyncClient, headers: dict[str, str], control: _StubHarvestControl
) -> None:
    """WB not answering must never reach the page as «нового ничего нет».

    The endpoint relays the outcome verbatim rather than collapsing it to a
    boolean: an unanswered question dressed as reassurance is the exact failure
    this surface exists to prevent.
    """
    control.last_check = FreshnessVerdict(
        outcome=FreshnessOutcome.PROBE_FAILED,
        checked_at=datetime(2026, 8, 12, 9, 0, tzinfo=UTC),
        probe_from=date(2026, 8, 10),
        probe_to=date(2026, 8, 11),
    )

    response = await client.get("/api/v1/finreports/harvest", headers=headers)

    assert response.json()["last_check"]["outcome"] == "probe_failed"


async def test_nothing_recorded_reads_as_nothing_recorded(
    client: httpx.AsyncClient, headers: dict[str, str], control: _StubHarvestControl
) -> None:
    """Never checked, expired, or a corrupt record all arrive as null.

    The page renders that as «мы не проверяли» — the honest answer, and a
    warning rather than a reassurance.
    """
    control.last_check = None
    control.latest_report = None

    response = await client.get("/api/v1/finreports/harvest", headers=headers)

    assert response.json()["last_check"] is None
    assert response.json()["latest_report"] is None


async def test_the_state_is_scoped_to_the_active_workspace(
    client: httpx.AsyncClient,
    headers: dict[str, str],
    control: _StubHarvestControl,
    workspace: Workspace,
) -> None:
    """Coverage is per-tenant: whose settlement history is being reported."""
    await client.get("/api/v1/finreports/harvest", headers=headers)

    assert control.calls[0]["workspace_id"] == workspace.id


async def test_the_trigger_requires_authentication(client: httpx.AsyncClient) -> None:
    """An unauthenticated caller must not be able to spend the WB budget."""
    response = await client.post("/api/v1/finreports/harvest")

    assert response.status_code == 401


async def test_pressing_refresh_also_fills_the_provisional_daily_tail(
    client: Any, headers: dict[str, str], task: _SpyTask, tail_task: _SpyTask
) -> None:
    """The days between the last weekly report and yesterday are the days the
    seller is usually looking at when they press the button.

    Enqueued beside the settled walk rather than after it: that walk can sit for
    minutes waiting for WB's next rate token, and behind it these rows would
    arrive last.
    """
    response = await client.post("/api/v1/finreports/harvest", headers=headers)

    assert response.status_code == 202
    assert tail_task.enqueued == 1


async def test_the_tail_a_click_enqueues_is_scoped_to_the_callers_workspace(
    client: Any, headers: dict[str, str], task: _SpyTask, tail_task: _SpyTask, workspace: Any
) -> None:
    """One tenant's click must not spend every other tenant's WB budget.

    The same rule the settled walk's enqueue already follows — it used to be
    fleet-wide, so the cost of one click grew with the number of sellers and
    landed on all of them.
    """
    await client.post("/api/v1/finreports/harvest", headers=headers)

    assert tail_task.calls == [{"workspace_id": str(workspace.id)}]


async def test_a_refresh_refused_as_already_running_enqueues_no_tail(
    client: Any,
    headers: dict[str, str],
    task: _SpyTask,
    tail_task: _SpyTask,
    control: _StubHarvestControl,
) -> None:
    """A refusal must refuse both halves, or the guard only covers one lane."""
    control.running = True

    response = await client.post("/api/v1/finreports/harvest", headers=headers)

    assert response.json()["status"] == "already_running"
    assert tail_task.enqueued == 0
