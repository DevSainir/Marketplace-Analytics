"""Component tests for the monitoring HTTP surface.

The analytics service is stubbed here on purpose: its arithmetic already has
deep unit coverage (``tests/unit/monitoring``), and repeating it through HTTP
would be slow and duplicated. What this tier adds is everything *around* the
service — that the SKU ownership guard makes another workspace's SKU look
nonexistent, that path/query validation rejects nonsense before a query runs,
and that domain errors arrive with the right status.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from datetime import date
from typing import Any, ClassVar

import httpx
import pytest

from src.core.exceptions import NotFoundError, ValidationError
from src.modules.monitoring.deps import get_analytics_service, get_product_card_repo
from src.modules.monitoring.schemas import (
    MetricWindow,
    PinnedSkusResponse,
    SkuLookupResponse,
    SkuSummaryListResponse,
)
from src.modules.users.deps import get_user_repo
from src.modules.workspaces.contract import WORKSPACE_HEADER
from src.modules.workspaces.deps import get_workspace_repo
from src.modules.workspaces.models import Workspace
from tests.support.auth import auth_headers
from tests.support.fakes import FakeUserRepository, FakeWorkspaceRepository, make_workspace

NM_ID = 953770957
FOREIGN_NM_ID = 999999999


class _StubAnalyticsService:
    """Answers exactly the calls these routes make, recording the arguments."""

    def __init__(self) -> None:
        """Start with no recorded calls and benign default answers."""
        self.calls: list[tuple[str, dict[str, Any]]] = []
        #: SKUs the bulk «Обновить все SKU» refresh will enqueue over.
        self.workspace_nm_ids: list[int] = [NM_ID]

    async def list_workspace_nm_ids(self, **kwargs: Any) -> list[int]:
        """Return the workspace's SKU list, recording the call."""
        self.calls.append(("list_workspace_nm_ids", kwargs))
        return self.workspace_nm_ids

    async def get_summary(self, **kwargs: Any) -> SkuSummaryListResponse:
        """Return an empty listing, recording the resolved window and paging."""
        self.calls.append(("get_summary", kwargs))
        return SkuSummaryListResponse(
            window=MetricWindow(start=date(2026, 7, 1), end=date(2026, 7, 7)),
            count=0,
            total=0,
            limit=kwargs.get("limit", 100),
            offset=kwargs.get("offset", 0),
            items=[],
        )

    async def list_pinned_skus(self, **kwargs: Any) -> PinnedSkusResponse:
        """Return an empty chip row."""
        self.calls.append(("list_pinned_skus", kwargs))
        return PinnedSkusResponse(items=[])

    async def lookup_skus_by_vendor_code(
        self, vendor_code: str, **kwargs: Any
    ) -> SkuLookupResponse:
        """Return no matches, recording the searched vendor code."""
        self.calls.append(("lookup", {"vendor_code": vendor_code, **kwargs}))
        return SkuLookupResponse(query=vendor_code, count=0, items=[])

    async def get_detail(self, **kwargs: Any) -> Any:
        """Report the SKU as having no data in the window."""
        self.calls.append(("get_detail", kwargs))
        raise NotFoundError(f"No monitoring data for SKU {kwargs.get('nm_id')}.")

    async def reorder_pins(self, **kwargs: Any) -> PinnedSkusResponse:
        """Reject the reorder the way the real service does on a stale list."""
        self.calls.append(("reorder_pins", kwargs))
        raise ValidationError("The list is not exactly the current pinned set.")


class _StubProductCardRepo:
    """SKU → workspace registry answering the ownership guard."""

    def __init__(self, owned: set[int]) -> None:
        """Record which SKUs the active workspace owns."""
        self.owned = owned

    async def is_in_workspace(self, *, nm_id: int, workspace_id: Any) -> bool:
        """Report whether this SKU belongs to the caller's workspace."""
        return nm_id in self.owned


@pytest.fixture
def analytics() -> _StubAnalyticsService:
    """The stub service the routes are wired to."""
    return _StubAnalyticsService()


@pytest.fixture(autouse=True)
def _wire_monitoring(
    override: Callable[[Any, Any], None],
    user_repo: FakeUserRepository,
    workspace_repo: FakeWorkspaceRepository,
    analytics: _StubAnalyticsService,
) -> None:
    """Wire identity, tenancy, the SKU registry, and the stubbed service."""
    override(get_user_repo, user_repo)
    override(get_workspace_repo, workspace_repo)
    override(get_product_card_repo, _StubProductCardRepo({NM_ID}))
    override(get_analytics_service, analytics)


@pytest.fixture
def headers(user: Any, workspace: Workspace) -> dict[str, str]:
    """Authenticated headers carrying the active workspace."""
    return {**auth_headers(user.id), WORKSPACE_HEADER: str(workspace.id)}


