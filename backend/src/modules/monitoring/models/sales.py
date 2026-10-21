"""Per-item sale/return records from the WB Statistics API.

One row per item OPERATION (``saleID``): an ``S``-prefixed id is a buyout
(sale), an ``R``-prefixed one a return. Rows are dated by the
SALE date — the day the customer accepted or returned the item — which is the
attribution the manager's «Выкупы, ₽» expects (the sales-funnel ``buyoutCount``
is an order-date cohort instead and matures for weeks).

Records are immutable facts upserted by ``sale_id``; the nightly harvest pulls
increments by ``lastChangeDate``, so retroactive changes (e.g. a late return)
land as their own ``R`` rows without rewriting history.
"""

from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import BigInteger, Boolean, Date, DateTime, Index, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from src.core.database import Base

_SCHEMA: str = "monitoring"


class SaleRecord(Base):
    """One sale or return operation of one item (WB Statistics API).

    Attributes:
        sale_id: WB operation identifier (``S…`` sale / ``R…`` return).
        srid: WB order-line identifier linking the operation to its order.
        nm_id: WB SKU identifier.
        sale_date: Calendar day (Moscow) the customer accepted/returned the item.
        is_return: True for a return (``R``-prefixed ``sale_id``).
        finished_price: What the customer actually paid, rubles (matches the
            portal's «Выкупили, ₽»).
        price_with_disc: Price after the seller's discount, rubles.
        for_pay: Amount payable to the seller, rubles.
        last_change_date: WB's change stamp driving incremental harvests.
    """

    __tablename__ = "sale_record"
    __table_args__ = (
        # Per-SKU daily aggregation reads (nm_id + date range).
        Index("ix_sale_record_nm_id_sale_date", "nm_id", "sale_date"),
        {"schema": _SCHEMA},
    )

    sale_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    srid: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    nm_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    sale_date: Mapped[date] = mapped_column(Date, nullable=False)
    is_return: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    finished_price: Mapped[float] = mapped_column(Numeric(12, 2), default=0, nullable=False)
    price_with_disc: Mapped[float] = mapped_column(Numeric(12, 2), default=0, nullable=False)
    for_pay: Mapped[float] = mapped_column(Numeric(12, 2), default=0, nullable=False)

    last_change_date: Mapped[datetime] = mapped_column(DateTime, nullable=False)
