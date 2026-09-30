"""Component tests for the heatmap's HTTP surface.

The arithmetic is covered in ``tests/unit/heatmap``; what is proved here is the
transport contract — who may reach the routes at all, that the caller's active
кабинет scopes every read and write, and that the window and the filter lists
are bounded before anything reaches a query.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from datetime import date, timedelta
from typing import Any

import httpx
import pytest

from src.core.exceptions import NotFoundError
from src.core.timeutils import moscow_today
from src.modules.heatmap.deps import get_group_service, get_heatmap_service, get_norm_service
from src.modules.heatmap.routers.heatmap import DEFAULT_WINDOW_DAYS, MAX_WINDOW_DAYS
from src.modules.heatmap.schemas import (
    HeatmapCatalogResponse,
    HeatmapResponse,
    HeatmapRow,
    SkuGroupList,
    SkuGroupRead,
    SkuGroupWrite,
    SkuNormList,
    SkuNormRead,
)
from src.modules.organizations.contract import (
    ALL_MODULES,
    AccessLevel,
    EffectiveRole,
    SubscriptionState,
)
from src.modules.users.deps import get_user_repo
from src.modules.workspaces.contract import WORKSPACE_HEADER
from src.modules.workspaces.deps import get_workspace_repo
from src.modules.workspaces.models import Workspace
from tests.support.auth import auth_headers
from tests.support.fakes import FakeUserRepository, FakeWorkspaceRepository


class _StubHeatmapService:
    """Records every request the grid and catalogue routes resolve."""

    def __init__(self) -> None:
        """Start with no recorded calls."""
        self.calls: list[dict[str, Any]] = []

    async def build(self, _session: Any, **kwargs: Any) -> HeatmapResponse:
        """Echo the resolved query back through an empty grid."""
        self.calls.append(kwargs)
        query = kwargs["query"]
        empty = HeatmapRow(key="total", label="Итого", sku_count=0, total=None, values=[])
        return HeatmapResponse(
            date_from=query.date_from,
            date_to=query.date_to,
            period=query.period,
            group_by=query.group_by,
            metric=query.metric,
            metric2=query.metric2,
            currency="",
            settled_to=None,
            columns=[],
            totals=empty,
            rows=[],
        )

    async def catalog(self, _session: Any, **kwargs: Any) -> HeatmapCatalogResponse:
        """Record the catalogue read."""
        self.calls.append(kwargs)
        return HeatmapCatalogResponse(items=[], subjects=[])


class _StubGroupService:
    """Records group writes; knows one group id."""

    def __init__(self) -> None:
        """Start with one known group."""
        self.known = uuid.uuid4()
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def list_groups(self, **kwargs: Any) -> SkuGroupList:
        """Record the list."""
        self.calls.append(("list", kwargs))
        return SkuGroupList(items=[])

    async def create(self, _session: Any, **kwargs: Any) -> SkuGroupRead:
        """Record the create and echo the group."""
        self.calls.append(("create", kwargs))
        payload: SkuGroupWrite = kwargs["payload"]
        return SkuGroupRead(id=uuid.uuid4(), name=payload.name, nm_ids=payload.nm_ids)

    async def delete(self, **kwargs: Any) -> None:
        """Delete the known group; anything else is missing."""
        self.calls.append(("delete", kwargs))
        if kwargs["group_id"] != self.known:
            raise NotFoundError("Группа не найдена.")


class _StubNormService:
    """Records norm reads and writes."""

    def __init__(self) -> None:
        """Start with no recorded calls."""
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def list_norms(self, **kwargs: Any) -> SkuNormList:
        """Record the list."""
        self.calls.append(("list", kwargs))
        return SkuNormList(items=[])

    async def set_norm(self, _session: Any, **kwargs: Any) -> SkuNormRead:
        """Record the set and echo the norm."""
        self.calls.append(("set", kwargs))
        return SkuNormRead(nm_id=kwargs["nm_id"], metric=kwargs["metric"], value=kwargs["value"])

    async def clear_norm(self, **kwargs: Any) -> None:
        """Record the clear."""
        self.calls.append(("clear", kwargs))


@pytest.fixture
def heatmap() -> _StubHeatmapService:
    """The stub read service the routes are wired to."""
    return _StubHeatmapService()


@pytest.fixture
def groups() -> _StubGroupService:
    """The stub group service the routes are wired to."""
    return _StubGroupService()


@pytest.fixture
def norms() -> _StubNormService:
    """The stub norm service the routes are wired to."""
    return _StubNormService()


@pytest.fixture(autouse=True)
def _wire(
    override: Callable[[Any, Any], None],
    user_repo: FakeUserRepository,
    workspace_repo: FakeWorkspaceRepository,
    heatmap: _StubHeatmapService,
    groups: _StubGroupService,
    norms: _StubNormService,
) -> None:
    """Wire identity, tenancy and the three stubbed services."""
    override(get_user_repo, user_repo)
    override(get_workspace_repo, workspace_repo)
    override(get_heatmap_service, heatmap)
    override(get_group_service, groups)
    override(get_norm_service, norms)


@pytest.fixture
def headers(user: Any, workspace: Workspace) -> dict[str, str]:
    """Authenticated headers carrying the active кабинет."""
    return {**auth_headers(user.id), WORKSPACE_HEADER: str(workspace.id)}


async def test_the_catalogue_is_ordered_over_the_requested_window(
    client: httpx.AsyncClient,
    headers: dict[str, str],
    heatmap: _StubHeatmapService,
    workspace: Workspace,
) -> None:
    """The pickers sort by orders in the period on screen, for the caller's кабинет."""
    response = await client.get(
        "/api/v1/heatmap/catalog",
        params={"date_from": "2026-09-01", "date_to": "2026-09-27"},
        headers=headers,
    )

    assert response.status_code == 200
    assert heatmap.calls[0] == {
        "workspace_id": workspace.id,
        "date_from": date(2026, 9, 1),
        "date_to": date(2026, 9, 27),
    }


