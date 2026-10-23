"""Composition of one article's per-size P&L rows.

Pure, like :mod:`.sku_report`: size aggregates in, size rows out. The
withholding formula is deliberately the SAME one
:func:`~.sku_report.build_sku_row` applies, so the column that matters — the
payout — sums over the sizes back to the article's own figure rather
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
NO_SIZE_LABEL = "no size"


def _pct(part: Decimal, whole: Decimal) -> Decimal | None:
    """Return ``part`` as a percentage of ``whole``, or ``None`` if undefined."""
    if whole == _ZERO:
        return None
    return (part / whole * _HUNDRED).quantize(_CENTS)


def _build_row(size: SizeSettlement) -> PnlSizeRow:
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

    buyout = _pct(Decimal(size.sold_units), Decimal(size.delivered_units))
    return PnlSizeRow(
        ts_name=size.ts_name or NO_SIZE_LABEL,
        sold_units=size.sold_units,
        returned_units=size.returned_units,
        delivered_units=size.delivered_units,
        buyout_pct=buyout,
        revenue_paid=revenue_paid,
        revenue_seller_price=revenue_seller,
        average_price=((revenue_seller / net_units).quantize(_CENTS) if net_units else None),
        logistics_total=logistics,
        logistics_pct=_pct(logistics, revenue_seller),
        logistics_per_delivery=(
            (logistics / size.delivered_units).quantize(_CENTS) if size.delivered_units else None
        ),
        penalties_total=size.penalties,
        payout_net=payout_net,
    )


def build_size_rows(sizes: list[SizeSettlement]) -> list[PnlSizeRow]:
    """Compose the size rows.

    There is no totals row: the sizes sum to the article's own row exactly
    (``test_sizes_match_the_article``), and a second "Total" under it only
    repeated that row — except for the buyout, which is measured differently
    here and so made the two look as if they disagreed.

    Args:
        sizes: One entry per ``ts_name``, as the repository returns them.

    Returns:
        The rows, in WB's size-label order.
    """
    return [_build_row(size) for size in sizes]
