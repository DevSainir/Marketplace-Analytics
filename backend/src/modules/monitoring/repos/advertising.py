"""Repository for :class:`AdvertisingStatDaily` rows."""

from __future__ import annotations

import uuid
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date
from typing import Any, cast

from sqlalchemy import CursorResult, case, delete, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.modules.monitoring.models import AdvertisingStatDaily
from src.modules.monitoring.repos.base import BaseRepository, workspace_sku_select


@dataclass(frozen=True, slots=True)
class AdDayTotal:
    """One day of advertising facts, summed across the SKUs in scope."""

    stat_date: date
    views: int
    clicks: int
    add_to_cart: int
    orders: int
    spend: float


@dataclass(frozen=True, slots=True)
class AdAggregate:
    """Window advertising totals for one SKU, computed by the database."""

    nm_id: int
    spend: float
    clicks: int


@dataclass(frozen=True, slots=True)
class CampaignDayTotal:
    """One campaign-day's metrics across ALL its nm_ids — the whole кампания.

    An advertising column of the matrix is a view of a рекламная кампания, not
    of the card on screen, so this — not the viewed SKU's slice of it — is what
    the column is built from. WB attributes a campaign's conversions to every
    size/colour variant the buyer actually converted on («ассоциированные
    конверсии»), so the totals exceed any single SKU's slice whenever
    associated variants converted.

    ``traffic_add_to_cart``/``traffic_orders`` are the same sums restricted to
    the rows that carried traffic (``views > 0``) — the advertised card(s). WB
    books an associated variant's conversions with ``views=clicks=0``, so the
    difference between the two pairs is exactly the associative extra: the part
    of the campaign's conversions no report attributes to a display zone, which
    the zone split has to apportion.
    """

    campaign_id: int
    stat_date: date
    views: int
    clicks: int
    add_to_cart: int
    spend: float
    orders: int
    order_sum: float
    traffic_add_to_cart: int
    traffic_orders: int


@dataclass(frozen=True, slots=True)
class CampaignSearchDayTotal:
    """One campaign-day's SEARCH-zone metrics across ALL its nm_ids.

    The campaign-grain counterpart of :class:`CampaignDayTotal` for WB's
    normquery feed, which reports only what the advertised card(s) took in the
    search zone (an associated variant's conversions never appear here — see
    :class:`CampaignDayTotal`).
    """

    campaign_id: int
    stat_date: date
    views: int
    clicks: int
    add_to_cart: int
    spend: float
    orders: int


