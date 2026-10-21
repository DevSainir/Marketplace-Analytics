"""Response DTOs for one article's per-size P&L (the size sub-table).

The «По артикулам» table answers *which article* loses money; this answers
*which size of it does* — and the two failure modes it exists to show are size
specific. A size whose buyout runs ten points under the article's average pays
the return leg on every unit that comes back, and a size that sells at the same
price while costing twice the logistics is invisible in the article's average.

Everything here is MEASURED, never allocated. WB stamps the size on every
settlement row it bills, so each figure below is a sum over that size's own
rows and Σ sizes reconciles to the article's row exactly. There is no profit
line: advertising has no size at WB, and a margin per size built on an
allocated share of it was judged not worth the guess — the cut is for
comparing how sizes sell, and the article's row carries the profit.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from pydantic import BaseModel


class PnlSizeRow(BaseModel):
    """One size of one article over the window, in the settlement currency."""

    #: WB's ``ts_name``. Empty on the rows WB bills without a size — kept as a
    #: row of its own rather than folded into a neighbour, so the sizes still
    #: add up to the article.
    ts_name: str

    sold_units: int
    returned_units: int
    #: Forward logistics legs — units WB actually carried to a buyer. The
    #: denominator of :attr:`buyout_pct`, and the only size-level measurement
    #: of demand there is (the funnel's «Заказы» carry no size).
    delivered_units: int
    #: sold / delivered. ``None`` when nothing was carried in the window.
    buyout_pct: Decimal | None

    #: «Продажи» - «Возвраты» (sales minus returns) at what buyers paid.
    revenue_paid: Decimal
    #: The same net revenue at the seller's own pre-SPP price; the base of the
    #: percentages.
    revenue_seller_price: Decimal
    #: «Цена» — net revenue at the seller's price per bought-out unit, so price x
    #: units is the revenue beside it. ``None`` when net units are 0.
    average_price: Decimal | None

    logistics_total: Decimal
    logistics_pct: Decimal | None
    #: Logistics per forward leg — what one trip to a buyer costs on this size.
    logistics_per_delivery: Decimal | None
    penalties_total: Decimal

    #: «К перечислению» (payout) for this size, net of its own withholdings — the same
    #: formula the article's row uses, which is what makes the column sum back.
    payout_net: Decimal


class PnlSizesResponse(BaseModel):
    """One article's sizes for a settlement-date window."""

    nm_id: int
    sa_name: str
    date_from: date
    date_to: date
    currency: str
    #: One row per size, by WB's size label. No totals row: the sizes sum to
    #: the article's own row, which the drill-down opens under.
    rows: list[PnlSizeRow]
