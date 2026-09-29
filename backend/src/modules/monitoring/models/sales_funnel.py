"""Sales-funnel (organic statistics) time-series model.

One row per ``(date, nm_id)`` — a composite primary key is intentional: the
architecture rules permit composite ``date + nm_id`` keys for time-series
aggregation tables, and it makes daily upserts idempotent.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from sqlalchemy import BigInteger, Date, Index, Integer, Numeric, String
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
        buyout_count: Buyouts / redeemed orders (``buyoutCount``).
        cancel_count: Deliveries the buyer refused (``cancelCount``). Together
            with ``buyout_count`` this is the cohort's DECIDED deliveries — the
            denominator of «Процент выкупа». Only the period-aggregate endpoint
            serves it, so it is refreshed by the cohort pass, not the daily
            history feed; ``None`` means "not refreshed yet" (excluded from the
            average rather than counted as zero refusals).
        add_to_wishlist: Add-to-favourites events (``addToWishlist``).
        cart_conversion: Flattened ``conversions.addToCartPercent``.
        order_conversion: Flattened ``conversions.cartToOrderPercent``.
        buyout_conversion: Flattened ``conversions.buyoutsPercent`` — WB's own
            whole-number cohort percent. Kept as a raw WB fact; the matrix does
            NOT derive «Процент выкупа» from it (it is rounded to an integer and
            is 0 for a zero-buyout cohort, which loses that cohort's refusals).
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
    buyout_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    # Nullable: NULL = "no aggregate refresh has landed for this cohort yet".
    cancel_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    add_to_wishlist: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    # The funnel's money, in :attr:`currency` — which is the кабинет's
    # SETTLEMENT currency, not the prices' RUB: WB converts each order's RUB
    # price at the Bank of Russia rate of the order day (wildberries-api,
    # references/currencies.md). NULL = not yet read for this day (rows from
    # before 2026-09-29, until the backfill reaches them). The history feed
    # owns ``order_sum``; ``buyout_sum``/``cancel_sum`` mature like their
    # counts and are the cohort pass's after the first insert.
    order_sum: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), nullable=True)
    buyout_sum: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), nullable=True)
    cancel_sum: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), nullable=True)
    currency: Mapped[str] = mapped_column(String(8), server_default="", nullable=False)

    cart_conversion: Mapped[float] = mapped_column(Numeric(6, 2), default=0, nullable=False)
    order_conversion: Mapped[float] = mapped_column(Numeric(6, 2), default=0, nullable=False)
    buyout_conversion: Mapped[float] = mapped_column(Numeric(6, 2), default=0, nullable=False)
