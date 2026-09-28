"""Repository for :class:`PriceSnapshot` rows."""

from __future__ import annotations

import uuid
from datetime import date

from sqlalchemy import and_, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from src.modules.monitoring.models import PriceSnapshot
from src.modules.monitoring.repos.base import BaseRepository, workspace_sku_select

_CONFLICT = ("stat_date", "nm_id")
_UPDATE = ("seller_price", "customer_price", "customer_spp", "customer_source", "currency")


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

    async def latest_by_sku(
        self, *, workspace_id: uuid.UUID, date_to: date
    ) -> dict[int, tuple[float | None, float | None]]:
        """Return each SKU's most recent ``(seller, customer)`` price on/before a day.

        Aggregated in SQL for the summary listing (which prices window-total
        counts against the latest known price — the per-day matrix carries prices
        forward per day instead).

        Args:
            workspace_id: Restrict to SKUs owned by this workspace.
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
            .where(
                PriceSnapshot.stat_date <= date_to,
                PriceSnapshot.nm_id.in_(workspace_sku_select(workspace_id)),
            )
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

    async def skus_missing_customer_price(
        self, *, workspace_id: uuid.UUID, stat_date: date
    ) -> list[int]:
        """Return this workspace's SKUs whose snapshot for a day has no customer price.

        The working set of the top-up pass: a SKU that already has a price is
        not asked about again, so the pass costs nothing for the ones that are
        already answered.

        Args:
            workspace_id: Restrict to SKUs owned by this workspace.
            stat_date: The snapshot day to look at.

        Returns:
            SKU ids with a snapshot row on the day and ``customer_price`` NULL.
        """
        stmt = select(PriceSnapshot.nm_id).where(
            PriceSnapshot.stat_date == stat_date,
            PriceSnapshot.customer_price.is_(None),
            PriceSnapshot.nm_id.in_(workspace_sku_select(workspace_id)),
        )
        result = await self._session.execute(stmt)
        return [int(nm_id) for nm_id in result.scalars().all()]

    async def fill_missing_customer_price(
        self, *, stat_date: date, nm_id: int, customer_price: float, spp: float | None, source: str
    ) -> bool:
        """Write a customer price ONLY where there is not one already.

        ``customer_price IS NULL`` is part of the statement rather than a check
        the caller makes first: between reading the gap and writing it a harvest
        may have filled the row, and a top-up that overwrites a fresher answer
        with its own is worse than one that does nothing. The database decides,
        so there is no window in which two passes can disagree.

        Args:
            stat_date: The snapshot day.
            nm_id: WB SKU identifier.
            customer_price: The price to write.
            spp: WB's loyalty percent, when the source states it.
            source: Which measurement this is (see the model's ``customer_source``).

        Returns:
            True when a row was actually filled, False when one was already there.
        """
        stmt = (
            update(PriceSnapshot)
            .where(
                PriceSnapshot.stat_date == stat_date,
                PriceSnapshot.nm_id == nm_id,
                PriceSnapshot.customer_price.is_(None),
            )
            .values(customer_price=customer_price, customer_spp=spp, customer_source=source)
        )
        result = await self._session.execute(stmt)
        return bool(result.rowcount)  # type: ignore[attr-defined]