# --------------------------------------------------------------------------- #
# Listing and lookup
# --------------------------------------------------------------------------- #
async def test_summary_passes_the_active_workspace_to_the_service(
    client: httpx.AsyncClient,
    headers: dict[str, str],
    analytics: _StubAnalyticsService,
    workspace: Workspace,
) -> None:
    """The header — not a query parameter — is what scopes the listing.

    If the workspace ever stopped reaching the service, every tenant would see
    the same rows.
    """
    response = await client.get("/api/v1/monitoring/summary", headers=headers)

    assert response.status_code == 200
    assert analytics.calls[0][1]["workspace_id"] == workspace.id


@pytest.mark.parametrize(
    "query",
    ["limit=0", "limit=501", "offset=-1", "date_from=not-a-date"],
)
async def test_summary_rejects_out_of_range_paging(
    client: httpx.AsyncClient, headers: dict[str, str], query: str
) -> None:
    """Paging bounds are enforced at the edge, not by the database.

    An unbounded ``limit`` is a trivial denial-of-service against the matrix
    query; ``le=500`` is the guard.
    """
    response = await client.get(f"/api/v1/monitoring/summary?{query}", headers=headers)

    assert response.status_code == 422


async def test_lookup_requires_a_non_empty_vendor_code(
    client: httpx.AsyncClient, headers: dict[str, str]
) -> None:
    """A blank search would scan every SKU; it is refused as 422."""
    response = await client.get("/api/v1/monitoring/skus/lookup?vendor_code=", headers=headers)

    assert response.status_code == 422


async def test_lookup_path_is_not_swallowed_by_the_sku_id_route(
    client: httpx.AsyncClient, headers: dict[str, str], analytics: _StubAnalyticsService
) -> None:
    """``/skus/lookup`` must resolve to the search route, not ``/skus/{nm_id}``.

    Both patterns match the same URL; only declaration order keeps the static
    path from being parsed as an integer SKU id.
    """
    response = await client.get(
        "/api/v1/monitoring/skus/lookup?vendor_code=M-TRX01", headers=headers
    )

    assert response.status_code == 200
    assert analytics.calls[0][0] == "lookup"


# --------------------------------------------------------------------------- #
# SKU ownership guard
# --------------------------------------------------------------------------- #
async def test_a_foreign_workspaces_sku_is_a_404(
    client: httpx.AsyncClient, headers: dict[str, str], analytics: _StubAnalyticsService
) -> None:
    """Another tenant's SKU is indistinguishable from a nonexistent one.

    A 403 here would confirm the SKU exists somewhere — enough to enumerate a
    competitor's catalogue through this endpoint.
    """
    response = await client.get(f"/api/v1/monitoring/skus/{FOREIGN_NM_ID}", headers=headers)

    assert response.status_code == 404
    assert analytics.calls == []


async def test_an_owned_sku_reaches_the_service(
    client: httpx.AsyncClient, headers: dict[str, str], analytics: _StubAnalyticsService
) -> None:
    """A SKU in the active workspace passes the guard and is queried."""
    response = await client.get(f"/api/v1/monitoring/skus/{NM_ID}", headers=headers)

    assert response.status_code == 404  # the stub reports "no data in window"
    assert analytics.calls[0][0] == "get_detail"


async def test_a_non_numeric_sku_id_is_422(
    client: httpx.AsyncClient, headers: dict[str, str]
) -> None:
    """The path parameter is typed, so garbage never reaches the guard."""
    response = await client.get(
        "/api/v1/monitoring/skus/abc/stock?on_date=2026-07-01", headers=headers
    )

    assert response.status_code == 422


async def test_the_guard_applies_to_every_per_sku_route(
    client: httpx.AsyncClient, headers: dict[str, str]
) -> None:
    """Write routes are guarded too, not just the read path.

    A tenancy check on GET only would let a caller comment on, pin, or edit the
    matrix of a SKU they cannot read.
    """
    responses = [
        await client.put(
            f"/api/v1/monitoring/skus/{FOREIGN_NM_ID}/pin",
            headers=headers,
            json={"pinned": True},
        ),
        await client.put(
            f"/api/v1/monitoring/skus/{FOREIGN_NM_ID}/comments/2026-07-01",
            headers=headers,
            json={"body": "hello"},
        ),
        await client.get(f"/api/v1/monitoring/funnel/{FOREIGN_NM_ID}", headers=headers),
    ]

    assert [response.status_code for response in responses] == [404, 404, 404]


