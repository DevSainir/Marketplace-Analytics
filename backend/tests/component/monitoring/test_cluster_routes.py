"""Component tests for the «Поиск по кластерам» HTTP surface.

The service is stubbed (its arithmetic is unit-tested): what this tier adds is
the wiring — that the route lives under `/skus/{nm_id}` behind the ownership
guard, that a foreign workspace's SKU reads as a 404, and that the page-size
bound is enforced at the edge rather than inside the service.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import date
from typing import Any

import httpx
import pytest

from src.modules.monitoring.deps import get_cluster_analytics, get_product_card_repo
from src.modules.monitoring.schemas import MetricWindow
from src.modules.monitoring.schemas.clusters import SkuClusterItem, SkuClustersResponse
from src.modules.users.deps import get_user_repo
from src.modules.workspaces.contract import WORKSPACE_HEADER
from src.modules.workspaces.deps import get_workspace_repo
from src.modules.workspaces.models import Workspace
from tests.support.auth import auth_headers
from tests.support.fakes import FakeUserRepository, FakeWorkspaceRepository

NM_ID = 953770957
FOREIGN_NM_ID = 999999999


class _StubClusterAnalytics:
    """Answers the two cluster routes, recording their arguments."""

    def __init__(self) -> None:
        """Start with benign answers and no recorded calls."""
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def clusters_for_sku(self, **kwargs: Any) -> SkuClustersResponse:
        """Return one cluster, recording the SKU and window asked for."""
        self.calls.append(("clusters_for_sku", kwargs))
        return SkuClustersResponse(
            nm_id=kwargs["nm_id"],
            window=MetricWindow(start=date(2026, 8, 1), end=date(2026, 8, 13)),
            items=[
                SkuClusterItem(
                    cluster="носки мужские",
                    views=1000,
                    clicks=50,
                    add_to_cart=10,
                    orders=4,
                    spend=250.0,
                    ctr=5.0,
                    cpc=5.0,
                    cpm=250.0,
                    avg_position=6.2,
                    days_count=3,
                    campaign_count=1,
                )
            ],
        )

    @staticmethod
    def normalise_keyword(query: str) -> str:
        """Mirror the real service's normalisation for the enqueue route."""
        return " ".join(query.split())


class _StubProductCardRepo:
    """SKU → workspace registry answering the ownership guard."""

    def __init__(self, owned: set[int]) -> None:
        """Record which SKUs the active workspace owns."""
        self.owned = owned

    async def is_in_workspace(self, *, nm_id: int, workspace_id: Any) -> bool:
        """Report whether this SKU belongs to the caller's workspace."""
        return nm_id in self.owned


@pytest.fixture
def clusters() -> _StubClusterAnalytics:
    """The stub service the cluster routes are wired to."""
    return _StubClusterAnalytics()


@pytest.fixture(autouse=True)
def _wire_clusters(
    override: Callable[[Any, Any], None],
    user_repo: FakeUserRepository,
    workspace_repo: FakeWorkspaceRepository,
    clusters: _StubClusterAnalytics,
) -> None:
    """Wire identity, tenancy, the SKU registry and the stubbed service."""
    override(get_user_repo, user_repo)
    override(get_workspace_repo, workspace_repo)
    override(get_product_card_repo, _StubProductCardRepo({NM_ID}))
    override(get_cluster_analytics, clusters)


@pytest.fixture
def headers(user: Any, workspace: Workspace) -> dict[str, str]:
    """Authenticated headers carrying the active workspace."""
    return {**auth_headers(user.id), WORKSPACE_HEADER: str(workspace.id)}


async def test_the_cluster_block_loads_for_the_pages_sku(
    client: httpx.AsyncClient, headers: dict[str, str], clusters: _StubClusterAnalytics
) -> None:
    """The window passes through and the SKU reaches the service intact."""
    response = await client.get(
        f"/api/v1/monitoring/skus/{NM_ID}/clusters",
        params={"date_from": "2026-08-01", "date_to": "2026-08-13"},
        headers=headers,
    )

    assert response.status_code == 200
    assert response.json()["items"][0]["cluster"] == "носки мужские"
    assert clusters.calls[0][1]["nm_id"] == NM_ID
    assert clusters.calls[0][1]["date_from"] == date(2026, 8, 1)


async def test_a_foreign_workspaces_sku_is_a_404(
    client: httpx.AsyncClient, headers: dict[str, str], clusters: _StubClusterAnalytics
) -> None:
    """The route takes `nm_id` through the ownership guard.

    A SKU the workspace does not own must be indistinguishable from one that does
    not exist — otherwise the endpoint becomes an oracle for other sellers' SKUs.
    """
    response = await client.get(
        f"/api/v1/monitoring/skus/{FOREIGN_NM_ID}/clusters", headers=headers
    )

    assert response.status_code == 404
    assert clusters.calls == []


async def test_an_out_of_range_limit_is_rejected_before_the_service_runs(
    client: httpx.AsyncClient, headers: dict[str, str], clusters: _StubClusterAnalytics
) -> None:
    """A 5000-cluster page is a latency footgun, so the bound is enforced at the edge."""
    response = await client.get(
        f"/api/v1/monitoring/skus/{NM_ID}/clusters", params={"limit": 5000}, headers=headers
    )

    assert response.status_code == 422
    assert clusters.calls == []
