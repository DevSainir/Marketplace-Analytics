"""Unit tests for «Поиск по кластерам» — one SKU's clusters and its live rank.

Hand-written fakes stand in for the repository and the WB probe, so these pin the
service's own decisions: how a sparse day series becomes a drawable trend, what a
phrase is allowed to be, and the difference between "this SKU ranks nowhere in
the depth we scanned" and a rank we actually found.
"""

from __future__ import annotations

import uuid
from datetime import date
from typing import Any

import pytest

from src.core.exceptions import ValidationError
from src.integrations.wildberries.clients.search import SearchPosition, SearchProbe
from src.modules.monitoring.models import ProductCard
from src.modules.monitoring.repos.advertising_clusters import ClusterAggregate, ClusterDayPoint
from src.modules.monitoring.services.analytics.clusters import ClusterAnalytics

WORKSPACE = uuid.UUID("018f4e2a-0000-7000-8000-000000000001")
NM_ID = 953770957
SIBLING = 144178006


class _FakeClusterRepo:
    """In-memory stand-in for AdvertisingClusterRepository."""

    def __init__(
        self,
        *,
        aggregates: list[ClusterAggregate] | None = None,
        series: list[ClusterDayPoint] | None = None,
    ) -> None:
        self._aggregates = aggregates or []
        self._series = series or []
        self.calls: list[dict[str, Any]] = []

    async def aggregate_for_sku(self, **kwargs: Any) -> list[ClusterAggregate]:
        self.calls.append(kwargs)
        return self._aggregates

    async def daily_series_for_sku(self, **kwargs: Any) -> list[ClusterDayPoint]:
        return self._series


class _FakeCardRepo:
    """In-memory stand-in for ProductCardRepository."""

    def __init__(self, *, nm_ids: list[int] | None = None) -> None:
        self._nm_ids = nm_ids if nm_ids is not None else [NM_ID, SIBLING]
        self.requested: list[set[int]] = []

    async def get_by_ids(self, nm_ids: Any) -> dict[int, ProductCard]:
        ids = set(nm_ids)
        self.requested.append(ids)
        return {
            nm_id: ProductCard(nm_id=nm_id, vendor_code=f"M-{nm_id}", title="Носки")
            for nm_id in ids
        }

    async def list_workspace_nm_ids(self, workspace_id: uuid.UUID) -> list[int]:
        return list(self._nm_ids)


class _FakeSearchClient:
    """Records probes it was asked for and replays a canned scan."""

    def __init__(self, probe: SearchProbe | None = None) -> None:
        self.probe = probe or SearchProbe(
            query="носки",
            normalized_query="мужские носки",
            total_found=1000,
            pages_scanned=1,
            positions_scanned=100,
            truncated=True,
            positions=[
                SearchPosition(nm_id=NM_ID, position=7, page=1, position_on_page=7),
                SearchPosition(nm_id=SIBLING, position=41, page=1, position_on_page=41),
            ],
        )
        self.calls: list[dict[str, Any]] = []

    async def find_positions(self, **kwargs: Any) -> SearchProbe:
        self.calls.append(kwargs)
        return self.probe


def _service(
    *,
    clusters: _FakeClusterRepo | None = None,
    cards: _FakeCardRepo | None = None,
    search: _FakeSearchClient | None = None,
) -> ClusterAnalytics:
    """Build the service with fakes and the probe cache disabled.

    ``cache_seconds=0`` keeps Redis out of the unit tier entirely — caching is a
    wiring concern, not arithmetic.
    """
    return ClusterAnalytics(
        cluster_repo=clusters or _FakeClusterRepo(),  # type: ignore[arg-type]
        product_card_repo=cards or _FakeCardRepo(),  # type: ignore[arg-type]
        search_client=search or _FakeSearchClient(),  # type: ignore[arg-type]
        cache_seconds=0,
        search_dest=-1257786,
    )


def _aggregate(**overrides: Any) -> ClusterAggregate:
    """A cluster aggregate with plausible defaults."""
    defaults: dict[str, Any] = {
        "cluster": "носки мужские",
        "days_count": 3,
        "campaign_count": 1,
        "views": 1000,
        "clicks": 50,
        "add_to_cart": 10,
        "orders": 4,
        "spend": 250.0,
        "avg_position": 6.25,
    }
    return ClusterAggregate(**{**defaults, **overrides})


# --------------------------------------------------------------------------- #
# Stored: the SKU's clusters
# --------------------------------------------------------------------------- #
async def test_derived_rates_come_from_the_window_totals() -> None:
    """CTR/CPC/CPM are recomputed from the totals, not averaged per day."""
    repo = _FakeClusterRepo(aggregates=[_aggregate(views=1000, clicks=50, spend=250.0)])

    response = await _service(clusters=repo).clusters_for_sku(
        nm_id=NM_ID, date_from=date(2026, 8, 1), date_to=date(2026, 8, 3), limit=50
    )

    item = response.items[0]
    assert item.ctr == 5.0
    assert item.cpc == 5.0
    assert item.cpm == 250.0


