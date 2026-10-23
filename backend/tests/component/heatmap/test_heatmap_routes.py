"""Component tests for the heatmap's HTTP surface.

The arithmetic is covered in ``tests/unit/heatmap``; what is proved here is the
transport contract — who may reach the routes at all, that the caller's active
workspace scopes every read and write, and that the window and the filter lists
are bounded before anything reaches a query.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import date, timedelta
from typing import Any

import httpx
import pytest

from src.core.timeutils import moscow_today
from src.modules.heatmap.deps import get_heatmap_service
from src.modules.heatmap.routers.heatmap import DEFAULT_WINDOW_DAYS, MAX_WINDOW_DAYS
from src.modules.heatmap.schemas import (
    HeatmapCatalogResponse,
    HeatmapResponse,
    HeatmapRow,
)
from src.modules.organizations.contract import (
    ALL_MODULES,
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
        empty = HeatmapRow(key="total", label="Total", sku_count=0, total=None, values=[])
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


@pytest.fixture
def heatmap() -> _StubHeatmapService:
    """The stub read service the routes are wired to."""
    return _StubHeatmapService()


@pytest.fixture(autouse=True)
def _wire(
    override: Callable[[Any, Any], None],
    user_repo: FakeUserRepository,
    workspace_repo: FakeWorkspaceRepository,
    heatmap: _StubHeatmapService,
) -> None:
    """Wire identity, tenancy and the stubbed read service."""
    override(get_user_repo, user_repo)
    override(get_workspace_repo, workspace_repo)
    override(get_heatmap_service, heatmap)


@pytest.fixture
def headers(user: Any, workspace: Workspace) -> dict[str, str]:
    """Authenticated headers carrying the active workspace."""
    return {**auth_headers(user.id), WORKSPACE_HEADER: str(workspace.id)}


async def test_the_catalogue_is_ordered_over_the_requested_window(
    client: httpx.AsyncClient,
    headers: dict[str, str],
    heatmap: _StubHeatmapService,
    workspace: Workspace,
) -> None:
    """The pickers sort by orders in the period on screen, for the caller's workspace."""
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


async def test_the_heatmap_grant_is_needed_for_the_page(
    client: httpx.AsyncClient,
    headers: dict[str, str],
    login_as: Callable[..., None],
    heatmap: _StubHeatmapService,
) -> None:
    """Every other grant held, "Heatmap" withheld — nothing."""
    login_as(role=EffectiveRole.MANAGER, modules=tuple(m for m in ALL_MODULES if m != "heatmap"))

    response = await client.get("/api/v1/heatmap", headers=headers)

    assert response.status_code == 403
    assert heatmap.calls == []


@pytest.mark.parametrize(
    ("metric", "metric2"), [("orders", None), ("revenue", None), ("orders", "profit")]
)
async def test_the_heatmap_grant_alone_opens_every_metric(
    client: httpx.AsyncClient,
    headers: dict[str, str],
    login_as: Callable[..., None],
    heatmap: _StubHeatmapService,
    metric: str,
    metric2: str | None,
) -> None:
    """The page's grant opens the page, money included — P&L is no longer asked for too."""
    login_as(role=EffectiveRole.MANAGER, modules=("heatmap",))
    params = {"metric": metric, **({"metric2": metric2} if metric2 else {})}

    response = await client.get("/api/v1/heatmap", params=params, headers=headers)

    assert response.status_code == 200
    assert len(heatmap.calls) == 1


async def test_the_grid_is_scoped_to_the_active_workspace(
    client: httpx.AsyncClient,
    headers: dict[str, str],
    heatmap: _StubHeatmapService,
    workspace: Workspace,
) -> None:
    """The workspace from the header, not the token, scopes the read."""
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
