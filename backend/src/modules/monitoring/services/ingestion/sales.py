"""Ingestion of per-item sale/return records (sale-date buyout facts)."""

from __future__ import annotations

from src.core.logging import get_logger
from src.integrations.wildberries.schemas import WBSaleRecord
from src.modules.monitoring.repos import SaleRepository

logger = get_logger(__name__)


class SalesIngestion:
    """Persists the sale/return operations from the Statistics feed."""

    def __init__(self, sale_repo: SaleRepository) -> None:
        """Inject the sale repository used for persistence."""
        self._sales = sale_repo

    async def ingest_sales(self, records: list[WBSaleRecord]) -> int:
        """Persist per-item sale/return records (sale-date buyout facts).

        Records are account-wide (the Statistics feed has no SKU filter) and
        keyed by ``sale_id``, so re-ingesting an overlapping increment is
        idempotent; a batch may repeat an id when WB re-emits a changed record —
        the LAST occurrence (highest ``lastChangeDate``) wins.

        Args:
            records: Raw sale/return operations from the statistics client.

        Returns:
            The number of sale rows persisted.
        """
        deduped: dict[str, WBSaleRecord] = {}
        for record in sorted(records, key=lambda r: r.last_change_date):
            deduped[record.sale_id] = record
        rows: list[dict[str, object]] = [
            {
                "sale_id": record.sale_id,
                "srid": record.srid,
                "nm_id": record.nm_id,
                "sale_date": record.sold_at.date(),
                "is_return": record.is_return,
                "finished_price": record.finished_price,
                "price_with_disc": record.price_with_disc,
                "for_pay": record.for_pay,
                "last_change_date": record.last_change_date,
            }
            for record in deduped.values()
        ]
        count = await self._sales.upsert_many(rows)
        logger.info("Ingested %d sale/return records.", count)
        return count
