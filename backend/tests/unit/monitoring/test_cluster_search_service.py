"""Unit tests for «Поиск по кластерам» — one SKU's advertising clusters.

A hand-written fake stands in for the repository, so these pin the service's own
decisions: how the derived rates fall out of the window totals, how a sparse day
series becomes a drawable trend, and that an unreported average ad position stays
null rather than rendering as rank zero.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from src.modules.monitoring.repos.advertising_clusters import ClusterAggregate, ClusterDayPoint
from src.modules.monitoring.services.analytics.clusters import ClusterAnalytics

NM_ID = 953770957


class _FakeClusterRepo:
    """In-memory stand-in for AdvertisingClusterRepository."""

    def __init__(
        self,
        *,
        aggregates: list[ClusterAggregate] | None = None,
        series: list[ClusterDayPoint] | None = None,
        currencies: dict[int, str] | None = None,
    ) -> None:
        self._aggregates = aggregates or []
        self._series = series or []
        self._currencies = currencies or {}
        self.calls: list[dict[str, Any]] = []

    async def aggregate_for_sku(self, **kwargs: Any) -> list[ClusterAggregate]:
        self.calls.append(kwargs)
        return self._aggregates

    async def daily_series_for_sku(self, **kwargs: Any) -> list[ClusterDayPoint]:
        return self._series

    async def campaign_currencies(self, *, campaign_ids: set[int]) -> dict[int, str]:
        return {cid: code for cid, code in self._currencies.items() if cid in campaign_ids}


def _service(*, clusters: _FakeClusterRepo | None = None) -> ClusterAnalytics:
    """Build the service with a fake repository."""
    return ClusterAnalytics(cluster_repo=clusters or _FakeClusterRepo())  # type: ignore[arg-type]


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


async def test_a_cluster_carries_its_campaigns_currency() -> None:
    repo = _FakeClusterRepo(aggregates=[_aggregate(campaign_ids=(7,))], currencies={7: "KGS"})

    response = await _service(clusters=repo).clusters_for_sku(
        nm_id=NM_ID, date_from=None, date_to=None, limit=50
    )

    assert response.items[0].currencies == ["KGS"]
    assert response.items[0].spend == 250.0


async def test_a_cluster_billed_in_two_currencies_has_no_spend_figure() -> None:
    """A RUB and a KGS campaign in one window: their sum would add roubles to сомы."""
    repo = _FakeClusterRepo(
        aggregates=[_aggregate(campaign_ids=(7, 8))], currencies={7: "RUB", 8: "KGS"}
    )

    response = await _service(clusters=repo).clusters_for_sku(
        nm_id=NM_ID, date_from=None, date_to=None, limit=50
    )

    item = response.items[0]
    assert (item.spend, item.cpc, item.cpm) == (None, None, None)
    assert item.ctr == 5.0  # counts are one unit whatever the currency
