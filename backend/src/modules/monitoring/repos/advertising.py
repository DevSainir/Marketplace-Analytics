"""Repository for :class:`AdvertisingStatDaily` rows."""

from __future__ import annotations

from datetime import date

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.modules.monitoring.models import AdvertisingStatDaily
from src.modules.monitoring.repos.base import BaseRepository

_CONFLICT = ("stat_date", "campaign_id", "app_type", "nm_id")
_UPDATE = ("views", "clicks", "add_to_cart", "spend", "orders")


class AdvertisingRepository(BaseRepository):
    """CRUD/read operations for daily advertising metrics."""

    model = AdvertisingStatDaily

    def __init__(self, session: AsyncSession) -> None:
        """Bind the repository to the request-scoped session."""
        super().__init__(session)

    async def upsert_many(self, rows: list[dict[str, object]]) -> int:
        """Idempotently upsert a batch of flattened advertising rows.

        Args:
            rows: Column->value mappings keyed by the four-column composite PK.

        Returns:
            The number of rows submitted.
        """
        return await self.bulk_upsert(rows, conflict_columns=_CONFLICT, update_columns=_UPDATE)

    async def list_for_sku(
        self,
        *,
        nm_id: int,
        date_from: date,
        date_to: date,
        campaign_id: int | None = None,
    ) -> list[AdvertisingStatDaily]:
        """Return advertising rows for one SKU within an inclusive window.

        Args:
            nm_id: WB SKU identifier.
            date_from: Inclusive window start.
            date_to: Inclusive window end.
            campaign_id: Optional filter restricting rows to one campaign.

        Returns:
            Matching advertising rows ordered by date then platform.
        """
        stmt = select(AdvertisingStatDaily).where(
            AdvertisingStatDaily.nm_id == nm_id,
            AdvertisingStatDaily.stat_date >= date_from,
            AdvertisingStatDaily.stat_date <= date_to,
        )
        if campaign_id is not None:
            stmt = stmt.where(AdvertisingStatDaily.campaign_id == campaign_id)
        stmt = stmt.order_by(
            AdvertisingStatDaily.campaign_id,
            AdvertisingStatDaily.stat_date,
            AdvertisingStatDaily.app_type,
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def list_window(self, *, date_from: date, date_to: date) -> list[AdvertisingStatDaily]:
        """Return advertising rows across every SKU within a window."""
        stmt = (
            select(AdvertisingStatDaily)
            .where(
                AdvertisingStatDaily.stat_date >= date_from,
                AdvertisingStatDaily.stat_date <= date_to,
            )
            .order_by(AdvertisingStatDaily.nm_id, AdvertisingStatDaily.stat_date)
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().all())
