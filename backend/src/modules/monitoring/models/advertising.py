"""Advertising full-stats time-series model.

Flattens the nested ``apps`` (platform) -> ``nms`` (SKU) tree from WB into one
row per ``(date, campaign_id, app_type, nm_id)``. The four-column composite key
matches the natural grain of the source data and makes re-ingestion idempotent.
"""

from __future__ import annotations

from datetime import date

from sqlalchemy import BigInteger, Date, Integer, Numeric
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
    """

    __tablename__ = "advertising_stat_daily"
    __table_args__ = {"schema": _SCHEMA}

    stat_date: Mapped[date] = mapped_column(Date, primary_key=True)
    campaign_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    app_type: Mapped[int] = mapped_column(Integer, primary_key=True)
    nm_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)

    views: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    clicks: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    add_to_cart: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    spend: Mapped[float] = mapped_column(Numeric(14, 2), default=0, nullable=False)
    orders: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
