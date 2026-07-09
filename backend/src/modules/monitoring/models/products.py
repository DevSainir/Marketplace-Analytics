"""Product catalogue dimension models (nmID -> vendor code / size labels).

Two slowly-changing dimensions sourced from the WB Content API
(``POST /content/v2/get/cards/list``), which is the authoritative source for the
human-readable identifiers the funnel and stock feeds omit:

* :class:`ProductCard` — one row per SKU (``nm_id``) carrying the seller
  ``vendor_code`` (the "Артикул продавца" column) and card ``title``.
* :class:`ProductSize` — one row per size characteristic (``chrt_id``) carrying
  its human ``tech_size`` label (the "Размер вещи" column, e.g. ``"52/170-177"``
  / ``"L"``), joined onto the label-less ``StockSnapshot`` rows by ``chrt_id``.

Keeping these as separate dimension tables (rather than columns on the
time-series facts) lets a single nightly catalogue sync refresh them without
touching the daily fact rows, and lets old fact rows LEFT JOIN nullably so they
keep working before the catalogue is first synced.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, String, func
from sqlalchemy.orm import Mapped, mapped_column

from src.core.database import Base

_SCHEMA: str = "monitoring"


class ProductCard(Base):
    """A SKU's catalogue identity: vendor code + title.

    Sourced from the Content API ``cards/list`` ``{nmID, vendorCode, title}``.

    Attributes:
        nm_id: WB SKU identifier (``nmID``); primary key.
        vendor_code: Seller article code (the "Артикул продавца", e.g.
            ``"M-TRX01-BLK"``).
        title: Card title (may be blank if the seller left it empty).
        synced_at: Timestamp of the last sync from WB.
    """

    __tablename__ = "product_card"
    __table_args__ = {"schema": _SCHEMA}

    nm_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    vendor_code: Mapped[str] = mapped_column(String(256), default="", nullable=False)
    title: Mapped[str] = mapped_column(String(512), default="", nullable=False)
    synced_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class ProductSize(Base):
    """A size characteristic's human label, keyed by WB's ``chrt_id``.

    Sourced from the Content API ``cards/list`` ``sizes[]``
    ``{chrtID, techSize, wbSize}``. ``chrt_id`` is the join key back to
    :class:`~src.modules.monitoring.models.stocks.StockSnapshot`, turning its
    label-less size id into a human size.

    Attributes:
        chrt_id: WB size characteristic id (``chrtID``); primary key.
        nm_id: Owning SKU identifier (denormalized for per-SKU lookups).
        tech_size: Human size label (the "Размер вещи", e.g. ``"52/170-177"`` /
            ``"L"`` / ``"42"``); may be blank for one-size items.
        wb_size: WB's alternate size scale (e.g. ``"2XL/ 170-177"`` / ``"46"``).
        synced_at: Timestamp of the last sync from WB.
    """

    __tablename__ = "product_size"
    __table_args__ = {"schema": _SCHEMA}

    chrt_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    nm_id: Mapped[int] = mapped_column(BigInteger, index=True, nullable=False)
    tech_size: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    wb_size: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    synced_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