async def test_a_paying_customer_reaches_the_heatmap(
    client: httpx.AsyncClient, headers: dict[str, str], login_as: Callable[..., None]
) -> None:
    """Open to every subscribed organisation since it left /labs, not only to us."""
    login_as(is_primary_org=False)

    response = await client.get("/api/v1/heatmap", headers=headers)

    assert response.status_code == 200


async def test_a_lapsed_subscription_cannot_reach_the_heatmap(
    client: httpx.AsyncClient,
    headers: dict[str, str],
    login_as: Callable[..., None],
    heatmap: _StubHeatmapService,
) -> None:
    """Past grace nothing tenant-scoped answers, this page included."""
    login_as(subscription=SubscriptionState.EXPIRED)

    response = await client.get("/api/v1/heatmap", headers=headers)

    assert response.status_code == 403
    assert heatmap.calls == []


@pytest.mark.parametrize("withheld", ["monitoring", "finreports"])
async def test_both_module_grants_are_needed(
    client: httpx.AsyncClient,
    headers: dict[str, str],
    login_as: Callable[..., None],
    withheld: str,
) -> None:
    """The grid shows orders and profit side by side, so either grant missing is a 403."""
    login_as(
        role=EffectiveRole.MANAGER,
        modules=tuple(m for m in ALL_MODULES if m != withheld),
    )

    response = await client.get("/api/v1/heatmap", headers=headers)

    assert response.status_code == 403


async def test_the_grid_is_scoped_to_the_active_workspace(
    client: httpx.AsyncClient,
    headers: dict[str, str],
    heatmap: _StubHeatmapService,
    workspace: Workspace,
) -> None:
    """The кабинет from the header, not the token, scopes the read."""
    response = await client.get("/api/v1/heatmap", headers=headers)

    assert response.status_code == 200
    assert heatmap.calls[0]["workspace_id"] == workspace.id


