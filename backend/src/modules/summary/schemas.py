"""Response DTOs for the «Сводка» surface.

One window, three cuts of it: the headline figures, the same figures per day for
the charts, and a ranking of who produced them. Everything is derived — nothing
here is stored — so the schema exists to pin the *shape* the page reads, not a
table.

The recurring rule in this file is that ``None`` and ``0`` mean different things
and must stay distinguishable. A margin of ``None`` is "no cost price on file",
never "broke even"; orders of ``None`` is "the funnel does not cover this
window", never "nobody ordered". Collapsing either one into a zero produces a
page that looks confident and is wrong.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from enum import StrEnum

from pydantic import BaseModel


class RevenueBase(StrEnum):
    """Which price the revenue figures are taken at.

    WB's СПП is a discount funded by WB, not by the seller, so the two bases
    answer different questions: ``PAID`` is what the buyer handed over, ``SELLER``
    is the seller's own pre-discount price, and WB's payout is pegged to the
    latter.
    """

    PAID = "paid"
    SELLER = "seller"


class CategoryGrouping(StrEnum):
    """How the «Выручка по категории» block is cut."""

    SKU = "sku"
    SUBJECT = "subject"
    BRAND = "brand"


class SummaryKpi(BaseModel):
    """The headline cards.

    There is deliberately no fixed-cost line and no «Прибыль»: this service has
    no source for taxes, salaries or rent, and a «Прибыль» computed without them
    would be a margin wearing a more confident name.
    """

    revenue: Decimal
    #: Payout net of withholdings, less cost of goods and the advertising the
    #: seller actually paid for. ``None`` while any settled SKU has no cost
    #: price on file — see :attr:`uncosted_skus`.
    margin: Decimal | None
    margin_pct: Decimal | None
    sold_units: int
    #: ``None`` when the funnel does not cover the window.
    orders: int | None
    #: Bought-out units over ordered units. Taken as settled units / orders so
    #: it agrees with the two cards standing next to it; WB's own buyout counter
    #: is reported separately as :attr:`buyout_counted_pct`.
    buyout_pct: Decimal | None
    #: WB's direct buyout counter from the funnel, for the same window.
    buyout_counted_pct: Decimal | None
    average_cheque: Decimal | None
    #: How many SKUs settled units in the window with no cost price on file.
    #: Non-zero is exactly why :attr:`margin` is ``None``.
    uncosted_skus: int


class SummaryDay(BaseModel):
    """One day of the window, as the three charts read it."""

    day: date
    revenue: Decimal
    #: ``None`` for the same reason as :attr:`SummaryKpi.margin`.
    margin: Decimal | None
    #: ``None`` on a day the funnel does not cover.
    orders: int | None
    #: What the seller paid for advertising that day, bonuses removed. ``None``
    #: on a day the advertising statistics do not cover.
    ad_spend: Decimal | None


class SummaryCategory(BaseModel):
    """One bar of «Выручка по категории»."""

    key: str
    label: str
    revenue: Decimal
    revenue_share_pct: Decimal
    margin: Decimal | None
    #: Share of the window's total margin. ``None`` when the margin is unknown,
    #: and legitimately negative when the bar lost money.
    margin_share_pct: Decimal | None
    margin_pct: Decimal | None
    sold_units: int
    #: How many SKUs this bar covers — 1 for a SKU cut, more for subjects and
    #: brands. What makes «ещё N» honest when the tail is folded.
    sku_count: int


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


class SummaryResponse(BaseModel):
    """Everything the «Сводка» page draws, for one window."""

    date_from: date
    date_to: date
    currency: str
    revenue_base: RevenueBase
    grouping: CategoryGrouping
    kpi: SummaryKpi
    days: list[SummaryDay]
    categories: list[SummaryCategory]
    coverage: SummaryCoverage
