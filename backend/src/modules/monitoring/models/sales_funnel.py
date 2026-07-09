"""Sales-funnel (organic statistics) time-series model.

One row per ``(date, nm_id)`` — a composite primary key is intentional: the
architecture rules permit composite ``date + nm_id`` keys for time-series
aggregation tables, and it makes daily upserts idempotent.
"""

from __future__ import annotations

from datetime import date

from sqlalchemy import BigInteger, Date, Index, Integer, Numeric
from sqlalchemy.orm import Mapped, mapped_column

from src.core.database import Base

_SCHEMA: str = "monitoring"


class SalesFunnelDaily(Base):
    """Flattened daily organic funnel metrics for a single SKU.

    Sourced from ``POST /api/analytics/v3/sales-funnel/products`` and normalized
    to Moscow time (UTC+3) before persistence.

    Attributes:
        stat_date: Calendar day (Moscow time) the metrics belong to.
        nm_id: WB SKU identifier (``nmID``).
        open_count: Card views / clicks (``openCount``).
        cart_count: Add-to-cart events (``cartCount``).
        order_count: Orders generated (``orderCount``).
        order_sum: Ordered value in rubles (``orderSum``).
        buyout_count: Buyouts / redeemed orders (``buyoutCount``).
        buyout_sum: Buyout value in rubles (``buyoutSum``).
        add_to_wishlist: Add-to-favourites events (``addToWishlist``).
        cart_conversion: Flattened ``conversions.addToCartPercent``.
        order_conversion: Flattened ``conversions.cartToOrderPercent``.
        buyout_conversion: Flattened ``conversions.buyoutsPercent``.
    """

    __tablename__ = "sales_funnel_daily"
    __table_args__ = (
        # The PK leads with stat_date, so per-SKU reads (detail/funnel views:
        # nm_id + date range) need this dedicated index or they degrade to
        # scanning the whole window across all SKUs.
        Index("ix_sales_funnel_daily_nm_id_stat_date", "nm_id", "stat_date"),
        {"schema": _SCHEMA},
    )

    stat_date: Mapped[date] = mapped_column(Date, primary_key=True)
    nm_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)

    open_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    cart_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    order_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    order_sum: Mapped[float] = mapped_column(Numeric(14, 2), default=0, nullable=False)
    buyout_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    buyout_sum: Mapped[float] = mapped_column(Numeric(14, 2), default=0, nullable=False)
    add_to_wishlist: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    cart_conversion: Mapped[float] = mapped_column(Numeric(6, 2), default=0, nullable=False)
    order_conversion: Mapped[float] = mapped_column(Numeric(6, 2), default=0, nullable=False)
    buyout_conversion: Mapped[float] = mapped_column(Numeric(6, 2), default=0, nullable=False)