async def test_an_omitted_window_is_the_week_ending_yesterday(
    client: httpx.AsyncClient, headers: dict[str, str], heatmap: _StubHeatmapService
) -> None:
    """Today's funnel is still filling; a half-day would paint itself red."""
    await client.get("/api/v1/heatmap", headers=headers)

    query = heatmap.calls[0]["query"]
    assert query.date_to == moscow_today() - timedelta(days=1)
    assert (query.date_to - query.date_from).days + 1 == DEFAULT_WINDOW_DAYS


async def test_a_window_longer_than_the_cap_is_refused(
    client: httpx.AsyncClient, headers: dict[str, str], heatmap: _StubHeatmapService
) -> None:
    """Every SKU-day of the window is scanned, so the bound is checked before any query."""
    end = date(2026, 9, 23)
    start = end - timedelta(days=MAX_WINDOW_DAYS)

    response = await client.get(
        "/api/v1/heatmap",
        params={"date_from": start.isoformat(), "date_to": end.isoformat()},
        headers=headers,
    )

    assert response.status_code == 422
    assert heatmap.calls == []


async def test_the_longest_allowed_window_is_accepted(
    client: httpx.AsyncClient, headers: dict[str, str]
) -> None:
    """180 days inclusive is the cap, not one past it."""
    end = date(2026, 9, 23)
    start = end - timedelta(days=MAX_WINDOW_DAYS - 1)

    response = await client.get(
        "/api/v1/heatmap",
        params={"date_from": start.isoformat(), "date_to": end.isoformat()},
        headers=headers,
    )

    assert response.status_code == 200


async def test_an_unknown_metric_is_refused(
    client: httpx.AsyncClient, headers: dict[str, str], heatmap: _StubHeatmapService
) -> None:
    """Metric keys are a closed list; a free string never reaches the service."""
    response = await client.get(
        "/api/v1/heatmap", params={"metric": "password_hash"}, headers=headers
    )

    assert response.status_code == 422
    assert heatmap.calls == []


async def test_an_oversized_article_filter_is_refused(
    client: httpx.AsyncClient, headers: dict[str, str], heatmap: _StubHeatmapService
) -> None:
    """The article list is bounded before it can become a huge ``IN`` clause."""
    response = await client.get(
        "/api/v1/heatmap",
        params=[("nm_ids", str(nm)) for nm in range(1, 1003)],
        headers=headers,
    )

    assert response.status_code == 422
    assert heatmap.calls == []


async def test_the_same_metric_twice_is_one_metric(
    client: httpx.AsyncClient, headers: dict[str, str], heatmap: _StubHeatmapService
) -> None:
    """Choosing the primary metric as the second one too shows it once, not twice per cell."""
    await client.get(
        "/api/v1/heatmap", params={"metric": "orders", "metric2": "orders"}, headers=headers
    )

    assert heatmap.calls[0]["query"].metric2 is None


async def test_a_read_only_manager_cannot_create_a_group(
    client: httpx.AsyncClient,
    headers: dict[str, str],
    login_as: Callable[..., None],
    groups: _StubGroupService,
) -> None:
    """A group changes what everyone in the кабинет sees in the filter — it is a write."""
    login_as(role=EffectiveRole.MANAGER, access_level=AccessLevel.READ_ONLY)

    response = await client.post(
        "/api/v1/heatmap/groups",
        json={"name": "Двойки", "nm_ids": [1]},
        headers=headers,
    )

    assert response.status_code == 403
    assert groups.calls == []


async def test_a_writer_creates_a_group_in_the_active_workspace(
    client: httpx.AsyncClient,
    headers: dict[str, str],
    groups: _StubGroupService,
    workspace: Workspace,
) -> None:
    """The кабинет comes from the header; the body cannot name one."""
    response = await client.post(
        "/api/v1/heatmap/groups",
        json={"name": "  Двойки  ", "nm_ids": [1, 2]},
        headers=headers,
    )

    assert response.status_code == 201
    kind, call = groups.calls[0]
    assert kind == "create"
    assert call["workspace_id"] == workspace.id
    assert call["payload"].name == "Двойки"


