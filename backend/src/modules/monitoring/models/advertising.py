"""Advertising time-series models — impressions, and who paid for them.

The fullstats family flattens the nested ``apps`` (platform) -> ``nms`` (SKU)
tree from WB into one row per ``(date, campaign_id, app_type, nm_id)``. The
four-column composite key matches the natural grain of the source data and makes
re-ingestion idempotent.

:class:`AdvertisingWriteOffDaily` is the money counterpart: fullstats reports
spend without ever saying whether the seller or WB funded it, and that split is
the difference between a true DRR and a flattering one.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from sqlalchemy import BigInteger, Date, Index, Integer, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from src.core.database import Base
from src.modules.monitoring.models.fx import FxConverted

_SCHEMA: str = "monitoring"


class AdvertisingStatDaily(FxConverted, Base):
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
        spend: Advertising expenses (WB ``sum``), in :attr:`currency`.
        orders: Attributed orders.
        order_sum: Ad-attributed order revenue (WB ``sum_price``), in :attr:`currency`.
        currency: The campaign's own unit, as fullstats states it on the
            campaign. RUB for campaigns created before WB moved the ad account
            to KGS on 2026-08-20, KGS after — so one workspace holds both.
            ``""`` = not yet read (rows harvested before the column existed).
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
    currency: Mapped[str] = mapped_column(String(8), server_default="", nullable=False)


class AdvertisingSearchStatDaily(FxConverted, Base):
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


class AdvertisingClusterStatDaily(FxConverted, Base):
    """Daily metrics of ONE search cluster for one SKU/campaign.

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


#: Longest ``paymentType`` WB has been observed to return, with headroom. It IS
#: part of the primary key, so the column must be bounded.
PAYMENT_TYPE_MAX_LENGTH: int = 32

#: ``paymentType`` values that mean «WB paid for this, not the seller».
#:
#: Checked against WB's API on 2026-09-15. «Кэшбэк» is the label WB actually
#: uses; «Бонусы» is listed alongside it because WB's own seller portal
#: names the same pool that way and a rename would otherwise go unnoticed.
#:
#: **The match is an allowlist, and that direction is deliberate.** An
#: unrecognised funding label is treated as the seller's own money, so a WB
#: rename degrades the report back to counting gross spend — today's behaviour.
#: The reverse default (unknown = bonus) would subtract real money and overstate
#: profit, which is the error nobody catches. Unknown labels are surfaced in the
#: report's ``notes`` instead of being silently absorbed.
BONUS_PAYMENT_TYPES: frozenset[str] = frozenset({"Кэшбэк", "Бонусы"})

#: ``paymentType`` values that mean the seller's own money left the account.
#: Only used to tell a *known* cash label from an unrecognised one when
#: assembling the caveat; the arithmetic never reads this.
CASH_PAYMENT_TYPES: frozenset[str] = frozenset({"Баланс", "Счет", "Счёт"})


class AdvertisingWriteOffDaily(FxConverted, Base):
    """One day's advertising charges for one campaign, one funding source.

    Sourced from ``GET /adv/v1/upd`` — the only WB feed that says who paid for
    an impression. ``fullstats`` reports the spend whatever funded it, and a
    cashback charge never reaches the settlement report at all (WB gives it no
    invoice document), so without this table WB's bonuses are counted as the
    seller's money in every per-SKU DRR, ROI and profit figure.

    **``currency`` is in the primary key because WB mixes currencies inside one
    window.** Over 2026-08..09 one account had «Баланс» rows in both RUB and
    KGS. Summing across it would add unlike units, so the grain
    keeps them apart and the reader picks the one currency it settles in.

    The grain deliberately drops WB's ``updNum``: it is an invoice-document
    number, and every cashback row carries ``0``. Aggregating by it once turned
    169 000 KGS of bonuses into 500.

    Attributes:
        stat_date: Moscow day WB charged it (``updTime``). This is the charge
            date, NOT the day the ads ran — write-offs are batched, so it aligns
            with ``advertising_stat_daily`` over a window, not day by day.
        campaign_id: WB advertising campaign charged. The feed carries no
            ``nm_id``, so this is the finest attribution WB permits.
        payment_type: WB's funding-source label, verbatim.
        currency: The row's own settlement currency.
        amount: Σ ``updSum`` of the write-offs in this bucket.
        write_offs: How many WB rows were summed — a bucket, not a single row.
    """

    __tablename__ = "advertising_write_off_daily"
    __table_args__ = (
        # The report reads a window across all campaigns, so date leads.
        Index("ix_advertising_write_off_daily_date", "stat_date"),
        {"schema": _SCHEMA},
    )

    stat_date: Mapped[date] = mapped_column(Date, primary_key=True)
    campaign_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    payment_type: Mapped[str] = mapped_column(String(PAYMENT_TYPE_MAX_LENGTH), primary_key=True)
    currency: Mapped[str] = mapped_column(String(8), primary_key=True)

    amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=Decimal(0), nullable=False)
    write_offs: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
