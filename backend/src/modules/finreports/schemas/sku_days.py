"""Per-SKU, per-settlement-day P&L inputs — a cut for other modules, not a screen.

The heatmap paints one figure per article per day, and three of its figures —
revenue, units sold and profit — only exist in the settlement. This is the
smallest set that lets it derive them without re-implementing any of the money
rules: revenue and units as the «По артикулам» row computes them, the payout
already netted of what WB withheld on the SKU's own rows, and the cost of the
goods. Advertising is deliberately absent: it is the Promotion API's figure,
which the consumer already holds per day, and the settlement's own ad invoice
never lands on an article.

The day is ``rr_dt``, the settlement date — see ``docs/finreports/PNL.md`` §1 —
so a return can sit on a different day than its sale and a cell can be negative.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from pydantic import BaseModel


class PnlSkuDay(BaseModel):
    """One article on one settlement day, in the settlement currency."""

    nm_id: int
    day: date
    #: Sales minus refunds at the seller's own price, before WB's SPP — the
    #: base every percentage of the P&L is taken of (PNL.md §17).
    revenue_seller: Decimal
    sold_units: int
    returned_units: int
    #: The payout for the goods, net of the logistics, fines and other charges
    #: WB booked on this article's own rows.
    payout_net: Decimal
    #: Cost price x net units. ``None`` when the article has no cost price on
    #: file in the settlement currency — a profit built on a missing cost would
    #: be a revenue figure wearing a profit's label.
    cogs: Decimal | None


class PnlSkuDays(BaseModel):
    """Every settled SKU-day of a window."""

    #: The window's settlement currency; ``""`` when nothing settled in it.
    currency: str
    cells: list[PnlSkuDay]


class PnlSkuDaySales(BaseModel):
    """One article's settled sales on one day — the lean cut, for a ratio's denominator.

    The same ``revenue_seller`` as :class:`PnlSkuDay`, without the payout and
    the cost that make that cut expensive to build over a long window.
    """

    nm_id: int
    day: date
    revenue_seller: Decimal
