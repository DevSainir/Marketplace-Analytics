"""A "Refresh" must not be an unbounded way to spend the platform's resources.

Register P0.4. Both enqueue routes called ``harvest_sku_window.delay`` with
nothing in the way: every press queued another catalogue walk, so a held-down
button — or a loop — could pile arbitrarily many onto a worker pool of four and
starve every scheduled harvest behind them.

Two controls, doing different jobs. Deduplication answers an identical request
already in flight with that task's id, so ordinary impatience costs nothing.
The budget is the bound on abuse, and it is keyed on the **workspace** rather
than the caller's address: the queue and the WB rate budget are spent per
tenant, so keying on the address would let one tenant multiply its allowance by
its number of devices, and would make two colleagues behind one office NAT
share a single one.

Both stores are the real ones here — the tier's in-memory Redis backs them — so
what is under test is the key each writes and the comparison each makes.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from typing import Any

import httpx
import pytest

from src.core.config import settings
from src.modules.monitoring.deps import get_analytics_service, get_product_card_repo
from src.modules.users.deps import get_user_repo
from src.modules.workspaces.contract import WORKSPACE_HEADER
from src.modules.workspaces.deps import get_workspace_repo
from src.modules.workspaces.models import Workspace
from tests.support.auth import auth_headers
from tests.support.fakes import FakeUserRepository, FakeWorkspaceRepository

NM_ID = 953770957


class _StubAnalytics:
    """Answers only ``list_workspace_nm_ids``, which refresh-all needs."""

    async def list_workspace_nm_ids(self, *, workspace_id: uuid.UUID) -> list[int]:
        """Report a one-SKU catalogue."""
        return [NM_ID]


class _StubProductCardRepo:
    """SKU → workspace registry answering the ownership guard."""

    def __init__(self, owned: set[int]) -> None:
        """Record which SKUs the active workspace owns."""
        self.owned = owned

    async def is_in_workspace(self, *, nm_id: int, workspace_id: Any) -> bool:
        """Report whether this SKU belongs to the caller's workspace."""
        return nm_id in self.owned


class _SpyEnqueue:
    """Counts calls to ``harvest_sku_window.delay`` and mints distinct ids."""

    def __init__(self) -> None:
        """Start with nothing enqueued."""
        self.count = 0

    def __call__(self, nm_ids: list[int]) -> Any:
        """Record an enqueue and return a fresh task id."""
        self.count += 1
        return type("Task", (), {"id": f"task-{self.count}"})()


@pytest.fixture
def enqueue(monkeypatch: pytest.MonkeyPatch) -> _SpyEnqueue:
    """Replace the Celery enqueue so nothing reaches a broker."""
    spy = _SpyEnqueue()
    monkeypatch.setattr("src.modules.monitoring.routers.refresh.harvest_sku_window.delay", spy)
    return spy


@pytest.fixture(autouse=True)
def _wire(
    override: Callable[[Any, Any], None],
    user_repo: FakeUserRepository,
    workspace_repo: FakeWorkspaceRepository,
) -> None:
    """Wire identity, tenancy, the SKU registry and the analytics stub."""
    override(get_user_repo, user_repo)
    override(get_workspace_repo, workspace_repo)
    override(get_product_card_repo, _StubProductCardRepo({NM_ID}))
    override(get_analytics_service, _StubAnalytics())


@pytest.fixture
def headers(user: Any, workspace: Workspace) -> dict[str, str]:
    """Authenticated headers carrying the active workspace."""
    return {**auth_headers(user.id), WORKSPACE_HEADER: str(workspace.id)}


async def test_a_repeated_press_reuses_the_running_task(
    client: httpx.AsyncClient, headers: dict[str, str], enqueue: _SpyEnqueue
) -> None:
    """A second press of "Refresh" joins the first harvest instead of racing it.

    Two runs writing the same rows is waste at best; the seller wants one
    harvest and one id to poll either way.
    """
    first = await client.post(f"/api/v1/monitoring/skus/{NM_ID}/refresh", headers=headers)
    second = await client.post(f"/api/v1/monitoring/skus/{NM_ID}/refresh", headers=headers)

    assert enqueue.count == 1
    assert first.json()["task_id"] == second.json()["task_id"]


async def test_refresh_all_deduplicates_on_the_sku_set(
    client: httpx.AsyncClient, headers: dict[str, str], enqueue: _SpyEnqueue
) -> None:
    """The bulk route dedups too — it is the heavier of the two."""
    await client.post("/api/v1/monitoring/skus/refresh-all", headers=headers)
    await client.post("/api/v1/monitoring/skus/refresh-all", headers=headers)

    assert enqueue.count == 1


async def test_a_workspace_cannot_enqueue_past_its_budget(
    client: httpx.AsyncClient,
    headers: dict[str, str],
    enqueue: _SpyEnqueue,
    redis_store: Any,
) -> None:
    """Once the window's budget is spent, further presses are refused with 429.

    The budget is pre-spent rather than reached by looping, so the assertion is
    about the guard and not about how many presses the configured limit allows.
    """
    workspace_id = headers[WORKSPACE_HEADER]
    key = f"ratelimit:monitoring-refresh-enqueue:{workspace_id}"
    redis_store.counters[key] = settings.refresh_enqueue_attempts

    response = await client.post(f"/api/v1/monitoring/skus/{NM_ID}/refresh", headers=headers)

    assert response.status_code == 429
    assert enqueue.count == 0


async def test_the_budget_is_charged_to_the_workspace_not_the_address(
    client: httpx.AsyncClient,
    headers: dict[str, str],
    redis_store: Any,
    enqueue: _SpyEnqueue,
) -> None:
    """The counter key names the tenant, which is who spends the queue.

    Keyed on the caller's address instead, one tenant would get a fresh budget
    per device while two colleagues on one office NAT shared one.
    """
    await client.post(f"/api/v1/monitoring/skus/{NM_ID}/refresh", headers=headers)

    workspace_id = headers[WORKSPACE_HEADER]
    assert f"ratelimit:monitoring-refresh-enqueue:{workspace_id}" in redis_store.counters
