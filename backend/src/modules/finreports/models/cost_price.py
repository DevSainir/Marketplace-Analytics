"""Cost-price model — the seller's own cost per SKU, including fulfilment.

The one figure in the P&L that WildBerries does not know and cannot supply. It is
entered by the seller, so it is the only input the statement cannot verify — which
is precisely why it is stored apart from the harvested facts, in its own table,
with its own audit trail (``source``, ``note``, ``updated_at``). A number that
came from a person must never be indistinguishable from a number that came from
WB's documents.

Keyed on ``nm_id``, not on ``sa_name``/``barcode``: WB serves several vendor codes
for one ``nm_id`` over time (the same card has been sold as both
``w-longsleeve-anesthesia-blue`` and ``w-lsx01-dbl``), and a size-level barcode
would multiply the seller's data-entry work without adding accuracy — the cost is
per model, not per size.

One current cost per SKU, applied to the whole settlement history. Restating a
cost therefore restates past periods; that is the intended behaviour (a corrected
cost was always the *true* cost), and ``updated_at`` is what makes the restatement
visible after the fact.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import BigInteger, DateTime, Numeric, String, func
from sqlalchemy.orm import Mapped, mapped_column

from src.core.database import Base

_SCHEMA: str = "finreports"


class ProductCostPrice(Base):
    """One SKU's cost of goods, as the seller states it.

    Attributes:
        workspace_id: Owning workspace (tenancy; part of the natural key, so two
            sellers may cost the same ``nm_id`` differently).
        nm_id: WB SKU identifier.
        cost: Cost of one unit **including fulfilment**, in :attr:`currency`.
        currency: The currency the cost is stated in. Compared against the
            settlement currency before the figure is used — a cost in the wrong
            currency is dropped from the P&L with a note rather than silently
            converted at an invented rate.
        vendor_code: The seller's own article, carried for display so the editor
            can be read without cross-referencing WB.
        source: How the figure arrived (``manual`` for the CRUD API, ``seed`` for
            the initial load). Cheap provenance on an unverifiable input.
        note: Free-text justification, optional.
        updated_at: When the figure last changed — the restatement trail.
    """

    __tablename__ = "product_cost_price"
    __table_args__ = {"schema": _SCHEMA}

    workspace_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    nm_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)

    cost: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String(8), default="KGS", nullable=False)
    vendor_code: Mapped[str] = mapped_column(String(128), default="", nullable=False)
    source: Mapped[str] = mapped_column(String(16), default="manual", nullable=False)
    note: Mapped[str] = mapped_column(String(256), default="", nullable=False)

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
