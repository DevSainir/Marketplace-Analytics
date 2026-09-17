"""Ingestion of per-item statistics records — orders and sale/return operations.

Two feeds, one shape: both are account-wide, both paginate on
``lastChangeDate``, and both are keyed by an id WB assigns, so re-ingesting an
overlapping page is idempotent. They are dated by different clocks, which is the
whole reason both exist — an order by the day it was placed, a sale by the day
the customer accepted or returned the item.
"""

from __future__ import annotations

from src.core.logging import get_logger
from src.integrations.wildberries.schemas import WBOrderRecord, WBSaleRecord
from src.modules.monitoring.repos import OrderRepository, SaleRepository

logger = get_logger(__name__)


class SalesIngestion:
    """Persists the sale/return operations from the Statistics feed."""

    def __init__(self, sale_repo: SaleRepository, order_repo: OrderRepository) -> None:
        """Inject the repositories used for persistence."""
        self._sales = sale_repo
        self._orders = order_repo

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

    async def ingest_orders(self, records: list[WBOrderRecord]) -> int:
        """Persist ordered item lines (order-date demand facts).

        Keyed by ``srid``, and the last copy of one wins — a line arrives again
        when the customer cancels it, and the newest ``lastChangeDate`` is the
        one that says so. A cancelled line is stored WITH its flag rather than
        dropped: the day it belongs to had that order, and a row that vanishes
        makes a harvested day look unharvested.

        Args:
            records: Raw order lines from the statistics client.

        Returns:
            How many order rows were persisted.
        """
        deduped: dict[str, WBOrderRecord] = {}
        for record in sorted(records, key=lambda r: r.last_change_date):
            deduped[record.srid] = record
        rows: list[dict[str, object]] = [
            {
                "srid": record.srid,
                "nm_id": record.nm_id,
                "order_date": record.ordered_at.date(),
                "is_cancel": record.is_cancel,
                "price_with_disc": record.price_with_disc,
                "finished_price": record.finished_price,
                "last_change_date": record.last_change_date,
            }
            for record in deduped.values()
        ]
        count = await self._orders.upsert_many(rows)
        logger.info("Ingested %d order records.", count)
        return count
