"""Seller-owned (FBS) warehouse directory — discovered from WB, labelled once.

Every warehouse WB reports for the seller is harvested, so the set is not
configured anywhere: it is whatever ``GET /api/v3/warehouses`` returns, and a
warehouse the seller opens tomorrow is read on the next run without a deploy.

What IS pinned here is the label. ``StockSnapshot.warehouse_name`` is part of
that table's primary key (and of every «Отгрузить» mark), so the name a
warehouse's stock is filed under has to survive the seller renaming it in the
WB portal — their names are editable working notes (a person, a district, a
"do not delete" reminder), not identifiers. So the label is resolved ONCE, on
first sight, and stored; afterwards only the WB id is matched.

Which makes ``Settings.wb_fbs_warehouse_labels`` a seeding map, not a setting:
editing an entry renames nothing, because the label in force is the frozen copy
here. A real rename has to move ``stock_snapshot.warehouse_name`` with it, in one
transaction — see the ``c7e4a1d90b62`` migration for the shape of it (it also
carried the «Отгрузить» marks, a feature since removed).

Keyed by the WB warehouse id alone, with no workspace column: the ids are
WB-global, so two workspaces can never collide on one.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, String, func
from sqlalchemy.orm import Mapped, mapped_column

from src.core.database import Base

_SCHEMA: str = "monitoring"

#: ``StockSnapshot.warehouse_name`` is ``String(128)``; a label longer than the
#: column it is filed into could not be stored at all.
LABEL_MAX_LENGTH = 128


class FbsWarehouse(Base):
    """One seller warehouse and the label its stock is filed under.

    Attributes:
        warehouse_id: WB id of the seller warehouse (``WBFbsWarehouse.id``).
        label: The frozen display name — written to
            ``StockSnapshot.warehouse_name`` and shown as the column header.
        wb_name: What WB called the warehouse when it was last seen. Diagnostic
            only: a rename shows up here without disturbing the label.
        discovered_at: When the harvest first saw this warehouse.
        last_seen_at: When the harvest last saw it listed. A warehouse the
            seller deletes stops advancing, and its stock history stays.
    """

    __tablename__ = "fbs_warehouse"
    __table_args__ = {"schema": _SCHEMA}

    warehouse_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)

    label: Mapped[str] = mapped_column(String(LABEL_MAX_LENGTH), nullable=False)
    wb_name: Mapped[str] = mapped_column(String(256), default="", nullable=False)
    discovered_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
