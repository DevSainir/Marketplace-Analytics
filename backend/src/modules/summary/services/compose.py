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
* **Advertising is charged once, and the total is WB's invoice.** WB withholds
  it as one invoice per week, already inside «к перечислению», and the Promotion
  API reports the same spend dated to the days the ads ran. The cards charge
  the invoices — what WB billed is the total, the owner's decision of
  2026-10-02, the same as the P&L's «Итого». The daily margin lays those
  invoices over the days in proportion to each day's own burn, so a day neither
  craters on invoice day nor counts the charge twice, and the chart still sums
  to the card.
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
    buyout_decided: int | None,
    buyout_lagged: bool,
    settled_advertising: Decimal,
) -> SummaryKpi:
    """Assemble the headline cards from the reconciled window totals.

    Args:
        report: The per-SKU P&L for the window — its ``totals`` row is the full
            reconciled window, account-level money included.
        orders: Orders for the window; ``None`` without coverage.
        buyouts: Deliveries bought out over the cohort window.
        buyout_decided: Deliveries answered over the same window — the only
            denominator the buyouts may be divided by.
        buyout_lagged: Whether those two came from the standing window rather
            than from the chosen period.
        settled_advertising: The «WB Продвижение» invoices the window's
            settlement withheld — what the cards charge for advertising.

    Returns:
        The cards, with every unknown left as ``None``.
    """
    totals = report.totals
    missing = uncosted_skus(report)

    # Advertising is subtracted exactly ONCE, as WB's invoice: «к перечислению»
    # is already net of it, so the margin is the payout less the goods. Taking
    # the burn off as well charged it twice — 2 657 954.54 against a true
    # 4 313 444.72 on one live 54-day window.
    margin = None if missing else totals.payout_net - (totals.cogs or _ZERO)

    # Fines and withholdings, minus the advertising invoices inside them: the
    # ДРР card already reports advertising, and the same money under two labels
    # reads as two costs. The dashboard's figures are the account-level ones,
    # which no SKU exclusion can move.
    withheld = (
        totals.penalties_total + report.dashboard.other_deductions - report.dashboard.advertising
    )

    return SummaryKpi(
        revenue_paid=totals.revenue_paid,
        revenue_seller=totals.revenue_seller_price,
        margin=margin,
        sold_units=totals.sold_units - totals.returned_units,
        orders=orders,
        buyouts=buyouts,
        buyout_decided=buyout_decided,
        buyout_lagged=buyout_lagged,
        uncosted_skus=missing,
        penalties=withheld,
        ad_spend=settled_advertising,
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
    orders_by_day = {day.stat_date: day for day in order_days}

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
    invoiced = _invoices_by_day(settled, cash_by_day)

    days: list[SummaryDay] = []
    # Every day ANY feed covers, not only the settled ones. The window can
    # legitimately run past the last settlement — WB calculates weekly and
    # serves late, while the funnel and the promotion statistics land daily —
    # and those days used to vanish from all three charts rather than showing
    # the orders and the spend we do have.
    for day in sorted(settled.keys() | orders_by_day.keys() | ad_by_day.keys()):
        bucket = settled.get(day)
        funnel = orders_by_day.get(day)
        ad_cash = cash_by_day.get(day)
        margin = None
        if costed and bucket is not None:
            # bucket.advertising is the «WB Продвижение» invoice the settlement
            # charged on this date; bucket.margin_profit has already subtracted
            # it inside «Удержания». It goes back, and the day's share of the
            # window's invoices comes off instead.
            margin = bucket.margin_profit + bucket.advertising - invoiced.get(day, _ZERO)
        days.append(
            SummaryDay(
                day=day,
                # None, never zero, on a day WB has not calculated: the line
                # stops instead of reporting a collapse in sales.
                revenue_paid=bucket.revenue_paid if bucket else None,
                revenue_seller=bucket.revenue_seller_price if bucket else None,
                margin=margin,
                orders=funnel.orders if funnel else None,
                orders_amount_seller=funnel.amount_seller if funnel else None,
                orders_amount_paid=funnel.amount_paid if funnel else None,
                sold_units=(bucket.sold_units - bucket.returned_units) if bucket else None,
                ad_spend=ad_cash,
            )
        )
    days.sort(key=lambda entry: entry.day)
    return days


def _invoices_by_day(
    settled: dict[date, PnlStatement], cash_by_day: dict[date, Decimal]
) -> dict[date, Decimal]:
    """Lay the window's invoices over its settled days in proportion to each day's burn.

    Σ is the invoices exactly — the last day takes the rounding — so the daily
    margins sum to the card. A window with invoices and no burn on its settled
    days leaves each invoice on the day WB charged it.
    """
    invoices = sum((bucket.advertising for bucket in settled.values()), _ZERO)
    burn = {day: cash_by_day.get(day, _ZERO) for day in sorted(settled)}
    total_burn = sum(burn.values(), _ZERO)
    if not total_burn:
        return {day: bucket.advertising for day, bucket in settled.items()}
    shares: dict[date, Decimal] = {}
    assigned = _ZERO
    days = list(burn)
    for position, day in enumerate(days):
        if position == len(days) - 1:
            shares[day] = invoices - assigned
        else:
            shares[day] = (invoices * burn[day] / total_burn).quantize(Decimal("0.01"))
            assigned += shares[day]
    return shares


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


def buyout_cohort(days: list[OrderDay], *, until: date) -> tuple[int | None, int | None]:
    """Sum the buyout cohort over the days that have answered, up to ``until``.

    WB's own definition of «Процент выкупа»: bought out over bought out plus
    refused. A day the cohort pass has never refreshed carries no refusals to
    add, so it is skipped rather than read as «none were refused» — that
    exclusion is what makes the matrix's figure match WB's, and the same reason
    applies here.

    Args:
        days: The window's days.
        until: Newest day that may contribute — the freshest cohorts are
            excluded by the caller's lag, because within them refusals land
            before buyouts do and the ratio reads far too low.

    Returns:
        ``(bought out, answered)``, or ``(None, None)`` when no day qualifies.
    """
    bought = 0
    answered = 0
    seen = False
    for day in days:
        if day.stat_date > until or day.decided is None or day.buyouts is None:
            continue
        seen = True
        bought += day.buyouts
        answered += day.decided
    return (bought, answered) if seen else (None, None)
