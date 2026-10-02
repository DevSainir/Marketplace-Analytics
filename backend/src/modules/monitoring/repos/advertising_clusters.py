"""Repository for :class:`AdvertisingClusterStatDaily` rows («Поиск по кластерам»).

Both reads aggregate in SQL: a SKU on a busy account can hold thousands of
(day, campaign, cluster) rows in a month, and hydrating them to sum in Python is
what turns a page section into a timeout.

Reads filter by ``nm_id`` alone, like every other per-SKU repository in this
module — WB SKU ids are globally unique, and tenancy is enforced once by the
router's ``WorkspaceSku`` guard (see ``monitoring/deps``).
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date
from typing import Any, cast

from sqlalchemy import CursorResult, case, delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.modules.monitoring.models import AdvertisingClusterStatDaily as Row
from src.modules.monitoring.models import AdvertisingStatDaily
from src.modules.monitoring.repos.ad_money import FX_COLUMNS, as_served
from src.modules.monitoring.repos.base import BaseRepository

_CONFLICT = ("stat_date", "campaign_id", "nm_id", "cluster")
_UPDATE = ("views", "clicks", "add_to_cart", "spend", "orders", "avg_position", *FX_COLUMNS)


@dataclass(frozen=True, slots=True)
class ClusterAggregate:
    """One search cluster's window totals for one SKU, computed by the database.

    Attributes:
        cluster: The normalized search phrase.
        days_count: Days in the window on which the cluster served impressions.
        campaign_count: Distinct campaigns that served in the cluster.
        views: Impressions.
        clicks: Clicks.
        add_to_cart: Add-to-cart events.
        orders: Attributed orders.
        spend: Advertising expenses in rubles.
        avg_position: Impression-weighted average ad position; ``None`` when WB
            reported no position for any matched row.
        campaign_ids: The campaigns that served in the cluster — what names the
            currency its spend is in.
    """

    cluster: str
    days_count: int
    campaign_count: int
    views: int
    clicks: int
    add_to_cart: int
    orders: int
    spend: float
    avg_position: float | None
    campaign_ids: tuple[int, ...] = ()


@dataclass(frozen=True, slots=True)
class ClusterDayPoint:
    """One day of one cluster's window (the trend behind a row)."""

    cluster: str
    stat_date: date
    views: int
    clicks: int
    orders: int
    spend: float


