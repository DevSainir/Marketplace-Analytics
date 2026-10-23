"""Marks on the "Stock balance" grid — a seller editorial choice.

One mark, on either axis: "Don't count" sends a warehouse column or a SKU row to
the far end of the grid and out of every total, while leaving its figures on
screen — for stock that is not the seller's to count, and which they still want
to see.

Rows and columns share this one table because they are the same gesture on the
same grid: the presence of a row *is* the mark, keyed
``(workspace_id, kind, value)``, and clearing it deletes the row — idempotent
both ways. A mark never touches a figure; it only decides what the totals are
drawn from.

The table used to carry two more kinds, ``sku`` and ``warehouse``, for a
"Pin" that floated a row or column to the front. That feature was removed
in 0.35; migration ``a3f81c2e57d4`` deleted their rows. ``kind`` is a plain text
column rather than a PG enum, which is what made that a ``DELETE`` and not a
type rewrite — keep it that way.
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

    #: A warehouse marked "Don't count": its stock stays visible but is left out
    #: of every total, and the column sorts to the far right. For warehouses
    #: whose stock is not the seller's to count — goods already written off,
    #: or a transit point they do not sell from.
    WAREHOUSE_UNCOUNTED = "warehouse_uncounted"
    #: The same mark on a SKU row: still shown, still priced, sorted to the
    #: bottom and out of the totals. For stock the seller does not count as
    #: theirs — a discontinued line, or goods held for someone else.
    SKU_UNCOUNTED = "sku_uncounted"


class BalancePin(Base):
    """One marked row or column of the balance grid, per workspace.

    Attributes:
        workspace_id: Owning workspace (tenancy; part of the natural key, so the
            mark is shared across every user of that workspace and only theirs).
        kind: Whether the mark is on a SKU row or a warehouse column.
        value: The marked ``nm_id`` (as text) or warehouse name. Stored as text
            for both kinds so one table serves both; the ``kind`` says how to
            read it, and no arithmetic is ever done on it.
        created_at: When it was marked — a light audit trail.
    """

    __tablename__ = "balance_pin"
    __table_args__ = {"schema": _SCHEMA}

    workspace_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    kind: Mapped[str] = mapped_column(String(32), primary_key=True)
    value: Mapped[str] = mapped_column(String(128), primary_key=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
