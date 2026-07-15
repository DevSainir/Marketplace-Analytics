"""Repository for :class:`AdvertisingStatDaily` rows."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date
from typing import Any, cast

from sqlalchemy import CursorResult, delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.modules.monitoring.models import AdvertisingStatDaily
from src.modules.monitoring.repos.base import BaseRepository


@dataclass(frozen=True, slots=True)
class AdAggregate:
    """Window advertising totals for one SKU, computed by the database."""

    nm_id: int
    spend: float
    clicks: int


@dataclass(frozen=True, slots=True)
class CampaignDayTotal:
    """One campaign-day's conversion totals across ALL its nm_ids.

    WB attributes a campaign's conversions to every size/colour variant the
    buyer actually converted on («ассоциированные конверсии»), so these totals
    exceed any single SKU's slice whenever associated variants converted.
    """

    campaign_id: int
    stat_date: date
    add_to_cart: int
    orders: int


_CONFLICT = ("stat_date", "campaign_id", "app_type", "nm_id")
_UPDATE = ("views", "clicks", "add_to_cart", "spend", "orders", "order_sum")


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

    async def campaign_day_totals(
        self, *, campaign_ids: Iterable[int], date_from: date, date_to: date
    ) -> list[CampaignDayTotal]:
        """Return per-(campaign, day) conversion totals across ALL nm_ids.

        Feeds the matrix's associative-conversion display: the campaign-level
        «carts/orders including associated variants» shown next to the viewed
        SKU's own slice.

        Args:
            campaign_ids: Campaigns to aggregate (typically the ones that
                delivered for the viewed SKU in the window).
            date_from: Inclusive window start.
            date_to: Inclusive window end.

        Returns:
            One :class:`CampaignDayTotal` per campaign-day with any rows.
        """
        ids = list(campaign_ids)
        if not ids:
            return []
        stmt = (
            select(
                AdvertisingStatDaily.campaign_id,
                AdvertisingStatDaily.stat_date,
                func.sum(AdvertisingStatDaily.add_to_cart).label("add_to_cart"),
                func.sum(AdvertisingStatDaily.orders).label("orders"),
            )
            .where(
                AdvertisingStatDaily.campaign_id.in_(ids),
                AdvertisingStatDaily.stat_date >= date_from,
                AdvertisingStatDaily.stat_date <= date_to,
            )
            .group_by(AdvertisingStatDaily.campaign_id, AdvertisingStatDaily.stat_date)
            .order_by(AdvertisingStatDaily.campaign_id, AdvertisingStatDaily.stat_date)
        )
        result = await self._session.execute(stmt)
        return [
            CampaignDayTotal(
                campaign_id=row.campaign_id,
                stat_date=row.stat_date,
                add_to_cart=int(row.add_to_cart),
                orders=int(row.orders),
            )
            for row in result.all()
        ]

    async def aggregate_window(self, *, date_from: date, date_to: date) -> list[AdAggregate]:
        """Return per-SKU advertising totals, aggregated by the database.

        Args:
            date_from: Inclusive window start.
            date_to: Inclusive window end.

        Returns:
            One :class:`AdAggregate` per SKU with advertising in the window.
        """
        stmt = (
            select(
                AdvertisingStatDaily.nm_id,
                func.sum(AdvertisingStatDaily.spend).label("spend"),
                func.sum(AdvertisingStatDaily.clicks).label("clicks"),
            )
            .where(
                AdvertisingStatDaily.stat_date >= date_from,
                AdvertisingStatDaily.stat_date <= date_to,
            )
            .group_by(AdvertisingStatDaily.nm_id)
            .order_by(AdvertisingStatDaily.nm_id)
        )
        result = await self._session.execute(stmt)
        return [
            AdAggregate(nm_id=row.nm_id, spend=float(row.spend), clicks=int(row.clicks))
            for row in result.all()
        ]

    async def delete_window_for_campaigns(
        self, *, date_from: date, date_to: date, campaign_ids: Iterable[int]
    ) -> int:
        """Delete a window's rows for the given campaigns (pre-refresh sweep).

        Ingestion skips WB's all-zero placeholder rows, so an upsert alone can
        never bring a previously nonzero row back DOWN to zero when WB corrects
        it. Deleting the harvested window first (in the same transaction as the
        re-insert) makes the harvest a faithful mirror of WB's current data.

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
        stmt = delete(AdvertisingStatDaily).where(
            AdvertisingStatDaily.campaign_id.in_(ids),
            AdvertisingStatDaily.stat_date >= date_from,
            AdvertisingStatDaily.stat_date <= date_to,
        )
        result = cast("CursorResult[Any]", await self._session.execute(stmt))
        return int(result.rowcount or 0)
