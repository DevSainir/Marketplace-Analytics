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

import uuid
from datetime import datetime

from sqlalchemy import BigInteger, DateTime, String, func
from sqlalchemy.orm import Mapped, mapped_column

from src.core.database import Base

_SCHEMA: str = "monitoring"

#: Column widths for WB's «Предмет» and «Бренд». WB's own names run to a few
#: dozen characters; the ingest truncates to these rather than failing a whole
#: catalogue page on one oversized value.
SUBJECT_MAX_LENGTH: int = 128
BRAND_MAX_LENGTH: int = 128


class ProductCard(Base):
    """A SKU's catalogue identity: vendor code + title + owning workspace.

    Sourced from the Content API ``cards/list`` ``{nmID, vendorCode, title}``.

    Doubles as the **SKU -> workspace registry** for multi-tenancy: WB assigns
    ``nmID`` globally (two seller accounts never share one), so this dimension
    is the single authoritative place recording which workspace a SKU belongs
    to. Every tenant-scoped read either semijoins this table or guards a path
    ``nm_id`` against it.

    Attributes:
        nm_id: WB SKU identifier (``nmID``); primary key.
        workspace_id: Owning workspace (soft reference into the ``workspaces``
            schema — no FK, keeping the modules decoupled; ``None`` only for
            legacy rows never claimed by a harvest, which are invisible to
            every workspace).
        vendor_code: Seller article code (the "Артикул продавца", e.g.
            ``"M-TRX01-BLK"``).
        title: Card title (may be blank if the seller left it empty).
        photo_url: The card's main gallery image on WB's public CDN, or ``""``
            when the card carries none — and also when WB named a host that is
            not WB's, because this value is rendered straight into an
            ``<img src>`` (see
            :func:`~src.integrations.wildberries.photos.is_wb_photo_url`).
            Stored rather than fetched per request: it changes only when the
            seller re-shoots the card, and the three screens that show it would
            otherwise cost a Content API call each — an endpoint whose page is
            100 cards and whose rate limit the harvest already spends.
        subject_name: WB's «Предмет» (e.g. «Костюмы»), ``""`` until the first
            catalogue sync that carried it. The heatmap groups and filters by it.
        brand: The card's brand, ``""`` the same way.
        synced_at: Timestamp of the last sync from WB.
    """

    __tablename__ = "product_card"
    __table_args__ = {"schema": _SCHEMA}

    nm_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    workspace_id: Mapped[uuid.UUID | None] = mapped_column(index=True, nullable=True)
    vendor_code: Mapped[str] = mapped_column(String(256), default="", nullable=False)
    title: Mapped[str] = mapped_column(String(512), default="", nullable=False)
    # `server_default` as well as `default`, unlike the two columns above: the
    # migration adds the column with one, so a model without it makes
    # `create_all` (the integration tier's schema) disagree with the migrated
    # schema (production's) about what an INSERT omitting this column does.
    photo_url: Mapped[str] = mapped_column(
        String(512), default="", server_default="", nullable=False
    )
    # `server_default` for the same reason as `photo_url`: the migration adds
    # both columns to a populated table, so it must give existing rows a value.
    subject_name: Mapped[str] = mapped_column(
        String(SUBJECT_MAX_LENGTH), default="", server_default="", nullable=False
    )
    brand: Mapped[str] = mapped_column(
        String(BRAND_MAX_LENGTH), default="", server_default="", nullable=False
    )
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
        barcode: The size's first WB barcode (``sizes[].skus[0]``), or blank
            when the card carries none. Stored solely because the FBS stock
            endpoint is queried BY barcode — every other WB surface identifies
            a size by ``chrt_id``. Only the first is kept: a size may carry
            several, but WB registers FBS stock against one, and the response
            echoes ``chrtId`` back so a second barcode would resolve to a row
            we already have.
        synced_at: Timestamp of the last sync from WB.
    """

    __tablename__ = "product_size"
    __table_args__ = {"schema": _SCHEMA}

    chrt_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    nm_id: Mapped[int] = mapped_column(BigInteger, index=True, nullable=False)
    tech_size: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    wb_size: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    barcode: Mapped[str] = mapped_column(String(32), default="", nullable=False)
    synced_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
