"""The «Сводка» arithmetic — pure functions over already-loaded figures.

Nothing here touches a session. Every input is a DTO the finreports and
monitoring contracts already produced, which is what lets the whole surface be
tested against hand-written numbers instead of against a database.

Two rules run through all of it:

* **No cost price, no margin.** A window where any settled SKU has no cost on
  file reports ``margin = None``, not a margin computed against free goods. The
  per-SKU report is softer — it sums the costed rows and counts the rest — which
  is right for a table a seller reads row by row and wrong for one headline
  number, where the omission is invisible.
* **Advertising is re-dated, never re-invented.** WB withholds advertising as one
  invoice per week, so a day-grained margin built on the settlement alone would
  crater on invoice days and sit too high on every other. The invoice is added
  back and the day's real burn — net of what WB's bonus pool funded — is taken
  off instead. Period sums are unchanged by the swap; only the dating is.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from src.modules.finreports.contract import PnlSkuReportResponse, PnlSkuRow, PnlStatement
from src.modules.monitoring.contract import AdSpendDay, OrderDay
from src.modules.summary.schemas import (
    CategoryGrouping,
    RevenueBase,
    SummaryCategory,
    SummaryDay,
    SummaryKpi,
)

_ZERO = Decimal(0)

#: Label for a SKU whose catalogue identity WB never filled in. Empty subject and
#: brand strings are common on older settlement rows, and a bar captioned with an
#: empty string reads as a rendering bug.
_UNNAMED = "(не указан)"


def _pct(part: Decimal, whole: Decimal) -> Decimal | None:
    """Return ``part`` as a percentage of ``whole``, or ``None`` when undefined."""
    return None if whole == _ZERO else (part / whole * 100).quantize(Decimal("0.01"))


def revenue_of(row: PnlSkuRow, base: RevenueBase) -> Decimal:
    """Take a row's revenue at the requested price base."""
    return row.revenue_paid if base is RevenueBase.PAID else row.revenue_seller_price


def _statement_revenue(bucket: PnlStatement, base: RevenueBase) -> Decimal:
    """Take a day bucket's revenue at the requested price base."""
    return bucket.revenue_paid if base is RevenueBase.PAID else bucket.revenue_seller_price


def uncosted_skus(report: PnlSkuReportResponse) -> int:
    """Count SKUs that moved units in the window with no cost price on file.

    Units, not revenue: a SKU whose only rows are a refund still consumed a cost
    that is not known, and it is exactly the kind of row that would quietly drag
    a margin up.
    """
    return sum(
        1
        for row in report.rows
        if row.cost_price is None and (row.sold_units - row.returned_units) != 0
    )


def build_kpi(
    *,
    report: PnlSkuReportResponse,
    base: RevenueBase,
    orders: int | None,
    buyouts: int | None,
    ad_cash: Decimal | None,
    settled_advertising: Decimal,
) -> SummaryKpi:
    """Assemble the headline cards from the reconciled window totals.

    Args:
        report: The per-SKU P&L for the window — its ``totals`` row is the full
            reconciled window, account-level money included.
        base: Which price revenue is taken at.
        orders: Funnel orders for the window; ``None`` without coverage.
        buyouts: WB's own buyout counter for the window; ``None`` without it.
        ad_cash: Advertising the seller actually paid for, bonuses removed;
            ``None`` without advertising coverage.
        settled_advertising: The «WB Продвижение» invoices the window's
            settlement withheld. Added back before ``ad_cash`` is taken off —
            see below.

    Returns:
        The cards, with every unknown left as ``None``.
    """
    totals = report.totals
    revenue = revenue_of(totals, base)
    net_units = totals.sold_units - totals.returned_units
    missing = uncosted_skus(report)

    # Advertising is subtracted exactly ONCE, and the invoice is not the copy
    # that survives. «К перечислению» is already net of WB's weekly invoice —
    # it sits inside «Удержания» — so taking `ad_cash` off it as well charges
    # the same advertising twice. Measured on a live кабинет: 3 161 239 against
    # a true 4 134 120 over one 54-day window, the gap being the 1 993 395 of
    # invoices to the сом.
    #
    # The invoice goes back and the real burn comes off, which is the same swap
    # `build_days` makes — and it is what keeps Σ days equal to this card.
    margin = (
        None
        if missing
        else totals.payout_net + settled_advertising - (totals.cogs or _ZERO) - (ad_cash or _ZERO)
    )

    return SummaryKpi(
        revenue=revenue,
        margin=margin,
        margin_pct=None if margin is None else _pct(margin, revenue),
        sold_units=net_units,
        orders=orders,
        buyout_pct=None if not orders else _pct(Decimal(net_units), Decimal(orders)),
        buyout_counted_pct=(
            None if not orders or buyouts is None else _pct(Decimal(buyouts), Decimal(orders))
        ),
        average_cheque=(
            None if net_units == 0 else (revenue / net_units).quantize(Decimal("0.01"))
        ),
        uncosted_skus=missing,
    )