# --------------------------------------------------------------------------- #
# Body-identified routes (no path guard available)
# --------------------------------------------------------------------------- #
async def test_reorder_validation_error_maps_to_422(
    client: httpx.AsyncClient, headers: dict[str, str]
) -> None:
    """``PUT /pins/order`` takes its ids from the body, so the service guards it.

    The route cannot use the path-based ownership dependency; a stale reorder
    must therefore come back as 422 from the service.
    """
    response = await client.put(
        "/api/v1/monitoring/pins/order", headers=headers, json={"nm_ids": [NM_ID]}
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "unprocessable_entity"


async def test_pin_colour_must_be_a_hex_triplet(
    client: httpx.AsyncClient, headers: dict[str, str]
) -> None:
    """A free-text colour would be injected straight into a style attribute."""
    response = await client.put(
        f"/api/v1/monitoring/skus/{NM_ID}/pin-color",
        headers=headers,
        json={"color": "red; background: url(evil)"},
    )

    assert response.status_code == 422


# --------------------------------------------------------------------------- #
# Refresh-task ownership
# --------------------------------------------------------------------------- #
class _FakeAsyncResult:
    """Celery's ``AsyncResult`` without its Redis result backend.

    ``get_refresh_status`` asks Celery for the task's state, and Celery answers
    from the broker — a live Redis this tier deliberately does not have. Faking
    it keeps the route, the ownership guard and the response model real, which
    is what the component tier exists to prove; whether Celery reports state
    correctly is Celery's problem, exercised for real in
    ``tests/integration/celery/test_task_wiring.py``.
    """

    #: Return value the faked task reports, as the harvest would produce it.
    payload: ClassVar[object] = {"funnel_rows": 7, "failed_sources": []}

    def __init__(self, task_id: str, app: Any = None) -> None:
        """Record the polled id and report a finished, successful task."""
        self.id = task_id
        self.state = "SUCCESS"
        self.result = self.payload

    def ready(self) -> bool:
        """Report the task as finished."""
        return True

    def successful(self) -> bool:
        """Report the task as successful."""
        return True


@pytest.fixture
def _fake_celery_result(monkeypatch: pytest.MonkeyPatch) -> None:
    """Replace Celery's result lookup for the refresh-status route."""
    monkeypatch.setattr("src.modules.monitoring.routers.refresh.AsyncResult", _FakeAsyncResult)


@pytest.mark.usefixtures("_fake_celery_result")
async def test_a_refresh_task_id_is_only_readable_by_the_workspace_that_enqueued_it(
    client: httpx.AsyncClient,
    headers: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``GET /refresh/{task_id}`` is workspace-scoped; an unknown id is a 404.

    Celery's ``AsyncResult`` reports on any id present in the broker, so without
    a scope check one workspace could poll another's harvest and learn both that
    it ran and whether it succeeded. A foreign id must be indistinguishable from
    one that never existed.

    The binding itself is REAL here (``redis_store`` backs it with the
    in-memory Redis): stubbing `bind_task_to_workspace` /
    `task_belongs_to_workspace` would have left the guard's actual logic — the
    key it writes and the comparison it makes — untested.
    """
    monkeypatch.setattr(
        "src.modules.monitoring.routers.refresh.harvest_sku_window.delay",
        lambda nm_ids: type("Task", (), {"id": "task-abc"})(),
    )

    enqueued = await client.post(f"/api/v1/monitoring/skus/{NM_ID}/refresh", headers=headers)
    own = await client.get("/api/v1/monitoring/refresh/task-abc", headers=headers)
    foreign = await client.get("/api/v1/monitoring/refresh/someone-elses-task", headers=headers)

    assert enqueued.status_code == 202
    assert enqueued.json()["task_id"] == "task-abc"
    assert own.status_code == 200
    assert foreign.status_code == 404


@pytest.mark.usefixtures("_fake_celery_result")
async def test_a_refresh_task_is_invisible_to_a_different_workspace(
    client: httpx.AsyncClient,
    user: Any,
    workspace: Workspace,
    workspace_repo: FakeWorkspaceRepository,
    organization_id: uuid.UUID,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The same task id polled from ANOTHER workspace is a 404.

    The sharper half of the guard: the id exists and is bound, so only the
    workspace comparison can reject it. Both workspaces belong to the SAME
    organisation on purpose — a second tenant would be refused by the tenancy
    check one layer up, and this test is about the task binding underneath it.
    """
    monkeypatch.setattr(
        "src.modules.monitoring.routers.refresh.harvest_sku_window.delay",
        lambda nm_ids: type("Task", (), {"id": "task-xyz"})(),
    )
    other = make_workspace(organization_id=organization_id, name="Другое пространство")
    workspace_repo.workspaces[other.id] = other

    mine = {**auth_headers(user.id), WORKSPACE_HEADER: str(workspace.id)}
    theirs = {**auth_headers(user.id), WORKSPACE_HEADER: str(other.id)}

    await client.post(f"/api/v1/monitoring/skus/{NM_ID}/refresh", headers=mine)
    seen_by_owner = await client.get("/api/v1/monitoring/refresh/task-xyz", headers=mine)
    seen_by_other = await client.get("/api/v1/monitoring/refresh/task-xyz", headers=theirs)

    assert seen_by_owner.status_code == 200
    assert seen_by_other.status_code == 404


@pytest.mark.usefixtures("_fake_celery_result")
async def test_a_partially_served_refresh_reports_which_wb_sources_failed(
    client: httpx.AsyncClient,
    headers: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A successful harvest that WB only partly served says which part is missing.

    The harvest deliberately tolerates a partial WB outage, so ``successful``
    stays true while the funnel rows never arrive. On 2026-07-30 that combination
    redrew the same numbers with no explanation and «Обновить» looked inert. The
    SPA can only say "Wildberries не отдал воронку продаж" if this field carries
    it, so the field is part of the contract.
    """
    monkeypatch.setattr(
        _FakeAsyncResult, "payload", {"funnel_rows": 0, "failed_sources": ["sales-funnel"]}
    )
    monkeypatch.setattr(
        "src.modules.monitoring.routers.refresh.harvest_sku_window.delay",
        lambda nm_ids: type("Task", (), {"id": "task-partial"})(),
    )

    await client.post(f"/api/v1/monitoring/skus/{NM_ID}/refresh", headers=headers)
    status = await client.get("/api/v1/monitoring/refresh/task-partial", headers=headers)

    assert status.status_code == 200
    assert status.json()["successful"] is True
    assert status.json()["failed_sources"] == ["sales-funnel"]


@pytest.mark.usefixtures("_fake_celery_result")
async def test_a_task_result_without_the_field_is_read_as_no_failures(
    client: httpx.AsyncClient,
    headers: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A result enqueued before this field existed must not break the poll.

    Mid-rollout, and for a few minutes after every deploy, the result backend
    still holds payloads from the previous version. The poll is what the SPA
    spins on — it cannot 500 on an older shape.
    """
    monkeypatch.setattr(_FakeAsyncResult, "payload", {"funnel_rows": 12})
    monkeypatch.setattr(
        "src.modules.monitoring.routers.refresh.harvest_sku_window.delay",
        lambda nm_ids: type("Task", (), {"id": "task-legacy"})(),
    )

    await client.post(f"/api/v1/monitoring/skus/{NM_ID}/refresh", headers=headers)
    status = await client.get("/api/v1/monitoring/refresh/task-legacy", headers=headers)

    assert status.status_code == 200
    assert status.json()["failed_sources"] == []


# --------------------------------------------------------------------------- #
# Bulk «Обновить все SKU»
# --------------------------------------------------------------------------- #
async def test_refresh_all_enqueues_a_harvest_over_every_workspace_sku(
    client: httpx.AsyncClient,
    headers: dict[str, str],
    analytics: _StubAnalyticsService,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The bulk refresh harvests exactly the workspace's own SKU list.

    The single task must carry every SKU the workspace owns — the whole point of
    the button — and no others, so the harvest cannot reach into another tenant.
    """
    analytics.workspace_nm_ids = [NM_ID, 424242]
    captured: dict[str, Any] = {}

    def _capture(nm_ids: list[int]) -> Any:
        captured["nm_ids"] = nm_ids
        return type("Task", (), {"id": "task-all"})()

    monkeypatch.setattr("src.modules.monitoring.routers.refresh.harvest_sku_window.delay", _capture)

    response = await client.post("/api/v1/monitoring/skus/refresh-all", headers=headers)

    assert response.status_code == 202
    assert response.json()["task_id"] == "task-all"
    assert captured["nm_ids"] == [NM_ID, 424242]


async def test_refresh_all_on_an_empty_workspace_is_a_404(
    client: httpx.AsyncClient,
    headers: dict[str, str],
    analytics: _StubAnalyticsService,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """With no SKUs there is nothing to harvest, and enqueuing an empty task
    would crash the worker (it indexes ``nm_ids[0]`` to resolve the workspace),
    so the route refuses up front instead."""
    analytics.workspace_nm_ids = []

    def _must_not_enqueue(nm_ids: list[int]) -> Any:  # pragma: no cover - must not run
        raise AssertionError("no harvest should be enqueued for an empty workspace")

    monkeypatch.setattr(
        "src.modules.monitoring.routers.refresh.harvest_sku_window.delay", _must_not_enqueue
    )

    response = await client.post("/api/v1/monitoring/skus/refresh-all", headers=headers)

    assert response.status_code == 404
