"""Daily seller/customer price snapshot time-series model.

One row per ``(date, nm_id)`` — like :class:`~src.modules.monitoring.models.
stocks.StockSnapshot`, WB exposes no price history, so a daily snapshot is
captured on each harvest and accumulates a per-day series over time.

* ``seller_price`` — the seller's DISCOUNTED price (WB ``discountedPrice``, after
  the seller's own discount). Drives the matrix's «Заказы, ₽»/«Выкупы, ₽»
  (count x price) and is the base of the СПП ratio.
* ``customer_price`` — the final price a shopper pays after ALL discounts incl.
  WB loyalty (from the public ``card.wb.ru`` detail), or ``NULL`` when the
  storefront did not return it.

СПП (скидка постоянного покупателя) is DERIVED on read
(``(seller - customer) / seller x 100``), never stored.
"""

from __future__ import annotations

from datetime import date

from sqlalchemy import BigInteger, Date, Index, Numeric
from sqlalchemy.orm import Mapped, mapped_column

from src.core.database import Base

_SCHEMA: str = "monitoring"


class PriceSnapshot(Base):
    """Daily seller (discounted) and customer (post-loyalty) price for one SKU.

    Attributes:
        stat_date: Snapshot calendar day (Moscow time).
        nm_id: WB SKU identifier.
        seller_price: Seller discounted price in rubles (WB ``discountedPrice``).
        customer_price: Final customer price in rubles after all discounts
            (``card.wb.ru``); ``None`` when the storefront omitted the SKU.
    """

    __tablename__ = "price_snapshot"
    __table_args__ = (
        # Per-SKU reads (nm_id + date range) cannot use the stat_date-led PK.
        Index("ix_price_snapshot_nm_id_stat_date", "nm_id", "stat_date"),
        {"schema": _SCHEMA},
    )

    stat_date: Mapped[date] = mapped_column(Date, primary_key=True)
    nm_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)

    seller_price: Mapped[float | None] = mapped_column(Numeric(12, 2), nullable=True)
    customer_price: Mapped[float | None] = mapped_column(Numeric(12, 2), nullable=True)
