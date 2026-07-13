"""Repository for :class:`PriceSnapshot` rows."""

from __future__ import annotations

from datetime import date

from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.modules.monitoring.models import PriceSnapshot
from src.modules.monitoring.repos.base import BaseRepository

_CONFLICT = ("stat_date", "nm_id")
_UPDATE = ("seller_price", "customer_price")


class PriceRepository(BaseRepository):
    """CRUD/read operations for daily seller/customer price snapshots."""

    model = PriceSnapshot

    def __init__(self, session: AsyncSession) -> None:
        """Bind the repository to the request-scoped session."""
        super().__init__(session)

    async def upsert_many(self, rows: list[dict[str, object]]) -> int:
        """Idempotently upsert a batch of daily price snapshot rows.

        Args:
            rows: Column->value mappings keyed by ``(stat_date, nm_id)``.

        Returns:
            The number of rows submitted.
        """
        return await self.bulk_upsert(rows, conflict_columns=_CONFLICT, update_columns=_UPDATE)

    async def list_for_sku(
        self, *, nm_id: int, date_from: date, date_to: date
    ) -> list[PriceSnapshot]:
        """Return one SKU's price snapshots within an inclusive window.

        Ordered ascending by date; the matrix prices only the exact snapshot
        days (days without a snapshot render unpriced).

        Args:
            nm_id: WB SKU identifier.
            date_from: Inclusive window start.
            date_to: Inclusive window end.

        Returns:
            Price snapshot rows ordered by ascending date.
        """
        stmt = (
            select(PriceSnapshot)
            .where(
                PriceSnapshot.nm_id == nm_id,
                PriceSnapshot.stat_date >= date_from,
                PriceSnapshot.stat_date <= date_to,
            )
            .order_by(PriceSnapshot.stat_date)
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def latest_by_sku(self, *, date_to: date) -> dict[int, tuple[float | None, float | None]]:
        """Return each SKU's most recent ``(seller, customer)`` price on/before a day.

        Aggregated in SQL for the summary listing (which prices window-total
        counts against the latest known price — the per-day matrix carries prices
        forward per day instead).

        Args:
            date_to: Inclusive upper bound on the snapshot day.

        Returns:
            ``{nm_id: (seller_price, customer_price)}`` for every SKU with a
            snapshot on or before ``date_to``.
        """
        latest = (
            select(
                PriceSnapshot.nm_id.label("nm_id"),
                func.max(PriceSnapshot.stat_date).label("latest_day"),
            )
            .where(PriceSnapshot.stat_date <= date_to)
            .group_by(PriceSnapshot.nm_id)
            .subquery()
        )
        stmt = select(
            PriceSnapshot.nm_id,
            PriceSnapshot.seller_price,
            PriceSnapshot.customer_price,
        ).join(
            latest,
            and_(
                PriceSnapshot.nm_id == latest.c.nm_id,
                PriceSnapshot.stat_date == latest.c.latest_day,
            ),
        )
        result = await self._session.execute(stmt)
        return {
            row.nm_id: (
                float(row.seller_price) if row.seller_price is not None else None,
                float(row.customer_price) if row.customer_price is not None else None,
            )
            for row in result.all()
        }
