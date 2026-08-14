"""«Поиск по кластерам» for one SKU — the stored half and the live probe.

Both halves belong to the block at the bottom of a SKU's monitoring page:

* :meth:`ClusterAnalytics.clusters_for_sku` reads the per-cluster advertising
  history harvested from ``POST /adv/v1/normquery/stats``. It needs no keyword —
  it is the SKU's own list of phrases and shows whenever the page has a SKU.
* :meth:`ClusterAnalytics.probe_position` answers the search box: where this SKU
  ranks in WB's public search for the phrase, right now.

They are never merged into one number. One is a window of paid impressions, the
other a sample taken seconds ago from a personalized, regional result page.

This is the module's only read path that makes an outbound HTTP call, which is
why it is a service of its own rather than a method on ``AnalyticsService``: a
live storefront probe must stay one deliberate call away from the SKU view every
dashboard depends on.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, date, datetime, timedelta
from typing import Any

from redis.exceptions import RedisError

from src.core.exceptions import ValidationError
from src.core.logging import get_logger
from src.core.redis import get_redis
from src.integrations.wildberries.clients.search import SearchProbe, WBPublicSearchClient
from src.modules.monitoring.models import ProductCard
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
from src.modules.monitoring.services.analytics.window import resolve_window

logger = get_logger(__name__)

#: Longest phrase accepted. WB clusters are short phrases; anything longer is a
#: pasted paragraph, and it would only ever find nothing (slowly).
KEYWORD_MAX_LENGTH = 100


def _cache_key(*, query: str, dest: int) -> str:
    """Build the per-phrase probe cache key.

    Keyed by phrase and delivery region ONLY — deliberately not by SKU. The probe
    reads whole result pages, so one scan answers for every SKU in the workspace,
    and a teammate checking the same phrase on another SKU's page reuses it
    instead of spending WB's rate budget again. ``dest`` is part of the key
    because a position is only meaningful for the region it was computed for.
    """
    return f"monitoring:search-position:{dest}:{query.casefold()}"


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
    async def probe_position(
        self,
        *,
        nm_id: int,
        workspace_id: uuid.UUID,
        query: str,
        refresh: bool = False,
    ) -> SkuSearchPositionResponse:
        """Locate the SKU in WB's public search results for ``query``.

        The scan reads whole result pages, so it looks for the workspace's ENTIRE
        catalogue in one pass at no extra cost: the asked-for SKU's rank is the
        answer, and its siblings' ranks come back as context. That also makes the
        cached scan reusable from any SKU's page — the endpoint is throttled by WB
        per IP, so reuse is the difference between an answer and a 429.

        Args:
            nm_id: The SKU the page is about (ownership already proven).
            workspace_id: The caller's active workspace (whose SKUs to look for).
            query: The shopper's phrase, as typed.
            refresh: Skip the cached scan and probe WB again.

        Returns:
            The SKU's rank, or a response with ``position=None`` when it was not
            inside the scanned depth.

        Raises:
            ValidationError: On a blank or over-long phrase.
            IntegrationError: When WB did not answer at all (propagated from the
                client, so the caller never mistakes it for "ranks nowhere").
        """
        term = self._clean_keyword(query)
        nm_ids = await self._cards.list_workspace_nm_ids(workspace_id)
        # The asked-for SKU is always looked for, even if the catalogue registry
        # is somehow behind — the router already proved the caller owns it.
        wanted = set(nm_ids) | {nm_id}

        cached = None if refresh else await self._cached_probe(term)
        if cached is None:
            result = await self._search.find_positions(query=term, nm_ids=wanted)
            cached = self._serialize(result)
            await self._store_probe(term, cached)

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
    def _serialize(result: SearchProbe) -> dict[str, Any]:
        """Flatten a probe into the JSON shape the cache stores."""
        return {
            "normalized_query": result.normalized_query,
            "total_found": result.total_found,
            "positions_scanned": result.positions_scanned,
            "truncated": result.truncated,
            "checked_at": datetime.now(UTC).isoformat(),
            "positions": [
                {
                    "nm_id": position.nm_id,
                    "position": position.position,
                    "page": position.page,
                    "position_on_page": position.position_on_page,
                }
                for position in result.positions
            ],
        }

    async def _cached_probe(self, term: str) -> dict[str, Any] | None:
        """Return a cached scan for the phrase, or ``None``.

        Redis is optional (see :mod:`src.core.redis`): an outage costs a slower,
        throttled probe, not the feature.
        """
        if not self._cache_seconds:
            return None
        try:
            raw = await get_redis().get(_cache_key(query=term, dest=self._search_dest))
        except RedisError:
            logger.warning("Redis unavailable: probing search.wb.ru without the phrase cache.")
            return None
        if raw is None:
            return None
        payload = raw.decode("utf-8") if isinstance(raw, bytes) else raw
        try:
            cached = json.loads(payload)
        except json.JSONDecodeError:
            return None
        return cached if isinstance(cached, dict) else None

    async def _store_probe(self, term: str, probe: dict[str, Any]) -> None:
        """Cache a fresh scan, tolerating a Redis outage."""
        if not self._cache_seconds:
            return
        try:
            await get_redis().set(
                _cache_key(query=term, dest=self._search_dest),
                json.dumps(probe),
                ex=self._cache_seconds,
            )
        except RedisError:
            logger.warning("Redis unavailable: the probe for %r was not cached.", term)

    @staticmethod
    def _vendor_code(card: ProductCard | None) -> str | None:
        """The card's seller article code, or ``None`` when it is not synced yet."""
        return card.vendor_code if card is not None else None

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
