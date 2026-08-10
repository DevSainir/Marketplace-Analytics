"""Response DTOs for «Баланс по товарным остаткам» — the stock balance grid.

One picked DAY, not a period: remaining stock is a snapshot WB reports per day
with no carry-over, so a range would have to either sum quantities that are the
same units counted twice or silently pick one of its days.

The grid is SKU x warehouse. Every cell carries two figures — the units still
lying there, and what they cost the seller to put there (units x the cost price
already on file). The second is the whole point of the table: a warehouse row of
«72» says nothing about whether the money tied up in it is 6 000 or 600 000.

A SKU with no cost price on file keeps its quantities and reports ``None`` for
every money figure, exactly as the P&L does — a balance computed against free
goods is worse than no figure. Such SKUs are counted in ``uncosted_count``, and
the totals the client draws are then honest partial sums of the costed ones.

**What this response deliberately does NOT carry: the totals.** The grid's marks
(pin, «Не считать») and its search apply the moment they are clicked, without a
round trip, and each of them changes every total on screen — so the panels are
summed by the client from these priced cells. Sending server-side totals as well
would be a second implementation of the same addition, guaranteed to disagree
with the screen the moment a mark is applied optimistically. What the backend
owns is what only it can know: the prices, the identity, the persisted marks.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from pydantic import BaseModel

from src.modules.finreports.models import BalancePinKind


class BalancePinInput(BaseModel):
    """Request body for marking a SKU row or a warehouse column."""

    kind: BalancePinKind
    #: ``nm_id`` as text for a SKU mark, the WB warehouse name for a column one.
    value: str
    pinned: bool


class BalanceCell(BaseModel):
    """One SKU's stock at one warehouse, and what it cost to put there."""

    warehouse_name: str
    quantity: int
    #: quantity x cost price; ``None`` when the SKU has no cost on file.
    balance: Decimal | None


class BalanceSkuRow(BaseModel):
    """One SKU's row of the grid."""

    nm_id: int
    sa_name: str
    #: Kept out of the columns (the grid has no room) but filterable on screen.
    subject_name: str
    brand_name: str

    #: The seller's own cost per unit; ``None`` = not on file.
    cost_price: Decimal | None

    #: Only warehouses where this SKU actually has stock — an absent warehouse
    #: is a blank cell, not a zero.
    cells: list[BalanceCell]


class BalanceResponse(BaseModel):
    """The whole grid for one snapshot day."""

    #: The day actually rendered — the requested one, or the newest snapshot day
    #: when the request named none.
    stat_date: date
    #: The snapshot days on record, bounding the day picker. ``None`` when the
    #: workspace has no stock history at all.
    available_from: date | None
    available_to: date | None
    currency: str

    #: Rows, largest balance first. The client re-orders them as marks change.
    rows: list[BalanceSkuRow]

    #: SKUs pinned to the top of the grid.
    pinned_skus: list[int]
    #: Warehouses pinned to the left of the grid.
    pinned_warehouses: list[str]
    #: Warehouses marked «Не считать»: shown, sorted last, and left out of every
    #: total the client draws.
    uncounted_warehouses: list[str]
    #: SKUs marked «Не считать» — the same, one axis over: the row is shown and
    #: keeps its own «Итого по артикулу», but contributes to no column total and
    #: not to the corner.
    uncounted_skus: list[int]

    #: How many rows carry quantities but no cost — the size of the gap in any
    #: money total drawn from this response.
    uncosted_count: int
    notes: list[str]
