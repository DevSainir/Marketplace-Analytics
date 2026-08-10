"""Marks on the «Баланс по товарным остаткам» grid — a seller editorial choice.

The balance table is a SKU x warehouse grid wide enough that the rows and
columns a seller actually watches scroll out of sight. Pinning («Закрепить»)
floats them to the front: pinned SKUs sort above every unpinned one, pinned
warehouses ahead of every unpinned column. The third mark is the opposite —
«Не считать» sends a warehouse to the far right and out of every total.

Deliberately NOT monitoring's ``warehouse_mark``, which is the «Отгрузить» flag
of ONE SKU's stock breakdown — a mark there says «I ship *this* article to Тула»
and would say nothing about the column of a grid that spans the whole catalogue.
Here a warehouse pin is grid-wide, so the two cannot share a table without one
silently moving the other's rows.

Rows and columns share this one table because they are the same gesture on the
same grid: the presence of a row *is* the pin, keyed
``(workspace_id, kind, value)``, and unpinning deletes it — idempotent both ways.
A pin never touches a figure; it only decides what is on screen first.
"""

from __future__ import annotations

import enum
import uuid
from datetime import datetime

from sqlalchemy import DateTime, String, func
from sqlalchemy.orm import Mapped, mapped_column

from src.core.database import Base

_SCHEMA: str = "finreports"


class BalancePinKind(enum.StrEnum):
    """What a mark is attached to, and what it does to the grid."""

    #: A SKU row pinned to the top, ``value`` being its ``nm_id`` as text.
    SKU = "sku"
    #: A warehouse column pinned to the left, ``value`` being the WB name.
    WAREHOUSE = "warehouse"
    #: A warehouse marked «Не считать»: its stock stays visible but is left out
    #: of every total, and the column sorts to the far right. For warehouses
    #: whose stock is not the seller's to count — goods already written off,
    #: or a transit point they do not sell from.
    WAREHOUSE_UNCOUNTED = "warehouse_uncounted"
    #: The same mark on a SKU row: still shown, still priced, sorted to the
    #: bottom and out of the totals. For stock the seller does not count as
    #: theirs — a discontinued line, or goods held for someone else.
    SKU_UNCOUNTED = "sku_uncounted"


class BalancePin(Base):
    """One pinned row or column of the balance grid, per workspace.

    Attributes:
        workspace_id: Owning workspace (tenancy; part of the natural key, so the
            pin is shared across every user of that workspace and only theirs).
        kind: Whether the pin is on a SKU row or a warehouse column.
        value: The pinned ``nm_id`` (as text) or warehouse name. Stored as text
            for both kinds so one table serves both; the ``kind`` says how to
            read it, and no arithmetic is ever done on it.
        created_at: When it was pinned — a light audit trail.
    """

    __tablename__ = "balance_pin"
    __table_args__ = {"schema": _SCHEMA}

    workspace_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    kind: Mapped[str] = mapped_column(String(32), primary_key=True)
    value: Mapped[str] = mapped_column(String(128), primary_key=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