def build_days(
    *,
    buckets: list[PnlStatement],
    order_days: list[OrderDay],
    ad_days: list[AdSpendDay],
    base: RevenueBase,
    costed: bool,
) -> list[SummaryDay]:
    """Assemble the daily series the three charts read.

    The margin of a day is the settlement's own margin with the advertising
    swapped: WB's weekly invoice — which the settlement charged to whichever day
    it closed on — is added back, and that day's actual burn is taken off. See
    the module docstring for why.

    The bonus is spread across the window in proportion to each day's spend
    rather than taken per day. WB writes bonuses off in batches, so a day's own
    ledger rows routinely exceed that day's impressions; apportioning over the
    window keeps every day non-negative AND keeps the series summing to the
    window's advertising cost, which a per-day clamp would not.

    Args:
        buckets: The P&L statement cut by settlement date.
        order_days: Funnel days; days it omits are days without coverage.
        ad_days: Advertising days, raw spend and raw bonus.
        base: Which price revenue is taken at.
        costed: Whether every settled SKU in the window has a cost price. When
            it does not, no day gets a margin — the same rule as the headline.

    Returns:
        One entry per day the settlement covers, ascending.
    """
    orders_by_day = {day.stat_date: day.orders for day in order_days}

    total_spend = sum((day.spend for day in ad_days), _ZERO)
    total_bonus = sum((day.bonus for day in ad_days), _ZERO)
    # Clamped once, over the window: a ledger row dated just inside a window
    # whose impressions fell just outside it must not make advertising negative.
    applied_bonus = min(total_bonus, total_spend)
    cash_by_day = {
        day.stat_date: (
            day.spend - (applied_bonus * day.spend / total_spend if total_spend else _ZERO)
        ).quantize(Decimal("0.01"))
        for day in ad_days
    }

    days: list[SummaryDay] = []
    for bucket in buckets:
        day = bucket.date_from
        if day is None:
            continue
        ad_cash = cash_by_day.get(day)
        margin = None
        if costed:
            # bucket.advertising is the «WB Продвижение» invoice the settlement
            # charged on this date; bucket.margin_profit has already subtracted
            # it inside «Удержания».
            margin = bucket.margin_profit + bucket.advertising - (ad_cash or _ZERO)
        days.append(
            SummaryDay(
                day=day,
                revenue=_statement_revenue(bucket, base),
                margin=margin,
                orders=orders_by_day.get(day),
                ad_spend=ad_cash,
            )
        )
    days.sort(key=lambda entry: entry.day)
    return days


@dataclass
class _Bucket:
    """One category bar under construction."""

    label: str
    revenue: Decimal = field(default=_ZERO)
    margin: Decimal = field(default=_ZERO)
    #: False as soon as one member SKU has no cost price — the bar then reports
    #: no margin at all rather than the margin of its costed half.
    costed: bool = True
    units: int = 0
    skus: int = 0


def _bucket_key(row: PnlSkuRow, grouping: CategoryGrouping) -> tuple[str, str]:
    """Return the ``(key, label)`` a row falls under for the category cut."""
    if grouping is CategoryGrouping.SUBJECT:
        return (row.subject_name or _UNNAMED, row.subject_name or _UNNAMED)
    if grouping is CategoryGrouping.BRAND:
        return (row.brand_name or _UNNAMED, row.brand_name or _UNNAMED)
    return (str(row.nm_id), row.sa_name)


def build_categories(
    *, report: PnlSkuReportResponse, base: RevenueBase, grouping: CategoryGrouping
) -> list[SummaryCategory]:
    """Rank who produced the window's revenue and margin.

    Account-level money is NOT spread across the bars. It has no SKU, no subject
    and no brand, so every way of dividing it would be an invention; the window's
    own advertising and penalties reach their SKUs from the sources that do carry
    one. What is left over stays outside this block and inside the headline.

    A bar's margin is ``None`` as soon as one of its SKUs has no cost price —
    the same rule as everywhere else, applied at the bar's own grain.

    Args:
        report: The per-SKU P&L for the window.
        base: Which price revenue is taken at.
        grouping: SKU, subject or brand.

    Returns:
        Bars sorted by revenue, largest first.
    """
    revenue_total = sum((revenue_of(row, base) for row in report.rows), _ZERO)
    margin_total = sum((row.net_profit for row in report.rows if row.net_profit is not None), _ZERO)

    grouped: dict[str, _Bucket] = {}
    for row in report.rows:
        key, label = _bucket_key(row, grouping)
        bucket = grouped.setdefault(key, _Bucket(label=label))
        bucket.revenue += revenue_of(row, base)
        bucket.units += row.sold_units - row.returned_units
        bucket.skus += 1
        if row.net_profit is None:
            bucket.costed = False
        else:
            bucket.margin += row.net_profit

    categories = []
    for key, bucket in grouped.items():
        margin = bucket.margin if bucket.costed else None
        categories.append(
            SummaryCategory(
                key=key,
                label=bucket.label,
                revenue=bucket.revenue,
                revenue_share_pct=_pct(bucket.revenue, revenue_total) or _ZERO,
                margin=margin,
                margin_share_pct=None if margin is None else _pct(margin, margin_total),
                margin_pct=None if margin is None else _pct(margin, bucket.revenue),
                sold_units=bucket.units,
                sku_count=bucket.skus,
            )
        )
    categories.sort(key=lambda entry: entry.revenue, reverse=True)
    return categories


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


def window_span(days: list[date]) -> tuple[date | None, date | None]:
    """Return ``(first, last)`` of a day list, or ``(None, None)`` when empty."""
    return (min(days), max(days)) if days else (None, None)
