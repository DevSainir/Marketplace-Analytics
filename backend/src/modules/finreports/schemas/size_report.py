"""Response DTOs for one article's per-size P&L («подтаблица размеров»).

The «По артикулам» table answers *which article* loses money; this answers
*which size of it does* — and the two failure modes it exists to show are size
specific. A size whose buyout runs ten points under the article's average pays
the return leg on every unit that comes back, and a size that sells at the same
price while costing twice the logistics is invisible in the article's average.

Everything here is MEASURED, never allocated. WB stamps the size on every
settlement row it bills, so each figure below is a sum over that size's own
rows and Σ sizes reconciles to the article's row exactly. The one column the
article has and a size cannot is advertising: WB's Promotion API attributes
spend to an ``nm_id`` and knows nothing about sizes, so the profit line here is
:attr:`PnlSizeRow.margin_before_ads` — named for what it leaves out, rather than
a «чистая прибыль» quietly built on a revenue-share guess.
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
    #: This size's buyout less the article's own, in percentage POINTS —
    #: negative means it is bought out worse than its siblings. ``None`` when
    #: either side is undefined.
    buyout_vs_article_pp: Decimal | None

    #: Продажи - Возвраты at what buyers paid; the base of the percentages.
    revenue_paid: Decimal
    #: The same net revenue at the seller's own pre-СПП price.
    revenue_seller_price: Decimal
    spp_pct: Decimal | None
    #: Средний чек — net revenue per bought-out unit. ``None`` when net units 0.
    average_cheque: Decimal | None

    logistics_total: Decimal
    logistics_pct: Decimal | None
    #: Logistics per forward leg — what one trip to a buyer costs on this size.
    logistics_per_delivery: Decimal | None
    penalties_total: Decimal

    #: The article's per-unit cost x this size's net units; ``None`` without a
    #: cost on file (the article's cost applies to all of its sizes — WB's
    #: settlement has no per-size cost and neither does the seller's sheet).
    cogs: Decimal | None
    #: К перечислению for this size, net of its own withholdings — the same
    #: formula the article's row uses, which is what makes the column sum back.
    payout_net: Decimal
    #: payout_net - cogs. NOT «чистая прибыль»: advertising has no size, so it
    #: is missing here and present on the article. ``None`` without a cost.
    margin_before_ads: Decimal | None
    margin_pct: Decimal | None


class PnlSizesResponse(BaseModel):
    """One article's sizes for a settlement-date window."""

    nm_id: int
    sa_name: str
    date_from: date
    date_to: date
    currency: str
    #: One row per size, by WB's size label.
    rows: list[PnlSizeRow]
    #: The same shape over all of them — what the article's own row says, cut
    #: to the columns a size row carries.
    totals: PnlSizeRow