async def test_a_blank_group_name_is_refused(
    client: httpx.AsyncClient, headers: dict[str, str], groups: _StubGroupService
) -> None:
    """A group the filter would list as an empty line is not a group."""
    response = await client.post(
        "/api/v1/heatmap/groups", json={"name": "   ", "nm_ids": [1]}, headers=headers
    )

    assert response.status_code == 422
    assert groups.calls == []


async def test_deleting_an_unknown_group_is_a_404(
    client: httpx.AsyncClient, headers: dict[str, str]
) -> None:
    """A group of another кабинет is missing, not forbidden — a guessed id confirms nothing."""
    response = await client.delete(f"/api/v1/heatmap/groups/{uuid.uuid4()}", headers=headers)

    assert response.status_code == 404


async def test_the_norms_are_read_for_the_active_workspace(
    client: httpx.AsyncClient,
    headers: dict[str, str],
    norms: _StubNormService,
    workspace: Workspace,
) -> None:
    """The кабинет from the header scopes the list."""
    response = await client.get("/api/v1/heatmap/norms", headers=headers)

    assert response.status_code == 200
    assert norms.calls == [("list", {"workspace_id": workspace.id})]


async def test_a_writer_sets_a_norm_in_the_active_workspace(
    client: httpx.AsyncClient,
    headers: dict[str, str],
    norms: _StubNormService,
    workspace: Workspace,
) -> None:
    """Article and metric come from the path, the кабинет from the header."""
    response = await client.put(
        "/api/v1/heatmap/norms/123/orders", json={"value": 50}, headers=headers
    )

    assert response.status_code == 200
    kind, call = norms.calls[0]
    assert kind == "set"
    assert call["workspace_id"] == workspace.id
    assert (call["nm_id"], call["metric"], call["value"]) == (123, "orders", 50.0)


async def test_a_read_only_manager_cannot_set_or_clear_a_norm(
    client: httpx.AsyncClient,
    headers: dict[str, str],
    login_as: Callable[..., None],
    norms: _StubNormService,
) -> None:
    """A norm changes how everyone in the кабинет sees the grid — it is a write."""
    login_as(role=EffectiveRole.MANAGER, access_level=AccessLevel.READ_ONLY)

    put = await client.put("/api/v1/heatmap/norms/123/orders", json={"value": 5}, headers=headers)
    delete = await client.delete("/api/v1/heatmap/norms/123/orders", headers=headers)

    assert (put.status_code, delete.status_code) == (403, 403)
    assert norms.calls == []


@pytest.mark.parametrize(
    ("path", "body"),
    [
        ("/api/v1/heatmap/norms/123/password_hash", {"value": 1}),
        ("/api/v1/heatmap/norms/0/orders", {"value": 1}),
        ("/api/v1/heatmap/norms/123/orders", {"value": 1e13}),
        ("/api/v1/heatmap/norms/123/orders", {"value": "NaN"}),
    ],
)
async def test_a_norm_outside_the_bounds_is_refused(
    client: httpx.AsyncClient,
    headers: dict[str, str],
    norms: _StubNormService,
    path: str,
    body: dict[str, Any],
) -> None:
    """Metric is a closed list, the article positive, the value finite and bounded."""
    response = await client.put(path, json=body, headers=headers)

    assert response.status_code == 422
    assert norms.calls == []


async def test_clearing_a_norm_is_scoped_to_the_active_workspace(
    client: httpx.AsyncClient,
    headers: dict[str, str],
    norms: _StubNormService,
    workspace: Workspace,
) -> None:
    """A clear can only ever reach the caller's own кабинет."""
    response = await client.delete("/api/v1/heatmap/norms/123/orders", headers=headers)

    assert response.status_code == 204
    assert norms.calls == [
        ("clear", {"workspace_id": workspace.id, "nm_id": 123, "metric": "orders"})
    ]
