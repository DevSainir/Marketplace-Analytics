"""Ordered item lines from the WB Statistics API — one row per ``srid``.

The funnel («Воронка продаж») is what a кабинет has from the day we started
harvesting it — 17.07.2025 for this service's oldest one. This feed is what WB
has had all along: ``supplier/orders`` answers from any ``dateFrom``, so a
кабинет's whole ordering history is reachable, which is the only way «Заказы» on
«Сводка» can cover the same period as the settlement.

Rows are dated by the ORDER date — when the customer placed it — which is the
attribution «Заказы в день» and «ДРР от заказов» both mean. That is a different
clock from ``sale_record`` next door, which is dated by the day the customer
accepted or returned the item.

Both prices travel, because both are shown: ``price_with_disc`` is the seller's
own price after their discount, ``finished_price`` what the customer pays with
WB's СПП applied. Storing them per line is also what frees «ДРР от заказов» from
the price snapshots — the funnel publishes no money at all, so before this the
ordered volume was ``counts x a price we happened to have snapshotted``.

A cancelled line is kept and flagged rather than deleted: WB cancels days after
the fact, and a row that vanishes turns a day that HAD orders into a day that
looks unharvested.
"""

from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import BigInteger, Boolean, Date, DateTime, Index, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from src.core.database import Base

_SCHEMA: str = "monitoring"


class OrderRecord(Base):
    """One ordered item line (WB Statistics API).

    Attributes:
        srid: WB's order-line identifier — the row's identity, and what
            deduplicates the overlapping pages of the feed.
        nm_id: WB SKU identifier.
        order_date: Calendar day (Moscow) the order was placed.
        is_cancel: True once the customer cancelled the line.
        price_with_disc: Seller's price after the seller's discount.
        finished_price: What the customer pays, WB's СПП applied.
        last_change_date: WB's change stamp, which drives the walk's cursor.
    """

    __tablename__ = "order_record"
    __table_args__ = (
        # The daily series: every read is a workspace's SKUs over a date range.
        Index("ix_order_record_nm_id_order_date", "nm_id", "order_date"),
        {"schema": _SCHEMA},
    )

    srid: Mapped[str] = mapped_column(String(128), primary_key=True)
    nm_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    order_date: Mapped[date] = mapped_column(Date, nullable=False)
    is_cancel: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    price_with_disc: Mapped[float] = mapped_column(Numeric(12, 2), default=0, nullable=False)
    finished_price: Mapped[float] = mapped_column(Numeric(12, 2), default=0, nullable=False)

    last_change_date: Mapped[datetime] = mapped_column(DateTime, nullable=False)