@dataclass(frozen=True, slots=True)
class CampaignDaySkuTotal:
    """One campaign-day's conversions booked on ONE nm_id.

    The per-variant decomposition of :class:`CampaignDayTotal`: summing these
    over a campaign-day reproduces it exactly. WB books an associated variant's
    conversions with ``views=clicks=0`` (all the traffic is credited to the
    advertised card), so a row here can carry carts/orders and no traffic.
    """

    campaign_id: int
    stat_date: date
    nm_id: int
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
        """Return per-(campaign, day) totals across ALL nm_ids — the whole кампания.

        These ARE the matrix's advertising columns: a column measures the
        рекламная кампания, and the viewed SKU's own rows only decorate it (the
        carts/orders hover) and feed the «Общая»/«Органика» columns.

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
        # The associated variants' rows carry conversions with no traffic, so
        # the traffic-only sums are taken in the same pass — a second query
        # over the same rows would only add a round trip.
        with_traffic = AdvertisingStatDaily.views > 0
        stmt = (
            select(
                AdvertisingStatDaily.campaign_id,
                AdvertisingStatDaily.stat_date,
                func.sum(AdvertisingStatDaily.views).label("views"),
                func.sum(AdvertisingStatDaily.clicks).label("clicks"),
                func.sum(AdvertisingStatDaily.add_to_cart).label("add_to_cart"),
                func.sum(AdvertisingStatDaily.spend).label("spend"),
                func.sum(AdvertisingStatDaily.orders).label("orders"),
                func.sum(AdvertisingStatDaily.order_sum).label("order_sum"),
                func.sum(case((with_traffic, AdvertisingStatDaily.add_to_cart), else_=0)).label(
                    "traffic_add_to_cart"
                ),
                func.sum(case((with_traffic, AdvertisingStatDaily.orders), else_=0)).label(
                    "traffic_orders"
                ),
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
                views=int(row.views),
                clicks=int(row.clicks),
                add_to_cart=int(row.add_to_cart),
                spend=float(row.spend),
                orders=int(row.orders),
                order_sum=float(row.order_sum),
                traffic_add_to_cart=int(row.traffic_add_to_cart),
                traffic_orders=int(row.traffic_orders),
            )
            for row in result.all()
        ]

    async def campaign_day_sku_totals(
        self, *, campaign_ids: Iterable[int], date_from: date, date_to: date
    ) -> list[CampaignDaySkuTotal]:
        """Return per-(campaign, day, nm_id) conversion totals.

        The breakdown behind :meth:`campaign_day_totals` — same rows, one
        ``GROUP BY`` finer — feeding the associative-conversion hover, which
        names the variants a campaign-day's carts/orders were booked on.

        Args:
            campaign_ids: Campaigns to aggregate (typically the ones that
                delivered for the viewed SKU in the window).
            date_from: Inclusive window start.
            date_to: Inclusive window end.

        Returns:
            One :class:`CampaignDaySkuTotal` per campaign-day-nm_id that
            converted; rows with neither carts nor orders are dropped, since
            they would only pad the hover with empty variants.
        """
        ids = list(campaign_ids)
        if not ids:
            return []
        carts = func.sum(AdvertisingStatDaily.add_to_cart).label("add_to_cart")
        orders = func.sum(AdvertisingStatDaily.orders).label("orders")
        stmt = (
            select(
                AdvertisingStatDaily.campaign_id,
                AdvertisingStatDaily.stat_date,
                AdvertisingStatDaily.nm_id,
                carts,
                orders,
            )
            .where(
                AdvertisingStatDaily.campaign_id.in_(ids),
                AdvertisingStatDaily.stat_date >= date_from,
                AdvertisingStatDaily.stat_date <= date_to,
            )
            .group_by(
                AdvertisingStatDaily.campaign_id,
                AdvertisingStatDaily.stat_date,
                AdvertisingStatDaily.nm_id,
            )
            .having(or_(carts > 0, orders > 0))
            .order_by(AdvertisingStatDaily.campaign_id, AdvertisingStatDaily.stat_date)
        )
        result = await self._session.execute(stmt)
        return [
            CampaignDaySkuTotal(
                campaign_id=row.campaign_id,
                stat_date=row.stat_date,
                nm_id=row.nm_id,
                add_to_cart=int(row.add_to_cart),
                orders=int(row.orders),
            )
            for row in result.all()
        ]

    async def daily_totals(
        self,
        *,
        workspace_id: uuid.UUID,
        date_from: date,
        date_to: date,
        nm_ids: Sequence[int] | None = None,
    ) -> list[AdDayTotal]:
        """Return per-DAY advertising totals summed ACROSS SKUs.

        Deliberately NOT split by traffic bucket. A bucket is the result of
        classifying a CAMPAIGN-day (bid type, placements, payment model, its
        normquery slice, and which campaigns delivered enough to count) — a
        per-SKU judgement that does not survive being summed over an account.
        The «Сравнение SKU» page therefore aggregates the totals only, and the
        per-SKU page keeps the bucket columns.

        The rows are the campaigns' own numbers for these cards, so a campaign
        running several SKUs contributes each of them once.

        Args:
            workspace_id: Restrict to SKUs owned by this workspace.
            date_from: Inclusive window start.
            date_to: Inclusive window end.
            nm_ids: Restrict further to these SKUs; ``None`` means all of them.

        Returns:
            One :class:`AdDayTotal` per day with advertising, ascending by date.
        """
        stmt = (
            select(
                AdvertisingStatDaily.stat_date,
                func.sum(AdvertisingStatDaily.views).label("views"),
                func.sum(AdvertisingStatDaily.clicks).label("clicks"),
                func.sum(AdvertisingStatDaily.add_to_cart).label("add_to_cart"),
                func.sum(AdvertisingStatDaily.orders).label("orders"),
                func.sum(AdvertisingStatDaily.spend).label("spend"),
            )
            .where(
                AdvertisingStatDaily.stat_date >= date_from,
                AdvertisingStatDaily.stat_date <= date_to,
                AdvertisingStatDaily.nm_id.in_(workspace_sku_select(workspace_id)),
            )
            .group_by(AdvertisingStatDaily.stat_date)
            .order_by(AdvertisingStatDaily.stat_date)
        )
        if nm_ids is not None:
            stmt = stmt.where(AdvertisingStatDaily.nm_id.in_(list(nm_ids)))
        result = await self._session.execute(stmt)
        return [
            AdDayTotal(
                stat_date=row.stat_date,
                views=int(row.views),
                clicks=int(row.clicks),
                add_to_cart=int(row.add_to_cart),
                orders=int(row.orders),
                spend=float(row.spend),
            )
            for row in result.all()
        ]

    async def aggregate_window(
        self, *, workspace_id: uuid.UUID, date_from: date, date_to: date
    ) -> list[AdAggregate]:
        """Return per-SKU advertising totals, aggregated by the database.

        Args:
            workspace_id: Restrict to SKUs owned by this workspace.
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
                AdvertisingStatDaily.nm_id.in_(workspace_sku_select(workspace_id)),
            )
            .group_by(AdvertisingStatDaily.nm_id)
            .order_by(AdvertisingStatDaily.nm_id)
        )
        result = await self._session.execute(stmt)
        return [
            AdAggregate(nm_id=row.nm_id, spend=float(row.spend), clicks=int(row.clicks))
            for row in result.all()
        ]

    async def campaign_ids_in_window(
        self, *, nm_ids: Iterable[int], date_from: date, date_to: date
    ) -> list[int]:
        """Return the campaigns already holding rows for ``nm_ids`` in a window.

        The harvest re-asks WB for these regardless of the status WB now
        reports, so a campaign the seller completed mid-window still gets its
        final day collected (see
        :func:`~src.modules.monitoring.tasks.planning._advertising_harvest_ids`).

        Args:
            nm_ids: The SKUs being harvested.
            date_from: Inclusive window start.
            date_to: Inclusive window end.

        Returns:
            Ascending campaign ids, empty when nothing delivered in the window.
        """
        ids = list(nm_ids)
        if not ids:
            return []
        stmt = (
            select(AdvertisingStatDaily.campaign_id)
            .where(
                AdvertisingStatDaily.nm_id.in_(ids),
                AdvertisingStatDaily.stat_date >= date_from,
                AdvertisingStatDaily.stat_date <= date_to,
            )
            .distinct()
            .order_by(AdvertisingStatDaily.campaign_id)
        )
        result = await self._session.execute(stmt)
        return [int(cid) for cid in result.scalars().all()]

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
