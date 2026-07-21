"""Ingestion of daily seller/customer price snapshots."""

from __future__ import annotations

from datetime import date

from src.core.logging import get_logger
from src.integrations.wildberries.schemas import WBCardProduct, WBPriceGood
from src.modules.monitoring.repos import PriceRepository

logger = get_logger(__name__)


class PriceIngestion:
    """Persists the daily per-SKU seller/customer price snapshot."""

    def __init__(self, price_repo: PriceRepository) -> None:
        """Inject the price repository used for persistence."""
        self._prices = price_repo

    async def ingest_prices(
        self,
        goods: list[WBPriceGood],
        customer: list[WBCardProduct],
        *,
        snapshot_date: date,
        nm_ids: list[int] | None = None,
    ) -> int:
        """Persist a daily seller/customer price snapshot per SKU.

        Joins the seller ``discountedPrice`` (Prices & Discounts API) with the
        final customer price (``card.wb.ru``) by ``nm_id`` into one row per SKU
        for ``snapshot_date``. A SKU present in only one source still yields a
        row (the missing side is ``NULL``); the matrix prices only these exact
        snapshot days — days without a snapshot stay unpriced.

        Snapshots are written ONLY for ``nm_ids`` — the SKUs this harvest
        covered. This matters for a single-SKU refresh: the seller ``goods`` feed
        returns the whole account, but the customer feed is fetched only for the
        harvested SKUs, so writing every good would stamp ``NULL`` customer
        prices over the other SKUs' snapshots. When ``nm_ids`` is ``None`` (a
        full harvest that did not scope), every good is written.

        Args:
            goods: Raw seller pricing records from the prices client.
            customer: Raw storefront card products from the card client.
            snapshot_date: The Moscow-time calendar day the snapshot represents.
            nm_ids: The harvested SKUs to snapshot; ``None`` writes all goods.

        Returns:
            The number of price snapshot rows persisted.
        """
        seller_by_sku = {good.nm_id: good.seller_price for good in goods}
        customer_by_sku = {product.nm_id: product.customer_price for product in customer}

        target_ids = (
            sorted(nm_ids)
            if nm_ids is not None
            else sorted(seller_by_sku.keys() | customer_by_sku.keys())
        )
        rows: list[dict[str, object]] = [
            {
                "stat_date": snapshot_date,
                "nm_id": nm_id,
                "seller_price": seller_by_sku.get(nm_id),
                "customer_price": customer_by_sku.get(nm_id),
            }
            for nm_id in target_ids
            if seller_by_sku.get(nm_id) is not None or customer_by_sku.get(nm_id) is not None
        ]
        count = await self._prices.upsert_many(rows)
        logger.info("Ingested %d price snapshot rows for %s.", count, snapshot_date)
        return count
