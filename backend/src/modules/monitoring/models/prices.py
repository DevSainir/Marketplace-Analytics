"""Daily seller/customer price snapshot time-series model.

One row per ``(date, nm_id)`` — like :class:`~src.modules.monitoring.models.
stocks.StockSnapshot`, WB exposes no price history, so a daily snapshot is
captured on each harvest and accumulates a per-day series over time.

* ``seller_price`` — the seller's DISCOUNTED price (WB ``discountedPrice``, after
  the seller's own discount). Drives the matrix's "Orders, ₽"/"Buyouts, ₽"
  (count x price) and is the base of the SPP ratio.
* ``customer_price`` — the final price a shopper pays after ALL discounts incl.
  WB loyalty, or ``NULL`` when neither source could answer.
* ``customer_spp`` — WB's loyalty discount as a percent, when it is known as a
  number rather than inferred from the two prices.
* ``customer_source`` — which of the two answered, because they are not the same
  measurement and a silent swap would move a user-visible figure with nothing to
  point at. ``storefront`` is the shelf price for one fixed region at one moment
  of the morning; ``orders`` is what customers were actually charged that day.

SPP (WB's customer discount) is DERIVED on read
(``(seller - customer) / seller x 100``), never stored.
"""

from __future__ import annotations

from datetime import date

from sqlalchemy import BigInteger, Date, Index, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from src.core.database import Base

_SCHEMA: str = "monitoring"


class PriceSnapshot(Base):
    """Daily seller (discounted) and customer (post-loyalty) price for one SKU.

    Attributes:
        stat_date: Snapshot calendar day (Moscow time).
        nm_id: WB SKU identifier.
        seller_price: Seller discounted price in rubles (WB ``discountedPrice``).
        customer_price: Final customer price in rubles after all discounts;
            ``None`` when neither source answered for this SKU.
        customer_spp: WB's loyalty discount in percent, as WB itself states it
            (whole numbers — WB rounds 12,4 % down to 12); ``None`` when the
            answering source does not publish it.
        customer_source: ``storefront`` or ``orders`` — which measurement
            ``customer_price`` is. ``None`` for rows written before the column
            existed, which are all storefront.
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
    customer_spp: Mapped[float | None] = mapped_column(Numeric(5, 2), nullable=True)
    customer_source: Mapped[str | None] = mapped_column(String(16), nullable=True)
    #: ISO code WB gave the seller price in (``currencyIsoCode4217``), ``""``
    #: where it was not recorded. Not the settlement's currency — see
    #: :class:`~src.integrations.wildberries.schemas.prices.WBPriceGood`.
    currency: Mapped[str] = mapped_column(String(8), default="", server_default="", nullable=False)
