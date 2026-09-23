"""Composition of one article's per-size P&L rows.

Pure, like :mod:`.sku_report`: size aggregates and the article's cost price in,
:class:`~src.modules.finreports.schemas.size_report.PnlSizesResponse` out. The
withholding formula is deliberately the SAME one
:func:`~.sku_report.build_sku_row` applies, so the column that matters — «К
перечислению» — sums over the sizes back to the article's own figure rather
than merely looking similar.
"""

from __future__ import annotations

from decimal import Decimal

from src.modules.finreports.repos.pnl.sizes import SizeSettlement
from src.modules.finreports.schemas.size_report import PnlSizeRow

_ZERO = Decimal(0)
_HUNDRED = Decimal(100)
_CENTS = Decimal("0.01")

#: What an empty ``ts_name`` is called on screen. WB bills a few rows per
#: article without a size (a fine, a storage correction); they are a size row
#: of their own so the sizes still add up to the article.
NO_SIZE_LABEL = "без размера"


def _pct(part: Decimal, whole: Decimal) -> Decimal | None:
    """Return ``part`` as a percentage of ``whole``, or ``None`` if undefined."""
    if whole == _ZERO:
        return None
    return (part / whole * _HUNDRED).quantize(_CENTS)


def _build_row(
    size: SizeSettlement,
    *,
    cost_price: Decimal | None,
    article_buyout_pct: Decimal | None,
    label: str | None = None,
) -> PnlSizeRow:
    """Compose one size's row from its summed settlement columns."""
    revenue_paid = size.sales_gross - size.returns_gross
    revenue_seller = size.sales_before_spp - size.returns_before_spp
    logistics = size.logistics_forward + size.logistics_return + size.logistics_unlegged
    payout_goods = size.payout_sales - size.payout_returns + size.payout_other
    withheld = (
        logistics
        + size.storage
        + size.acceptance
        + size.penalties
        + size.deductions
        + size.rebill_logistic_cost
        - size.additional_payments
    )
    payout_net = payout_goods - withheld

    net_units = size.sold_units - size.returned_units
    cogs = cost_price * net_units if cost_price is not None else None
    margin = payout_net - cogs if cogs is not None else None

    buyout = _pct(Decimal(size.sold_units), Decimal(size.delivered_units))
    return PnlSizeRow(
        ts_name=label if label is not None else (size.ts_name or NO_SIZE_LABEL),
        sold_units=size.sold_units,
        returned_units=size.returned_units,
        delivered_units=size.delivered_units,
        buyout_pct=buyout,
        buyout_vs_article_pp=(
            (buyout - article_buyout_pct)
            if buyout is not None and article_buyout_pct is not None
            else None
        ),
        revenue_paid=revenue_paid,
        revenue_seller_price=revenue_seller,
        spp_pct=_pct(revenue_seller - revenue_paid, revenue_seller),
        average_cheque=((revenue_paid / net_units).quantize(_CENTS) if net_units else None),
        logistics_total=logistics,
        logistics_pct=_pct(logistics, revenue_paid),
        logistics_per_delivery=(
            (logistics / size.delivered_units).quantize(_CENTS) if size.delivered_units else None
        ),
        penalties_total=size.penalties,
        cogs=cogs,
        payout_net=payout_net,
        margin_before_ads=margin,
        margin_pct=_pct(margin, revenue_paid) if margin is not None else None,
    )


def _merge(sizes: list[SizeSettlement]) -> SizeSettlement:
    """Sum every size back into one aggregate — the article, re-derived."""

    def total(pick: str) -> Decimal:
        return sum((getattr(s, pick) for s in sizes), _ZERO)

    def count(pick: str) -> int:
        return sum(getattr(s, pick) for s in sizes)

    return SizeSettlement(
        ts_name="",
        sold_units=count("sold_units"),
        returned_units=count("returned_units"),
        delivered_units=count("delivered_units"),
        sales_gross=total("sales_gross"),
        returns_gross=total("returns_gross"),
        sales_before_spp=total("sales_before_spp"),
        returns_before_spp=total("returns_before_spp"),
        payout_sales=total("payout_sales"),
        payout_returns=total("payout_returns"),
        payout_other=total("payout_other"),
        logistics_forward=total("logistics_forward"),
        logistics_return=total("logistics_return"),
        logistics_unlegged=total("logistics_unlegged"),
        penalties=total("penalties"),
        storage=total("storage"),
        acceptance=total("acceptance"),
        deductions=total("deductions"),
        additional_payments=total("additional_payments"),
        rebill_logistic_cost=total("rebill_logistic_cost"),
        rows=count("rows"),
    )


def build_size_rows(
    sizes: list[SizeSettlement],
    *,
    cost_price: Decimal | None,
) -> tuple[list[PnlSizeRow], PnlSizeRow]:
    """Compose the size rows and the article-level row they add up to.

    The totals row is built from the SUMMED aggregate rather than by adding the
    composed rows: a ratio is not the sum of ratios, and «Выкуп» over the
    article is what every size's «К среднему» is measured against, so it has to
    exist before the rows do.

    Args:
        sizes: One entry per ``ts_name``, as the repository returns them.
        cost_price: The article's per-unit cost, ``None`` when not on file.

    Returns:
        ``(rows, totals)``, rows in WB's size-label order.
    """
    merged = _merge(sizes)
    totals = _build_row(merged, cost_price=cost_price, article_buyout_pct=None, label="Итого")
    rows = [
        _build_row(size, cost_price=cost_price, article_buyout_pct=totals.buyout_pct)
        for size in sizes
    ]
    return rows, totals
