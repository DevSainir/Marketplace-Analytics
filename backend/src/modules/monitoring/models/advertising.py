"""Advertising full-stats time-series model.

Flattens the nested ``apps`` (platform) -> ``nms`` (SKU) tree from WB into one
row per ``(date, campaign_id, app_type, nm_id)``. The four-column composite key
matches the natural grain of the source data and makes re-ingestion idempotent.
"""

from __future__ import annotations

from datetime import date

from sqlalchemy import BigInteger, Date, Index, Integer, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from src.core.database import Base

_SCHEMA: str = "monitoring"


class AdvertisingStatDaily(Base):
    """Flattened daily advertising metrics for one platform/SKU/campaign.

    Sourced from ``GET /adv/v3/fullstats``. ``app_type`` encodes the platform:
    ``1`` Desktop, ``3`` Android, ``4`` iOS, ``10`` Mobile Web, ``64`` ARK.

    Attributes:
        stat_date: Calendar day (Moscow time).
        campaign_id: WB advertising campaign identifier.
        app_type: Platform indicator (see codes above).
        nm_id: WB SKU identifier.
        views: Impressions served.
        clicks: Clicks received.
        spend: Advertising expenses (WB ``sum``).
        orders: Attributed orders.
        order_sum: Ad-attributed order revenue in rubles (WB ``sum_price``).
    """

    __tablename__ = "advertising_stat_daily"
    __table_args__ = (
        # nm_id is the FOURTH PK column, so per-SKU reads need this index.
        Index("ix_advertising_stat_daily_nm_id_stat_date", "nm_id", "stat_date"),
        {"schema": _SCHEMA},
    )

    stat_date: Mapped[date] = mapped_column(Date, primary_key=True)
    campaign_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    app_type: Mapped[int] = mapped_column(Integer, primary_key=True)
    nm_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)

    views: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    clicks: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    add_to_cart: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    spend: Mapped[float] = mapped_column(Numeric(14, 2), default=0, nullable=False)
    orders: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    order_sum: Mapped[float] = mapped_column(Numeric(14, 2), default=0, nullable=False)


class AdvertisingSearchStatDaily(Base):
    """Daily SEARCH-zone slice of a campaign's advertising for one SKU.

    Sourced from ``POST /adv/v1/normquery/stats`` (search clusters summed per
    day). Covers only the «Поиск» display zone; the recommendations («Полки»)
    slice is derived at read time as ``fullstats total - search``. There is no
    platform split on this endpoint, so the grain is one row per
    ``(date, campaign_id, nm_id)``.

    Attributes:
        stat_date: Calendar day (Moscow time).
        campaign_id: WB advertising campaign identifier.
        nm_id: WB SKU identifier.
        views: Search-zone impressions.
        clicks: Search-zone clicks.
        add_to_cart: Search-zone add-to-cart events (WB ``atbs``).
        spend: Search-zone advertising expenses.
        orders: Search-zone attributed orders.
    """

    __tablename__ = "advertising_search_stat_daily"
    __table_args__ = (
        # nm_id is the THIRD PK column, so per-SKU reads need this index.
        Index("ix_advertising_search_stat_daily_nm_id_stat_date", "nm_id", "stat_date"),
        {"schema": _SCHEMA},
    )

    stat_date: Mapped[date] = mapped_column(Date, primary_key=True)
    campaign_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    nm_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)

    views: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    clicks: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    add_to_cart: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    spend: Mapped[float] = mapped_column(Numeric(14, 2), default=0, nullable=False)
    orders: Mapped[int] = mapped_column(Integer, default=0, nullable=False)


#: Longest cluster text WB has been observed to return, with headroom. The
#: cluster IS part of the primary key, so it must be a bounded column: an
#: unbounded ``Text`` key risks exceeding the B-tree tuple limit on a pathological
#: value. Longer texts are truncated on ingest (see the cluster ingestion).
CLUSTER_MAX_LENGTH: int = 255


class AdvertisingClusterStatDaily(Base):
    """Daily metrics of ONE search cluster («кластер») for one SKU/campaign.

    Sourced from ``POST /adv/v1/normquery/stats`` — the same payload
    :class:`AdvertisingSearchStatDaily` sums over. That table answers "how much
    of this campaign's day was the search zone"; this one keeps the cluster
    labels the sum throws away, which is the only place the seller's own search
    phrases exist in our data. It is what «Поиск по кластерам» reads.

    Rows are only ever the SEARCH zone, and only clusters the seller PAID to
    appear in: a cluster absent here means the campaign served no impression for
    it, not that WB users did not search it.

    Attributes:
        stat_date: Calendar day (Moscow time).
        campaign_id: WB advertising campaign identifier.
        nm_id: WB SKU identifier.
        cluster: Normalized search phrase WB grouped the queries under.
        views: Impressions served for the cluster.
        clicks: Clicks received.
        add_to_cart: Add-to-cart events (WB ``atbs``).
        spend: Advertising expenses in rubles.
        orders: Attributed orders.
        avg_position: Average ad position in the cluster's results; 0 = unknown.
    """

    __tablename__ = "advertising_cluster_stat_daily"
    __table_args__ = (
        # The keyword search is `cluster ILIKE '%...%'` over a window, so the
        # useful index is the one that narrows the window first; the cluster
        # index serves exact-cluster drill-downs (and prefix matches).
        Index("ix_advertising_cluster_stat_daily_date_cluster", "stat_date", "cluster"),
        Index("ix_advertising_cluster_stat_daily_cluster", "cluster"),
        Index("ix_advertising_cluster_stat_daily_nm_id_stat_date", "nm_id", "stat_date"),
        {"schema": _SCHEMA},
    )

    stat_date: Mapped[date] = mapped_column(Date, primary_key=True)
    campaign_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    nm_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    cluster: Mapped[str] = mapped_column(String(CLUSTER_MAX_LENGTH), primary_key=True)

    views: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    clicks: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    add_to_cart: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    spend: Mapped[float] = mapped_column(Numeric(14, 2), default=0, nullable=False)
    orders: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    avg_position: Mapped[float] = mapped_column(Numeric(8, 2), default=0, nullable=False)
