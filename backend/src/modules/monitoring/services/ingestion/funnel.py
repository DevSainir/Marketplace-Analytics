"""Ingestion of the daily organic sales funnel (history, cohorts, backfill)."""

from __future__ import annotations

from datetime import date

from src.core.logging import get_logger
from src.integrations.wildberries.schemas import WBFunnelAggregateRow, WBFunnelHistoryRow
from src.modules.monitoring.repos import FunnelRepository

logger = get_logger(__name__)


class FunnelIngestion:
    """Flattens and persists the organic sales-funnel fact family."""

    def __init__(self, funnel_repo: FunnelRepository) -> None:
        """Inject the funnel repository used for persistence."""
        self._funnel = funnel_repo

    async def ingest_sales_funnel(self, rows: list[WBFunnelHistoryRow]) -> int:
        """Flatten and upsert the daily organic sales-funnel history.

        Each product row carries a per-day ``history`` array; every day becomes
        one ``SalesFunnelDaily`` record keyed by ``(stat_date, nm_id)`` — the
        true daily granularity the baseline-demand normalization relies on.

        Args:
            rows: Raw per-product funnel-history rows from the analytics client.

        Returns:
            The number of daily funnel rows persisted.
        """
        # NOTE: ``orderSum``/``buyoutSum`` from WB are intentionally dropped —
        # the ₽ volumes are now derived from ``count x seller_price`` (see the
        # matrix and price snapshot), not stored on the funnel row.
        #
        # ``buyout_count`` is written here only to SEED a newly inserted day
        # (this feed serves the last 7 days, so its buyout counts are always the
        # immature ones); the cohort pass owns the column thereafter — see
        # ``FunnelRepository._UPDATE`` and :meth:`ingest_funnel_cohorts`.
        flattened: list[dict[str, object]] = [
            {
                "stat_date": day.stat_date,
                "nm_id": row.nm_id,
                "open_count": day.open_count,
                "cart_count": day.cart_count,
                "order_count": day.order_count,
                "buyout_count": day.buyout_count,
                "add_to_wishlist": day.add_to_wishlist,
                "cart_conversion": day.cart_conversion,
                "order_conversion": day.order_conversion,
                "buyout_conversion": day.buyout_conversion,
            }
            for row in rows
            for day in row.history
        ]
        count = await self._funnel.upsert_many(flattened)
        logger.info("Ingested %d daily sales-funnel rows.", count)
        return count

    async def ingest_funnel_cohorts(
        self, day: date, rows: list[WBFunnelAggregateRow], *, nm_ids: set[int] | None = None
    ) -> int:
        """Refresh one order-date cohort's matured buyout/cancel counts.

        Args:
            day: The cohort day these aggregate rows describe.
            rows: Per-product aggregate rows for that single-day period.
            nm_ids: Optional SKU filter. WB ignores the request's ``nmIDs`` and
                answers with the whole catalogue, so a targeted refresh narrows
                the response here.

        Returns:
            The number of cohort days refreshed.
        """
        flattened: list[dict[str, object]] = [
            {
                "stat_date": day,
                "nm_id": row.nm_id,
                "buyout_count": row.statistic.selected.buyout_count,
                "cancel_count": row.statistic.selected.cancel_count,
            }
            for row in rows
            if nm_ids is None or row.nm_id in nm_ids
        ]
        count = await self._funnel.update_cohorts(flattened)
        logger.info("Refreshed %d funnel cohort rows for %s.", count, day)
        return count

    async def ingest_funnel_backfill(
        self, day: date, rows: list[WBFunnelAggregateRow], *, nm_ids: set[int]
    ) -> int:
        """INSERT one historical day's funnel rows from the period aggregate.

        The daily history feed only serves the last 7 days, so days beyond it
        can only be reconstructed from the aggregate endpoint called with
        ``start == end == day``. Unlike :meth:`ingest_funnel_cohorts` (which
        UPDATEs cohort columns on existing rows), this path INSERTs full rows —
        the caller must pass only ``(day, nm_id)`` pairs that do NOT yet exist,
        and only for SKUs it owns (the aggregate answers for the whole
        catalogue regardless of the request).

        Only rows with actual activity are written: the aggregate answers for
        every product on any date, and inserting all-zero rows would fabricate
        funnel days the seller never traded (the matrix correctly shows «—»
        for absent days).

        Conversions are computed from the counts (the aggregate carries them
        nested per-period, but the counts are the definition): cart% =
        cart/open, order% = order/cart, buyout% = buyout/(buyout+cancel) —
        the same matured ratio the cohort pass converges on.

        Args:
            day: The historical day being reconstructed.
            rows: Per-product aggregate rows for that single-day period.
            nm_ids: SKUs to insert — the workspace's own, minus already-present.

        Returns:
            The number of funnel rows inserted.
        """

        def _pct(numerator: int, denominator: int) -> float:
            return round(numerator / denominator * 100, 2) if denominator else 0.0

        flattened: list[dict[str, object]] = []
        for row in rows:
            if row.nm_id not in nm_ids:
                continue
            sel = row.statistic.selected
            if not sel.has_activity:
                continue
            flattened.append(
                {
                    "stat_date": day,
                    "nm_id": row.nm_id,
                    "open_count": sel.open_count,
                    "cart_count": sel.cart_count,
                    "order_count": sel.order_count,
                    "buyout_count": sel.buyout_count,
                    "cancel_count": sel.cancel_count,
                    "add_to_wishlist": sel.add_to_wishlist,
                    "cart_conversion": _pct(sel.cart_count, sel.open_count),
                    "order_conversion": _pct(sel.order_count, sel.cart_count),
                    "buyout_conversion": _pct(
                        sel.buyout_count, sel.buyout_count + sel.cancel_count
                    ),
                }
            )
        count = await self._funnel.upsert_many(flattened)
        logger.info("Backfilled %d funnel rows for %s.", count, day)
        return count