async def test_the_read_is_scoped_to_the_sku_the_page_is_about() -> None:
    """The block is per-SKU: a shared cluster must not drag in other SKUs' traffic."""
    repo = _FakeClusterRepo(aggregates=[_aggregate()])

    await _service(clusters=repo).clusters_for_sku(
        nm_id=NM_ID, date_from=None, date_to=None, limit=50
    )

    assert repo.calls[0]["nm_id"] == NM_ID


async def test_an_unreported_average_position_stays_null() -> None:
    """None means "WB never reported a position", which is not position zero."""
    repo = _FakeClusterRepo(aggregates=[_aggregate(avg_position=None)])

    response = await _service(clusters=repo).clusters_for_sku(
        nm_id=NM_ID, date_from=None, date_to=None, limit=50
    )

    assert response.items[0].avg_position is None


async def test_days_wb_reported_nothing_for_are_returned_as_zeros() -> None:
    """A gap in the payload is a day with no impressions, and must draw as zero.

    Omitting it instead lets a trend interpolate straight through a pause in the
    campaign, which reads as steady traffic that never happened.
    """
    repo = _FakeClusterRepo(
        aggregates=[_aggregate()],
        series=[
            ClusterDayPoint(
                cluster="носки мужские",
                stat_date=date(2026, 8, 3),
                views=400,
                clicks=20,
                orders=2,
                spend=100.0,
            )
        ],
    )

    response = await _service(clusters=repo).clusters_for_sku(
        nm_id=NM_ID, date_from=date(2026, 8, 1), date_to=date(2026, 8, 3), limit=50
    )

    assert [(point.stat_date, point.views) for point in response.items[0].daily] == [
        (date(2026, 8, 1), 0),
        (date(2026, 8, 2), 0),
        (date(2026, 8, 3), 400),
    ]


# --------------------------------------------------------------------------- #
# Live: this SKU's rank
# --------------------------------------------------------------------------- #
async def test_the_probe_reports_this_skus_rank_and_its_siblings_separately() -> None:
    """The asked-for SKU is the answer; the others are context from the same scan.

    Mixing them into one list would make the seller hunt for their own card in a
    ranking that is supposed to be about it.
    """
    search = _FakeSearchClient()

    response = await _service(search=search).probe_position(
        nm_id=NM_ID, workspace_id=WORKSPACE, query="носки"
    )

    assert (response.position, response.page, response.position_on_page) == (7, 1, 7)
    assert [other.nm_id for other in response.other_skus] == [SIBLING]
    assert response.other_skus[0].vendor_code == f"M-{SIBLING}"
    assert response.normalized_query == "мужские носки"


async def test_a_sku_outside_the_scanned_depth_has_no_position() -> None:
    """None, not a large number: "not in the first N" is not a rank.

    `truncated` is what tells the UI a deeper rank is still possible, so the pair
    has to survive together.
    """
    search = _FakeSearchClient(
        SearchProbe(
            query="носки",
            normalized_query="носки",
            total_found=90000,
            pages_scanned=3,
            positions_scanned=300,
            truncated=True,
            positions=[],
        )
    )

    response = await _service(search=search).probe_position(
        nm_id=NM_ID, workspace_id=WORKSPACE, query="носки"
    )

    assert response.position is None
    assert response.positions_scanned == 300
    assert response.truncated is True


async def test_the_scan_looks_for_the_whole_catalogue_in_one_pass() -> None:
    """One scan answers for every SKU, so it is asked for all of them at once.

    WB throttles this endpoint per IP; a per-SKU scan of the same pages would
    spend the budget N times for information already on the page.
    """
    search = _FakeSearchClient()

    await _service(search=search).probe_position(nm_id=NM_ID, workspace_id=WORKSPACE, query="носки")

    assert search.calls[0]["nm_ids"] == {NM_ID, SIBLING}


async def test_the_pages_own_sku_is_looked_for_even_if_the_registry_lags() -> None:
    """Ownership was already proven by the router, so the SKU is never dropped."""
    search = _FakeSearchClient()

    await _service(cards=_FakeCardRepo(nm_ids=[]), search=search).probe_position(
        nm_id=NM_ID, workspace_id=WORKSPACE, query="носки"
    )

    assert search.calls[0]["nm_ids"] == {NM_ID}


@pytest.mark.parametrize("phrase", ["", "   ", "а" * 101])
async def test_an_unusable_phrase_is_rejected_before_wb_is_called(phrase: str) -> None:
    """An empty phrase has no ranking, and a pasted paragraph can only find nothing."""
    search = _FakeSearchClient()

    with pytest.raises(ValidationError):
        await _service(search=search).probe_position(
            nm_id=NM_ID, workspace_id=WORKSPACE, query=phrase
        )

    assert search.calls == []


async def test_a_phrase_is_collapsed_to_single_spaces() -> None:
    """«носки   мужские» and «носки мужские» are the same query to WB."""
    search = _FakeSearchClient()

    await _service(search=search).probe_position(
        nm_id=NM_ID, workspace_id=WORKSPACE, query="  носки   мужские "
    )

    assert search.calls[0]["query"] == "носки мужские"
