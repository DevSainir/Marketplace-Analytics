"""«Поиск по кластерам» for one SKU — the per-cluster advertising history.

Reads the per-cluster history harvested from ``POST /adv/v1/normquery/stats``:
the SKU's own list of the phrases its advertising served in, and what each one
cost and returned. It needs no keyword — it shows whenever the page has a SKU.

A cluster window is a window of PAID impressions, and nothing here claims to be
an organic rank. The live position probe that used to sit beside it was removed
on 2026-08-27; ``docs/monitoring/LIVE_POSITION.md`` records what it measured and
why it went.
"""

from __future__ import annotations

from datetime import date, timedelta

from src.core.logging import get_logger
from src.modules.monitoring.repos import AdvertisingClusterRepository
from src.modules.monitoring.repos.advertising_clusters import ClusterAggregate, ClusterDayPoint
from src.modules.monitoring.schemas.clusters import (
    ClusterDayStat,
    SkuClusterItem,
    SkuClustersResponse,
)
from src.modules.monitoring.schemas.summary import MetricWindow
from src.modules.monitoring.services.analytics.window import resolve_window

logger = get_logger(__name__)


class ClusterAnalytics:
    """Serves a SKU's advertising clusters."""

    def __init__(self, *, cluster_repo: AdvertisingClusterRepository) -> None:
        """Inject the cluster repository."""
        self._clusters = cluster_repo

    # ------------------------------------------------------------------ #
    # Stored: this SKU's advertising, by search cluster
    # ------------------------------------------------------------------ #
    async def clusters_for_sku(
        self,
        *,
        nm_id: int,
        date_from: date | None,
        date_to: date | None,
        limit: int,
    ) -> SkuClustersResponse:
        """Return the SKU's search clusters over the window, with daily trends.

        Args:
            nm_id: WB SKU identifier (already proven to belong to the caller's
                workspace by the router's ownership guard).
            date_from: Optional inclusive window start.
            date_to: Optional inclusive window end.
            limit: Maximum clusters to return.

        Returns:
            The ranked clusters for the SKU.

        Raises:
            ValidationError: On an invalid date window.
        """
        start, end = resolve_window(date_from, date_to)
        aggregates = await self._clusters.aggregate_for_sku(
            nm_id=nm_id, date_from=start, date_to=end, limit=limit
        )
        series = await self._clusters.daily_series_for_sku(
            nm_id=nm_id,
            clusters=[aggregate.cluster for aggregate in aggregates],
            date_from=start,
            date_to=end,
        )
        currencies = await self._clusters.campaign_currencies(
            campaign_ids={cid for aggregate in aggregates for cid in aggregate.campaign_ids}
        )
        series_by_cluster: dict[str, list[ClusterDayPoint]] = {}
        for point in series:
            series_by_cluster.setdefault(point.cluster, []).append(point)

        return SkuClustersResponse(
            nm_id=nm_id,
            window=MetricWindow(start=start, end=end),
            items=[
                self._present(
                    aggregate,
                    series=series_by_cluster.get(aggregate.cluster, []),
                    window=(start, end),
                    currencies=sorted(
                        {currencies[cid] for cid in aggregate.campaign_ids if cid in currencies}
                    ),
                )
                for aggregate in aggregates
            ],
        )

    def _present(
        self,
        agg: ClusterAggregate,
        *,
        series: list[ClusterDayPoint],
        window: tuple[date, date],
        currencies: list[str],
    ) -> SkuClusterItem:
        """Render one cluster aggregate into its response DTO."""
        # CONVERSION-TODO: a cluster whose campaigns bill in two currencies has
        # no spend figure until one side is converted.
        mixed = len(currencies) > 1
        return SkuClusterItem(
            cluster=agg.cluster,
            views=agg.views,
            clicks=agg.clicks,
            add_to_cart=agg.add_to_cart,
            orders=agg.orders,
            spend=None if mixed else round(agg.spend, 2),
            ctr=round(agg.clicks / agg.views * 100, 2) if agg.views else 0.0,
            cpc=None if mixed else (round(agg.spend / agg.clicks, 2) if agg.clicks else 0.0),
            cpm=None if mixed else (round(agg.spend / agg.views * 1000, 2) if agg.views else 0.0),
            currencies=currencies,
            avg_position=round(agg.avg_position, 1) if agg.avg_position is not None else None,
            days_count=agg.days_count,
            campaign_count=agg.campaign_count,
            daily=self._zero_filled(series, window=window),
        )

    @staticmethod
    def _zero_filled(
        series: list[ClusterDayPoint], *, window: tuple[date, date]
    ) -> list[ClusterDayStat]:
        """Expand a sparse day series to every day of the window.

        A day WB reported nothing for is a day with no impressions, so the trend
        must draw it as zero; skipping it lets a chart interpolate straight
        through a pause in the campaign, which reads as traffic that never was.
        """
        by_day = {point.stat_date: point for point in series}
        start, end = window
        filled: list[ClusterDayStat] = []
        for offset in range((end - start).days + 1):
            day = start + timedelta(days=offset)
            point = by_day.get(day)
            filled.append(
                ClusterDayStat(
                    stat_date=day,
                    views=point.views if point else 0,
                    clicks=point.clicks if point else 0,
                    orders=point.orders if point else 0,
                    spend=round(point.spend, 2) if point else 0.0,
                )
            )
        return filled
