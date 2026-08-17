"""«Поиск по кластерам» for one SKU — the stored half and the live probe.

Both halves belong to the block at the bottom of a SKU's monitoring page:

* :meth:`ClusterAnalytics.clusters_for_sku` reads the per-cluster advertising
  history harvested from ``POST /adv/v1/normquery/stats``. It needs no keyword —
  it is the SKU's own list of phrases and shows whenever the page has a SKU.
* :meth:`ClusterAnalytics.cached_position` answers the search box: where this SKU
  ranked when the phrase was last checked. The checking itself is a Celery task
  (``monitoring.probe_position``) because WB refuses roughly every second attempt
  and outlasting that takes minutes — this reads what the task stored.

They are never merged into one number. One is a window of paid impressions, the
other a sample taken seconds ago from a personalized, regional result page.

This is the module's only read path that makes an outbound HTTP call, which is
why it is a service of its own rather than a method on ``AnalyticsService``: a
live storefront probe must stay one deliberate call away from the SKU view every
dashboard depends on.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta

from src.core.exceptions import ValidationError
from src.core.logging import get_logger
from src.integrations.wildberries.clients.search import WBPublicSearchClient
from src.modules.monitoring.models import ProductCard
from src.modules.monitoring.models.pinned_keywords import (
    KEYWORD_MAX_LENGTH as _KEYWORD_MAX_LENGTH,
)
from src.modules.monitoring.repos import (
    AdvertisingClusterRepository,
    ProductCardRepository,
)
from src.modules.monitoring.repos.advertising_clusters import ClusterAggregate, ClusterDayPoint
from src.modules.monitoring.schemas.clusters import (
    ClusterDayStat,
    OtherSkuPosition,
    SkuClusterItem,
    SkuClustersResponse,
    SkuSearchPositionResponse,
)
from src.modules.monitoring.schemas.summary import MetricWindow
from src.modules.monitoring.services.analytics.position_cache import (
    read_probe_result,
)
from src.modules.monitoring.services.analytics.window import resolve_window

logger = get_logger(__name__)

#: Longest phrase accepted. WB clusters are short phrases; anything longer is a
#: pasted paragraph, and it would only ever find nothing (slowly). Re-exported
#: from the model so the probe's limit and the ``pinned_keyword.keyword`` column
#: width cannot drift apart — a phrase that pins but cannot be checked, or the
#: reverse, is worse than either bound alone.
KEYWORD_MAX_LENGTH = _KEYWORD_MAX_LENGTH


class ClusterAnalytics:
    """Serves a SKU's advertising clusters and its live search position."""

    def __init__(
        self,
        *,
        cluster_repo: AdvertisingClusterRepository,
        product_card_repo: ProductCardRepository,
        search_client: WBPublicSearchClient,
        cache_seconds: int,
        search_dest: int,
    ) -> None:
        """Inject the cluster repository, the SKU registry and the live probe."""
        self._clusters = cluster_repo
        self._cards = product_card_repo
        self._search = search_client
        self._cache_seconds = cache_seconds
        self._search_dest = search_dest

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
    ) -> SkuClusterItem:
        """Render one cluster aggregate into its response DTO."""
        return SkuClusterItem(
            cluster=agg.cluster,
            views=agg.views,
            clicks=agg.clicks,
            add_to_cart=agg.add_to_cart,
            orders=agg.orders,
            spend=round(agg.spend, 2),
            ctr=round(agg.clicks / agg.views * 100, 2) if agg.views else 0.0,
            cpc=round(agg.spend / agg.clicks, 2) if agg.clicks else 0.0,
            cpm=round(agg.spend / agg.views * 1000, 2) if agg.views else 0.0,
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

    # ------------------------------------------------------------------ #
    # Live: where this SKU ranks in WB search right now
    # ------------------------------------------------------------------ #
    async def cached_position(
        self,
        *,
        nm_id: int,
        workspace_id: uuid.UUID,
        query: str,
    ) -> SkuSearchPositionResponse | None:
        """Return the STORED sample for ``query``, or ``None`` if there is none.

        This path makes NO outbound call any more, and that is the design rather
        than an optimisation. WB refuses roughly every second attempt from a
        shared residential exit, each retry has to wait out a throttle window, and
        an HTTP request cannot honestly be held open for that; worse, a seller who
        left the page lost the work. Getting the answer is now
        ``monitoring.probe_position``'s job — it writes here, and this reads.

        One scan still answers for the whole workspace: it looks for every SKU in
        the catalogue, so a colleague checking the same phrase from another SKU's
        page is served from the same sample instead of spending WB's budget again.

        Args:
            nm_id: The SKU the page is about (ownership already proven).
            workspace_id: The caller's active workspace, for the sibling ranks.
            query: The shopper's phrase, as typed.

        Returns:
            The SKU's rank, a response with ``position=None`` when the scan did
            not find it inside its depth, or ``None`` when no scan is stored —
            which the router turns into "not checked yet", NOT "ranks nowhere".

        Raises:
            ValidationError: On a blank or over-long phrase.
        """
        term = self._clean_keyword(query)
        cached = await read_probe_result(
            term, dest=self._search_dest, ttl_seconds=self._cache_seconds
        )
        if cached is None:
            return None

        found = {int(row["nm_id"]): row for row in cached["positions"]}
        mine = found.get(nm_id)
        others = [row for row in cached["positions"] if int(row["nm_id"]) != nm_id]
        cards = await self._cards.get_by_ids({int(row["nm_id"]) for row in others})

        return SkuSearchPositionResponse(
            nm_id=nm_id,
            query=term,
            normalized_query=cached["normalized_query"] or None,
            checked_at=datetime.fromisoformat(cached["checked_at"]),
            total_found=int(cached["total_found"]),
            positions_scanned=int(cached["positions_scanned"]),
            truncated=bool(cached["truncated"]),
            position=int(mine["position"]) if mine else None,
            page=int(mine["page"]) if mine else None,
            position_on_page=int(mine["position_on_page"]) if mine else None,
            other_skus=[
                OtherSkuPosition(
                    nm_id=int(row["nm_id"]),
                    vendor_code=self._vendor_code(cards.get(int(row["nm_id"]))),
                    position=int(row["position"]),
                )
                for row in others
            ],
        )

    @staticmethod
    def _vendor_code(card: ProductCard | None) -> str | None:
        """The card's seller article code, or ``None`` when it is not synced yet."""
        return card.vendor_code if card is not None else None

    @staticmethod
    def normalise_keyword(query: str) -> str:
        """Public alias of :meth:`_clean_keyword` for callers that only validate.

        The route that ENQUEUES a check has to normalise the phrase before it
        becomes a task argument and a Redis key, without touching the store.
        """
        return ClusterAnalytics._clean_keyword(query)

    @staticmethod
    def _clean_keyword(query: str) -> str:
        """Trim and validate a typed phrase.

        Args:
            query: The raw input.

        Returns:
            The trimmed phrase, inner whitespace collapsed.

        Raises:
            ValidationError: When blank (WB has no ranking for an empty phrase)
                or longer than :data:`KEYWORD_MAX_LENGTH`.
        """
        term = " ".join(query.split())
        if not term:
            raise ValidationError("Введите поисковый запрос.")
        if len(term) > KEYWORD_MAX_LENGTH:
            raise ValidationError(
                f"Поисковый запрос не может быть длиннее {KEYWORD_MAX_LENGTH} символов."
            )
        return term
