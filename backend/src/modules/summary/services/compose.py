"""The «Сводка» arithmetic — pure functions over already-loaded figures.

Nothing here touches a session. Every input is a DTO the finreports and
monitoring contracts already produced, which is what lets the whole surface be
tested against hand-written numbers instead of against a database.

Three rules run through all of it:

* **No cost price, no margin.** A window where any settled SKU has no cost on
  file reports ``margin = None``, not a margin computed against free goods. The
  per-SKU report is softer — it sums the costed rows and counts the rest — which
  is right for a table a seller reads row by row and wrong for one headline
  number, where the omission is invisible.
* **Advertising is charged once, and the invoice is not the copy that survives.**
  WB withholds it as one invoice per week, already inside «к перечислению», and
  the Promotion API reports the same spend dated to the days the ads ran. The
  invoice goes back and the burn comes off, so a day-grained margin neither
  craters on invoice days nor counts the charge twice.
* **Presentation is not computed here.** Which price base is shown, how the rows
  are grouped, sorted or folded — none of that reaches this module. Both bases
  travel on every figure and the rows go out per article, so the page answers
  those questions from data it already holds instead of through a round trip
  over the whole settlement window.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from src.modules.finreports.contract import PnlSkuReportResponse, PnlStatement
from src.modules.monitoring.contract import AdSpendDay, OrderDay
from src.modules.summary.schemas import SummaryDay, SummaryKpi, SummarySkuRow

_ZERO = Decimal(0)


def uncosted_skus(report: PnlSkuReportResponse) -> int:
    """Count SKUs that moved units in the window with no cost price on file.

    Units, not revenue: a SKU whose only rows are a refund still consumed a cost
    that is not known, and it is exactly the kind of row that would quietly drag
    a margin up. A SKU whose sales and refunds cancel exactly contributes no cost
    either way, so an unknown price there costs nothing and is not counted.
    """
    return sum(
        1
        for row in report.rows
        if row.cost_price is None and (row.sold_units - row.returned_units) != 0
    )


def build_kpi(
    *,
    report: PnlSkuReportResponse,
    orders: int | None,
    buyouts: int | None,
    ad_cash: Decimal | None,
    settled_advertising: Decimal,
) -> SummaryKpi:
    """Assemble the headline cards from the reconciled window totals.

    Args:
        report: The per-SKU P&L for the window — its ``totals`` row is the full
            reconciled window, account-level money included.
        orders: Funnel orders for the window; ``None`` without coverage.
        buyouts: WB's own buyout counter for the window; ``None`` without it.
        ad_cash: Advertising the seller actually paid for, bonuses removed;
            ``None`` without advertising coverage.
        settled_advertising: The «WB Продвижение» invoices the window's
            settlement withheld.

    Returns:
        The cards, with every unknown left as ``None``.
    """
    totals = report.totals
    missing = uncosted_skus(report)

    # Advertising is subtracted exactly ONCE. «К перечислению» is already net of
    # WB's weekly invoice, so taking `ad_cash` off it as well charges the same
    # advertising twice — 2 657 954.54 against a true 4 313 444.72 on one live
    # 54-day window. With no advertising coverage there is no burn to swap in,
    # and the invoice stays where the settlement put it.
    swap = settled_advertising if ad_cash is not None else _ZERO
    margin = (
        None if missing else totals.payout_net + swap - (totals.cogs or _ZERO) - (ad_cash or _ZERO)
    )

    return SummaryKpi(
        revenue_paid=totals.revenue_paid,
        revenue_seller=totals.revenue_seller_price,
        margin=margin,
        sold_units=totals.sold_units - totals.returned_units,
        orders=orders,
        buyouts=buyouts,
        uncosted_skus=missing,
    )


def build_days(
    *,
    buckets: list[PnlStatement],
    order_days: list[OrderDay],
    ad_days: list[AdSpendDay],
    costed: bool,
) -> list[SummaryDay]:
    """Assemble the daily series the three charts read.

    The margin of a day is the settlement's own margin with the advertising
    swapped: WB's weekly invoice — which the settlement charged to whichever day
    it closed on — is added back, and that day's actual burn is taken off.

    The bonus is spread across the window in proportion to each day's spend
    rather than taken per day. WB writes bonuses off in batches, so a day's own
    ledger rows routinely exceed that day's impressions; apportioning over the
    window keeps every day non-negative AND keeps the series summing to the
    window's advertising cost, which a per-day clamp would not.

    Args:
        buckets: The P&L statement cut by settlement date.
        order_days: Funnel days; days it omits are days without coverage.
        ad_days: Advertising days, raw spend and raw bonus.
        costed: Whether every settled SKU in the window has a cost price. When
            it does not, no day gets a margin — the same rule as the headline.

    Returns:
        One entry per day ANY feed covers, ascending.
    """
    orders_by_day = {day.stat_date: day.orders for day in order_days}

    total_spend = sum((day.spend for day in ad_days), _ZERO)
    total_bonus = sum((day.bonus for day in ad_days), _ZERO)
    # Clamped once, over the window: a ledger row dated just inside a window
    # whose impressions fell just outside it must not make advertising negative.
    applied_bonus = min(total_bonus, total_spend)
    # The last day takes whatever the rounding left over, so Σ days is the
    # window's advertising cost EXACTLY rather than within a kopeck of it. On a
    # live 54-day window the drift was three kopecks — invisible on screen and
    # enough to make «the chart sums to the card» a claim with an asterisk.
    cash_by_day: dict[date, Decimal] = {}
    assigned = _ZERO
    for position, entry in enumerate(ad_days):
        if position == len(ad_days) - 1:
            share = applied_bonus - assigned
        else:
            share = (
                (applied_bonus * entry.spend / total_spend).quantize(Decimal("0.01"))
                if total_spend
                else _ZERO
            )
            assigned += share
        cash_by_day[entry.stat_date] = entry.spend - share

    settled = {bucket.date_from: bucket for bucket in buckets if bucket.date_from is not None}
    ad_by_day = {day.stat_date: day for day in ad_days}

    days: list[SummaryDay] = []
    # Every day ANY feed covers, not only the settled ones. The window can
    # legitimately run past the last settlement — WB calculates weekly and
    # serves late, while the funnel and the promotion statistics land daily —
    # and those days used to vanish from all three charts rather than showing
    # the orders and the spend we do have.
    for day in sorted(settled.keys() | orders_by_day.keys() | ad_by_day.keys()):
        bucket = settled.get(day)
        ad_cash = cash_by_day.get(day)
        margin = None
        if costed and bucket is not None:
            # bucket.advertising is the «WB Продвижение» invoice the settlement
            # charged on this date; bucket.margin_profit has already subtracted
            # it inside «Удержания».
            margin = bucket.margin_profit + bucket.advertising - (ad_cash or _ZERO)
        days.append(
            SummaryDay(
                day=day,
                # None, never zero, on a day WB has not calculated: the line
                # stops instead of reporting a collapse in sales.
                revenue_paid=bucket.revenue_paid if bucket else None,
                revenue_seller=bucket.revenue_seller_price if bucket else None,
                margin=margin,
                orders=orders_by_day.get(day),
                ad_spend=ad_cash,
            )
        )
    days.sort(key=lambda entry: entry.day)
    return days


def build_rows(report: PnlSkuReportResponse) -> list[SummarySkuRow]:
    """Carry the per-article rows the category block is folded from.

    Account-level money is NOT among them and is not spread across them. It has
    no article, no subject and no brand, so every way of dividing it would be an
    invention; the window's own advertising and penalties reach their articles
    from the sources that do carry one. What is left over stays outside this list
    and inside the headline.

    Args:
        report: The per-SKU P&L for the window.

    Returns:
        One row per settled article, in the report's own order.
    """
    return [
        SummarySkuRow(
            nm_id=row.nm_id,
            code=row.sa_name,
            subject=row.subject_name,
            brand=row.brand_name,
            revenue_paid=row.revenue_paid,
            revenue_seller=row.revenue_seller_price,
            margin=row.net_profit,
            sold_units=row.sold_units - row.returned_units,
        )
        for row in report.rows
    ]


def window_ad_cash(ad_days: list[AdSpendDay]) -> Decimal | None:
    """Return what the window's advertising actually cost the seller.

    ``None`` when the advertising statistics have nothing for the window, which
    is not the same as a window that ran no ads: the first must not lower a cost.
    """
    if not ad_days:
        return None
    spend = sum((day.spend for day in ad_days), _ZERO)
    bonus = sum((day.bonus for day in ad_days), _ZERO)
    return spend - min(bonus, spend)
