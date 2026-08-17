"""Component tests for the «Поиск по кластерам» HTTP surface.

The service is stubbed (its arithmetic is unit-tested): what this tier adds is
the wiring — that both routes live under `/skus/{nm_id}` behind the ownership
guard, that query validation rejects nonsense before any WB call, and that a
failed live probe arrives as 502 rather than as an empty ranking.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, date, datetime
from typing import Any

import httpx
import pytest

from src.modules.monitoring.deps import get_cluster_analytics, get_product_card_repo
from src.modules.monitoring.schemas import MetricWindow
from src.modules.monitoring.schemas.clusters import (
    OtherSkuPosition,
    SkuClusterItem,
    SkuClustersResponse,
    SkuSearchPositionResponse,
)
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
        #: Set to raise from the read (an unexpected failure).
        self.probe_error: Exception | None = None
        #: False when no sample is stored for the phrase — the 404 case.
        self.has_sample = True

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

    async def cached_position(self, **kwargs: Any) -> SkuSearchPositionResponse | None:
        """Return the stored rank, ``None`` when there is none, or raise."""
        self.calls.append(("cached_position", kwargs))
        if self.probe_error is not None:
            raise self.probe_error
        if not self.has_sample:
            return None
        return SkuSearchPositionResponse(
            nm_id=kwargs["nm_id"],
            query=kwargs["query"],
            normalized_query="мужские носки",
            checked_at=datetime(2026, 8, 14, 9, 0, tzinfo=UTC),
            total_found=1000,
            positions_scanned=300,
            truncated=True,
            position=7,
            page=1,
            position_on_page=7,
            other_skus=[OtherSkuPosition(nm_id=144178006, vendor_code="M-TRX01-BEJ", position=41)],
        )


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


@pytest.mark.parametrize("path", ["clusters", "search-position"])
async def test_a_foreign_workspaces_sku_is_a_404(
    client: httpx.AsyncClient,
    headers: dict[str, str],
    clusters: _StubClusterAnalytics,
    path: str,
) -> None:
    """Both routes take `nm_id` through the ownership guard.

    A SKU the workspace does not own must be indistinguishable from one that does
    not exist — otherwise the endpoints become an oracle for other sellers' SKUs.
    """
    response = await client.get(
        f"/api/v1/monitoring/skus/{FOREIGN_NM_ID}/{path}",
        params={"query": "носки"},
        headers=headers,
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


async def test_the_stored_position_returns_this_skus_rank_and_its_siblings(
    client: httpx.AsyncClient, headers: dict[str, str], clusters: _StubClusterAnalytics
) -> None:
    """The rank, its page, WB's normalized phrase, and the other SKUs found."""
    response = await client.get(
        f"/api/v1/monitoring/skus/{NM_ID}/search-position",
        params={"query": "носки"},
        headers=headers,
    )

    body = response.json()
    assert response.status_code == 200
    assert body["position"] == 7
    assert body["normalized_query"] == "мужские носки"
    assert body["other_skus"][0]["position"] == 41
    assert body["truncated"] is True


async def test_the_probe_rejects_an_empty_phrase(
    client: httpx.AsyncClient, headers: dict[str, str], clusters: _StubClusterAnalytics
) -> None:
    """WB has no ranking for an empty phrase, so the request never leaves here."""
    response = await client.get(
        f"/api/v1/monitoring/skus/{NM_ID}/search-position", params={"query": ""}, headers=headers
    )

    assert response.status_code == 422
    assert clusters.calls == []


async def test_the_read_passes_the_active_workspace_to_the_service(
    client: httpx.AsyncClient,
    headers: dict[str, str],
    clusters: _StubClusterAnalytics,
    workspace: Workspace,
) -> None:
    """The scan looks for the workspace's catalogue, so the header has to reach it.

    Without it the read could only ever describe the one SKU, losing the sibling
    ranks the same stored scan already contains.
    """
    await client.get(
        f"/api/v1/monitoring/skus/{NM_ID}/search-position",
        params={"query": "носки"},
        headers=headers,
    )

    assert clusters.calls[0][1]["workspace_id"] == workspace.id


