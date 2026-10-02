"""Repository for :class:`AdvertisingSearchStatDaily` rows."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import date
from typing import Any, cast

from sqlalchemy import CursorResult, delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.modules.monitoring.models import AdvertisingSearchStatDaily
from src.modules.monitoring.repos.ad_money import FX_COLUMNS, as_served
from src.modules.monitoring.repos.advertising import CampaignSearchDayTotal
from src.modules.monitoring.repos.base import BaseRepository

_CONFLICT = ("stat_date", "campaign_id", "nm_id")
_UPDATE = ("views", "clicks", "add_to_cart", "spend", "orders", *FX_COLUMNS)


class AdvertisingSearchRepository(BaseRepository):
    """CRUD/read operations for daily search-zone advertising metrics."""

    model = AdvertisingSearchStatDaily

    def __init__(self, session: AsyncSession) -> None:
        """Bind the repository to the request-scoped session."""
        super().__init__(session)

    async def upsert_many(self, rows: list[dict[str, object]]) -> int:
        """Idempotently upsert a batch of flattened search-zone rows.

        Args:
            rows: Column->value mappings keyed by the three-column composite PK.

        Returns:
            The number of rows submitted.
        """
        return await self.bulk_upsert(
            as_served(rows), conflict_columns=_CONFLICT, update_columns=_UPDATE
        )

    async def campaign_day_totals(
        self, *, campaign_ids: Iterable[int], date_from: date, date_to: date
    ) -> list[CampaignSearchDayTotal]:
        """Return per-(campaign, day) search-zone totals across ALL nm_ids.

        The zone split of an advertising column divides the whole кампания, so
        the slice it splits off has to be the whole campaign's search zone —
        not the viewed card's share of it.

        Args:
            campaign_ids: Campaigns to aggregate (typically the ones that
                delivered for the viewed SKU in the window).
            date_from: Inclusive window start.
            date_to: Inclusive window end.

        Returns:
            One :class:`CampaignSearchDayTotal` per campaign-day with any rows.
        """
        ids = list(campaign_ids)
        if not ids:
            return []
        stmt = (
            select(
                AdvertisingSearchStatDaily.campaign_id,
                AdvertisingSearchStatDaily.stat_date,
                func.sum(AdvertisingSearchStatDaily.views).label("views"),
                func.sum(AdvertisingSearchStatDaily.clicks).label("clicks"),
                func.sum(AdvertisingSearchStatDaily.add_to_cart).label("add_to_cart"),
                func.sum(AdvertisingSearchStatDaily.spend).label("spend"),
                func.sum(AdvertisingSearchStatDaily.orders).label("orders"),
            )
            .where(
                AdvertisingSearchStatDaily.campaign_id.in_(ids),
                AdvertisingSearchStatDaily.stat_date >= date_from,
                AdvertisingSearchStatDaily.stat_date <= date_to,
            )
            .group_by(AdvertisingSearchStatDaily.campaign_id, AdvertisingSearchStatDaily.stat_date)
            .order_by(AdvertisingSearchStatDaily.campaign_id, AdvertisingSearchStatDaily.stat_date)
        )
        result = await self._session.execute(stmt)
        return [
            CampaignSearchDayTotal(
                campaign_id=row.campaign_id,
                stat_date=row.stat_date,
                views=int(row.views),
                clicks=int(row.clicks),
                add_to_cart=int(row.add_to_cart),
                spend=float(row.spend),
                orders=int(row.orders),
            )
            for row in result.all()
        ]

    async def list_for_sku(
        self,
        *,
        nm_id: int,
        date_from: date,
        date_to: date,
        campaign_id: int | None = None,
    ) -> list[AdvertisingSearchStatDaily]:
        """Return search-zone rows for one SKU within an inclusive window.

        Args:
            nm_id: WB SKU identifier.
            date_from: Inclusive window start.
            date_to: Inclusive window end.
            campaign_id: Optional filter restricting rows to one campaign.

        Returns:
            Matching search-zone rows ordered by campaign then date.
        """
        stmt = select(AdvertisingSearchStatDaily).where(
            AdvertisingSearchStatDaily.nm_id == nm_id,
            AdvertisingSearchStatDaily.stat_date >= date_from,
            AdvertisingSearchStatDaily.stat_date <= date_to,
        )
        if campaign_id is not None:
            stmt = stmt.where(AdvertisingSearchStatDaily.campaign_id == campaign_id)
        stmt = stmt.order_by(
            AdvertisingSearchStatDaily.campaign_id,
            AdvertisingSearchStatDaily.stat_date,
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def delete_window_for_campaigns(
        self, *, date_from: date, date_to: date, campaign_ids: Iterable[int]
    ) -> int:
        """Delete a window's rows for the given campaigns (pre-refresh sweep).

        Mirrors the advertising fact sweep: an upsert alone can never bring a
        previously nonzero search-zone row back down to zero when WB corrects
        it, so the harvested window is deleted first in the same transaction.

        Args:
            date_from: Inclusive window start.
            date_to: Inclusive window end.
            campaign_ids: The campaigns whose window is being re-harvested.

        Returns:
            The number of rows deleted.
        """
        ids = list(campaign_ids)
        if not ids:
            return 0
        stmt = delete(AdvertisingSearchStatDaily).where(
            AdvertisingSearchStatDaily.campaign_id.in_(ids),
            AdvertisingSearchStatDaily.stat_date >= date_from,
            AdvertisingSearchStatDaily.stat_date <= date_to,
        )
        result = cast("CursorResult[Any]", await self._session.execute(stmt))
        return int(result.rowcount or 0)
