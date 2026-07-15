"""Repository for :class:`SaleRecord` rows (sale-date buyouts/returns)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.modules.monitoring.models import SaleRecord
from src.modules.monitoring.repos.base import BaseRepository

# Sale records feed the SUMMARY listing's window buyout/return totals. The
# matrix's «Выкупы, ₽» is now order-date derived («Заказы, ₽» x «Процент
# выкупа»), so the former per-day sale-date aggregation is no longer needed.
_CONFLICT = ("sale_id",)
_UPDATE = (
    "srid",
    "nm_id",
    "sale_date",
    "is_return",
    "finished_price",
    "price_with_disc",
    "for_pay",
    "last_change_date",
)


@dataclass
class SaleWindowTotal:
    """One SKU's buyout/return totals over a window, aggregated in SQL."""

    buyout_count: int
    buyout_sum: float
    return_count: int


class SaleRepository(BaseRepository):
    """CRUD/read operations for per-item sale/return records."""

    model = SaleRecord

    def __init__(self, session: AsyncSession) -> None:
        """Bind the repository to the request-scoped session."""
        super().__init__(session)

    async def upsert_many(self, rows: list[dict[str, object]]) -> int:
        """Idempotently upsert a batch of sale/return records keyed by ``sale_id``.

        Args:
            rows: Column->value mappings keyed by ``sale_id``.

        Returns:
            The number of rows submitted.
        """
        return await self.bulk_upsert(rows, conflict_columns=_CONFLICT, update_columns=_UPDATE)

    async def window_totals_by_sku(
        self, *, date_from: date, date_to: date
    ) -> dict[int, SaleWindowTotal]:
        """Return every SKU's buyout/return window totals (summary listing).

        Args:
            date_from: Inclusive window start.
            date_to: Inclusive window end.

        Returns:
            ``{nm_id: SaleWindowTotal}`` for every SKU with operations inside
            the window.
        """
        is_sale = SaleRecord.is_return.is_(False)
        is_return = SaleRecord.is_return.is_(True)
        stmt = (
            select(
                SaleRecord.nm_id,
                func.coalesce(func.sum(case((is_sale, 1), else_=0)), 0).label("buyout_count"),
                func.coalesce(
                    func.sum(case((is_sale, SaleRecord.finished_price), else_=0)), 0
                ).label("buyout_sum"),
                func.coalesce(func.sum(case((is_return, 1), else_=0)), 0).label("return_count"),
            )
            .where(SaleRecord.sale_date >= date_from, SaleRecord.sale_date <= date_to)
            .group_by(SaleRecord.nm_id)
        )
        result = await self._session.execute(stmt)
        return {
            row.nm_id: SaleWindowTotal(
                buyout_count=int(row.buyout_count),
                buyout_sum=round(float(row.buyout_sum), 2),
                return_count=int(row.return_count),
            )
            for row in result.all()
        }