async def test_a_phrase_with_no_stored_sample_is_a_404_not_an_empty_ranking(
    client: httpx.AsyncClient, headers: dict[str, str], clusters: _StubClusterAnalytics
) -> None:
    """ "Nobody has checked this" must never render as "your SKU does not rank".

    The two are opposite conclusions for a seller deciding whether to raise a bid,
    and this path no longer calls WB at all: the check is a task now, so an
    unchecked phrase simply has nothing stored.
    """
    clusters.has_sample = False

    response = await client.get(
        f"/api/v1/monitoring/skus/{NM_ID}/search-position",
        params={"query": "носки"},
        headers=headers,
    )

    assert response.status_code == 404


@pytest.mark.parametrize("path", ["clusters", "search-position"])
async def test_the_cluster_routes_require_an_access_token(
    client: httpx.AsyncClient, workspace: Workspace, path: str
) -> None:
    """Both routes sit behind the module's auth guard."""
    response = await client.get(
        f"/api/v1/monitoring/skus/{NM_ID}/{path}",
        params={"query": "носки"},
        headers={WORKSPACE_HEADER: str(workspace.id)},
    )

    assert response.status_code in {401, 403}


class _FinishedAsyncResult:
    """Celery's ``AsyncResult`` without its Redis result backend.

    The route asks Celery whether the check has finished, and Celery answers from
    the result backend — a live Redis this tier deliberately does not have. Faking
    it keeps the route, the marker round-trip and the response model real; whether
    Celery reports state correctly is Celery's problem, covered for real in
    ``tests/integration/celery/test_task_wiring.py``.
    """

    def __init__(self, task_id: str, app: Any = None) -> None:
        """Record the polled id and report a finished, successful check."""
        self.id = task_id

    def ready(self) -> bool:
        """Report the check as finished."""
        return True

    def successful(self) -> bool:
        """Report the check as successful."""
        return True


async def test_a_position_check_is_queued_and_remembered_for_this_sku(
    client: httpx.AsyncClient,
    headers: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """«Проверить позицию» queues the work and leaves a marker behind it.

    The marker is what makes a check survive leaving the page: the GET beside this
    finds it without the tab that started the check, so a reload re-attaches
    instead of showing nothing while the worker carries on.
    """
    monkeypatch.setattr(
        "src.modules.monitoring.routers.clusters.probe_position.delay",
        lambda workspace_id, nm_id, query: type("Task", (), {"id": "check-1"})(),
    )
    monkeypatch.setattr("src.modules.monitoring.routers.clusters.AsyncResult", _FinishedAsyncResult)

    # Before anything is queued the panel must get a plain null, not an error:
    # it asks this on every mount, including the first one.
    before = await client.get(
        f"/api/v1/monitoring/skus/{NM_ID}/search-position/checks", headers=headers
    )

    queued = await client.post(
        f"/api/v1/monitoring/skus/{NM_ID}/search-position/checks",
        params={"query": "  носки   мужские "},
        headers=headers,
    )
    resumed = await client.get(
        f"/api/v1/monitoring/skus/{NM_ID}/search-position/checks", headers=headers
    )

    assert (before.status_code, before.json()) == (200, None)
    assert queued.status_code == 202
    # Normalised on the way in, so the task argument, the Redis key and the label
    # the panel shows cannot drift apart.
    assert queued.json() == {"task_id": "check-1", "query": "носки мужские"}
    body = resumed.json()
    assert body["task_id"] == "check-1"
    assert body["query"] == "носки мужские"


async def test_a_check_cannot_be_queued_for_a_sku_the_workspace_does_not_own(
    client: httpx.AsyncClient,
    headers: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The ownership guard covers the write path too, not only the reads.

    An unowned SKU must be indistinguishable from one that does not exist —
    otherwise the endpoint answers "that card is someone else's".
    """
    enqueued: list[object] = []
    monkeypatch.setattr(
        "src.modules.monitoring.routers.clusters.probe_position.delay",
        lambda *args: enqueued.append(args) or type("Task", (), {"id": "check-2"})(),
    )

    response = await client.post(
        "/api/v1/monitoring/skus/999999999/search-position/checks",
        params={"query": "носки"},
        headers=headers,
    )

    assert response.status_code == 404
    # Nothing was queued: WB's rate budget is not spent on an unowned SKU.
    assert enqueued == []
