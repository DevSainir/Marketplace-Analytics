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
from datetime import date
from typing import Any

import httpx
import pytest

from src.modules.finreports.deps import get_harvest_control_service
from src.modules.finreports.services import HarvestState
from src.modules.users.deps import get_user_repo
from src.modules.workspaces.contract import WORKSPACE_HEADER
from src.modules.workspaces.deps import get_workspace_repo
from src.modules.workspaces.models import Workspace
from tests.support.auth import auth_headers
from tests.support.fakes import FakeUserRepository, FakeWorkspaceRepository

SETTLED_THROUGH = date(2026, 8, 9)


class _StubHarvestControl:
    """Reports a canned harvest state and records who asked."""

    def __init__(self) -> None:
        """Start idle, settled through :data:`SETTLED_THROUGH`."""
        self.running = False
        self.calls: list[dict[str, Any]] = []

    async def get_state(self, **kwargs: Any) -> HarvestState:
        """Echo the caller's scope back through a canned state."""
        self.calls.append(kwargs)
        return HarvestState(running=self.running, latest_settled=SETTLED_THROUGH)


class _SpyTask:
    """Stands in for ``harvest_finance.delay`` and counts enqueues."""

    def __init__(self) -> None:
        """Start with nothing enqueued."""
        self.enqueued = 0

    def delay(self) -> Any:
        """Record an enqueue and hand back a task id."""
        self.enqueued += 1
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
    assert response.json() == {"running": True, "latest_settled": "2026-08-09"}


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