class AdvertisingClusterRepository(BaseRepository):
    """CRUD/read operations for daily per-search-cluster advertising metrics."""

    model = Row

    def __init__(self, session: AsyncSession) -> None:
        """Bind the repository to the request-scoped session."""
        super().__init__(session)

    async def upsert_many(self, rows: list[dict[str, object]]) -> int:
        """Idempotently upsert a batch of per-cluster rows.

        Args:
            rows: Column->value mappings keyed by the four-column composite PK.

        Returns:
            The number of rows submitted.
        """
        return await self.bulk_upsert(
            as_served(rows), conflict_columns=_CONFLICT, update_columns=_UPDATE
        )

    async def delete_window_for_campaigns(
        self, *, date_from: date, date_to: date, campaign_ids: Iterable[int]
    ) -> int:
        """Delete a window's rows for the given campaigns (pre-refresh sweep).

        Mirrors the search-zone sweep, and matters more here: a campaign that
        stopped bidding on a cluster produces no row for it at all, so an upsert
        alone would leave the dropped phrase in the seller's report forever.

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
        stmt = delete(Row).where(
            Row.campaign_id.in_(ids),
            Row.stat_date >= date_from,
            Row.stat_date <= date_to,
        )
        result = cast("CursorResult[Any]", await self._session.execute(stmt))
        return int(result.rowcount or 0)

    async def aggregate_for_sku(
        self,
        *,
        nm_id: int,
        date_from: date,
        date_to: date,
        limit: int,
    ) -> list[ClusterAggregate]:
        """Sum the SKU's clusters over the window, most impressions first.

        Ranked by impressions because that is the cluster's actual weight in the
        SKU's paid traffic; ties break on the cluster text for a stable order.

        Args:
            nm_id: WB SKU identifier.
            date_from: Inclusive window start.
            date_to: Inclusive window end.
            limit: Maximum clusters to return.

        Returns:
            One :class:`ClusterAggregate` per cluster the SKU served in.
        """
        # Rows WB reported no position for (avg_position 0) are excluded from
        # BOTH sides of the weighted mean — counting their impressions in the
        # denominator alone would drag every average towards zero.
        positioned = case((Row.avg_position > 0, Row.views), else_=0)
        stmt = (
            select(
                Row.cluster,
                func.count(func.distinct(Row.stat_date)).label("days_count"),
                func.count(func.distinct(Row.campaign_id)).label("campaign_count"),
                func.sum(Row.views).label("views"),
                func.sum(Row.clicks).label("clicks"),
                func.sum(Row.add_to_cart).label("add_to_cart"),
                func.sum(Row.orders).label("orders"),
                func.sum(Row.spend).label("spend"),
                func.sum(Row.avg_position * positioned).label("weighted_position"),
                func.sum(positioned).label("positioned_views"),
                func.array_agg(func.distinct(Row.campaign_id)).label("campaign_ids"),
            )
            .where(
                Row.nm_id == nm_id,
                Row.stat_date >= date_from,
                Row.stat_date <= date_to,
            )
            .group_by(Row.cluster)
            .order_by(func.sum(Row.views).desc(), Row.cluster)
            .limit(limit)
        )
        result = await self._session.execute(stmt)
        return [
            ClusterAggregate(
                cluster=row.cluster,
                days_count=int(row.days_count),
                campaign_count=int(row.campaign_count),
                views=int(row.views or 0),
                clicks=int(row.clicks or 0),
                add_to_cart=int(row.add_to_cart or 0),
                orders=int(row.orders or 0),
                spend=float(row.spend or 0),
                # Weighted by impressions: a cluster with 10 000 views at
                # position 3 and 10 at position 40 averages ~3, not ~21.
                avg_position=(
                    float(row.weighted_position) / float(row.positioned_views)
                    if row.positioned_views
                    else None
                ),
                campaign_ids=tuple(int(cid) for cid in row.campaign_ids or ()),
            )
            for row in result.all()
        ]

    async def campaign_currencies(self, *, campaign_ids: Iterable[int]) -> dict[int, str]:
        """What each campaign is billed in, as its fullstats rows state it.

        A campaign's currency is fixed at its creation, so any labelled row
        names it; MAX prefers a label over the blank of a row harvested before
        labels were recorded. A campaign with no labelled row is absent.
        """
        ids = list(campaign_ids)
        if not ids:
            return {}
        stmt = (
            select(AdvertisingStatDaily.campaign_id, func.max(AdvertisingStatDaily.currency))
            .where(AdvertisingStatDaily.campaign_id.in_(ids), AdvertisingStatDaily.currency != "")
            .group_by(AdvertisingStatDaily.campaign_id)
        )
        return {int(cid): str(code) for cid, code in (await self._session.execute(stmt)).all()}

    async def daily_series_for_sku(
        self,
        *,
        nm_id: int,
        clusters: Iterable[str],
        date_from: date,
        date_to: date,
    ) -> list[ClusterDayPoint]:
        """Per-day totals for the SKU's given clusters (the trend behind a row).

        Only days WB reported are returned; the presentation layer fills the
        gaps, because a missing day means "no impressions", which a trend should
        draw as zero rather than skip.

        Args:
            nm_id: WB SKU identifier.
            clusters: Exact cluster texts (those returned by the aggregate).
            date_from: Inclusive window start.
            date_to: Inclusive window end.

        Returns:
            One row per ``(cluster, day)`` with activity.
        """
        wanted = list(clusters)
        if not wanted:
            return []
        stmt = (
            select(
                Row.cluster,
                Row.stat_date,
                func.sum(Row.views).label("views"),
                func.sum(Row.clicks).label("clicks"),
                func.sum(Row.orders).label("orders"),
                func.sum(Row.spend).label("spend"),
            )
            .where(
                Row.nm_id == nm_id,
                Row.cluster.in_(wanted),
                Row.stat_date >= date_from,
                Row.stat_date <= date_to,
            )
            .group_by(Row.cluster, Row.stat_date)
            .order_by(Row.cluster, Row.stat_date)
        )
        result = await self._session.execute(stmt)
        return [
            ClusterDayPoint(
                cluster=row.cluster,
                stat_date=row.stat_date,
                views=int(row.views or 0),
                clicks=int(row.clicks or 0),
                orders=int(row.orders or 0),
                spend=float(row.spend or 0),
            )
            for row in result.all()
        ]
