"""Response DTOs for the "Summary" surface.

One window, three cuts of it: the headline figures, the same figures per day for
the charts, and the per-article rows the category block is built from.
Everything is derived — nothing here is stored — so the schema exists to pin the
*shape* the page reads, not a table.

**Both price bases travel in every figure, and the rows are not pre-grouped.**
Which price revenue is shown at, whether the block is cut by article, subject or
brand, how it is sorted and how much of the tail is folded are all decisions a
reader changes several times a minute. Answering them on the server means a
round trip over 700 000 settlement rows per click; answering them from a payload
that already carries both bases and every row is arithmetic on data the browser
already has. The window is the only thing worth a request.

The recurring rule in the rest of the file is that ``None`` and ``0`` mean
different things and must stay distinguishable. A margin of ``None`` is "no cost
price on file", never "broke even"; orders of ``None`` is "the funnel does not
cover this window", never "nobody ordered". Collapsing either one into a zero
produces a page that looks confident and is wrong.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from pydantic import BaseModel


class SummaryKpi(BaseModel):
    """The headline cards.

    There is deliberately no fixed-cost line and no "Profit": this service has
    no source for taxes, salaries or rent, and a "Profit" computed without them
    would be a margin wearing a more confident name.
    """

    #: Net revenue at the price the buyer paid, after WB's SPP.
    revenue_paid: Decimal
    #: The same revenue at the seller's own price, before SPP. WB's payout is
    #: pegged to this one, which is why it is offered as a base at all.
    revenue_seller: Decimal
    #: Payout net of withholdings, less cost of goods and the advertising the
    #: seller actually paid for. ``None`` while any settled SKU has no cost
    #: price on file — see :attr:`uncosted_skus`.
    margin: Decimal | None
    sold_units: int
    #: ``None`` when the funnel does not cover the window.
    orders: int | None
    #: Deliveries bought out, over the lagged cohort window. ``None`` without
    #: coverage.
    buyouts: int | None
    #: Deliveries ANSWERED — bought out or refused — over the same window, and
    #: the only denominator :attr:`buyouts` may be divided by. WB's own
    #: buyout rate is defined this way, and it is what keeps the figure
    #: from starting near zero and climbing for three weeks: an order still in
    #: transit belongs to neither half rather than counting as a refusal.
    buyout_decided: int | None
    #: ``True`` when the figure had to be taken from the standing
    #: "21-7 days ago" window because the chosen period is too fresh to have
    #: decided deliveries of its own. The page says so rather than passing one
    #: period's rate off as another's.
    buyout_lagged: bool
    #: How many SKUs settled units in the window with no cost price on file.
    #: Non-zero is exactly why :attr:`margin` is ``None``.
    uncosted_skus: int
    #: Fines plus WB's other withholdings, WITHOUT the advertising invoices —
    #: those are :attr:`ad_spend`'s subject, and a figure that counted them in
    #: both places would be read as two different costs.
    penalties: Decimal
    #: What advertising actually cost the seller in the window, WB's bonuses
    #: removed. ``None`` without advertising coverage. The DRR card is this over
    #: revenue, computed by the page so it follows the price base.
    ad_spend: Decimal | None


class SummaryDay(BaseModel):
    """One day of the window, as the three charts read it."""

    day: date
    #: ``None`` on a day WB has not calculated yet. The window may legitimately
    #: run past the last settlement — orders and advertising arrive daily while
    #: the settlement lands weekly — and a zero there is a claim that the
    #: workspace sold nothing, which is a very different statement from «WB has
    #: not said yet». The chart breaks its line instead of dropping to the axis.
    revenue_paid: Decimal | None
    revenue_seller: Decimal | None
    #: ``None`` for the same reason as :attr:`SummaryKpi.margin`.
    margin: Decimal | None
    #: ``None`` on a day the funnel does not cover.
    orders: int | None
    #: What those orders were worth at the seller's own price, and at the price
    #: the customer pays. ``None`` when the day cannot be valued at all — the
    #: funnel publishes no money volume, so a day reached only by it and never
    #: priced has no volume, and zero would read as infinite DRR.
    orders_amount_seller: Decimal | None
    orders_amount_paid: Decimal | None
    #: Units WB calculated as sold that day, net of refunds. ``None`` on a day
    #: WB has not calculated.
    sold_units: int | None
    #: What the seller paid for advertising that day, bonuses removed. ``None``
    #: on a day the advertising statistics do not cover.
    ad_spend: Decimal | None


class SummarySkuRow(BaseModel):
    """One article's contribution, ungrouped.

    The page folds these by subject or brand itself. They are sent per article
    because that is the finest grain the settlement has — anything coarser can
    be derived from it, and nothing coarser can be un-derived.
    """

    nm_id: int
    #: The seller's article as WB stores it. The page uppercases it; WB keeps
    #: whatever casing was typed, so the same article arrives both ways.
    code: str
    subject: str
    brand: str
    revenue_paid: Decimal
    revenue_seller: Decimal
    #: ``None`` when this article has no cost price on file.
    margin: Decimal | None
    sold_units: int


class SummaryCoverage(BaseModel):
    """What the window actually rests on, per source.

    The three feeds end on different days — settlements lag the funnel by a
    couple of days because WB has not calculated them yet — so a window that
    looks complete can be complete in one figure and short in another.
    """

    settlement_from: date | None
    settlement_to: date | None
    funnel_from: date | None
    funnel_to: date | None
    advertising_from: date | None
    advertising_to: date | None


class SummarySpan(BaseModel):
    """The days a workspace has data for, for the period picker.

    Every feed, not the settlement alone: orders and advertising arrive daily
    while WB calculates settlements weekly, so ending every preset on the last
    settled day hid several days of the two figures that ARE current. The
    settlement's own end travels separately, because that is what the revenue
    line can be drawn to.

    Answered off the report headers and two min/max reads rather than the
    settlement detail, so the picker opens instantly.
    """

    date_from: date | None
    date_to: date | None
    #: Last day WB has calculated. Revenue and margin stop here; orders and
    #: advertising may run past it.
    settled_to: date | None = None


class SummaryResponse(BaseModel):
    """Everything the "Summary" page draws, for one window."""

    date_from: date
    date_to: date
    #: The settlement's currency — revenue, margin and fines are in it, and so
    #: are advertising and the orders' money volume: rouble ads are converted
    #: where they are stored (2026-10-02), the orders are WB's own funnel sums.
    currency: str
    kpi: SummaryKpi
    days: list[SummaryDay]
    rows: list[SummarySkuRow]
    coverage: SummaryCoverage
