"""The per-SKU P&L report — the «По артикулам» cut of the statement.

Composition only, like :mod:`.statement`: settlement aggregates, cost prices,
and the two cross-module mappings (orders, ad spend) in; one
:class:`~src.modules.finreports.schemas.sku_report.PnlSkuReportResponse` out.

The reconciliation rule this module exists to keep: **Σ rows + unallocated =
the window statement, exactly.** Per-SKU figures come only from that SKU's own
settlement rows; account-level money is never redistributed, because a
redistribution key (by revenue? by units?) is an editorial choice that turns a
verifiable report into a model. The reference workbook smears advertising over
SKUs this way and its «Чистая прибыль» column absorbs the arbitrariness; here
advertising per SKU is the Promotion API's own attribution instead, and the
invoice-vs-stats gap stays visible in the unallocated row.
"""

from __future__ import annotations

from decimal import Decimal

from src.modules.finreports.repos import SettlementAggregate
from src.modules.finreports.schemas.sku_report import PnlSkuRow, SkuPenalty

_ZERO = Decimal(0)
_HUNDRED = Decimal(100)

#: Grouping label of the row that carries WB's account-level (nm_id = 0) money.
UNALLOCATED_NAME = "Без привязки к артикулу (счёт целиком)"


def _pct(part: Decimal, whole: Decimal) -> Decimal | None:
    """Return ``part`` as a percentage of ``whole``, or ``None`` if undefined."""
    if whole == _ZERO:
        return None
    return (part / whole * _HUNDRED).quantize(Decimal("0.01"))


def build_sku_row(
    aggregate: SettlementAggregate,
    *,
    nm_id: int,
    sa_name: str,
    orders: int | None,
    cost_price: Decimal | None,
    advertising: Decimal | None,
    penalties: list[SkuPenalty],
) -> PnlSkuRow:
    """Compose one SKU's row from its aggregate and the cross-module figures.

    Args:
        aggregate: The summed settlement inputs for this SKU's rows.
        nm_id: The SKU (0 for the unallocated bucket).
        sa_name: Display article.
        orders: Ordered units from the funnel, ``None`` without coverage.
        cost_price: The seller's per-unit cost, ``None`` when not on file.
        advertising: Promotion-API spend, ``None`` without coverage.
        penalties: This SKU's penalty categories.

    Returns:
        The row, with every derived figure computed.
    """
    revenue_paid = aggregate.sales_gross - aggregate.returns_gross
    revenue_seller = aggregate.sales_before_spp - aggregate.returns_before_spp
    payout_goods = aggregate.payout_sales - aggregate.payout_returns + aggregate.payout_other
    logistics = (
        aggregate.logistics_forward + aggregate.logistics_return + aggregate.logistics_unlegged
    )
    # The same net-of-withholdings formula the window statement uses, applied to
    # this SKU's own rows. For a real SKU the storage/acceptance/deduction terms
    # are almost always zero (WB bills them at account level); for the nm_id = 0
    # bucket they are the whole point. Keeping one formula is what makes
    # Σ payout_net over rows + unallocated equal the window's «Итого к оплате».
    withheld = (
        logistics
        + aggregate.storage
        + aggregate.acceptance
        + aggregate.penalties
        + aggregate.deductions
        + aggregate.rebill_logistic_cost
        - aggregate.additional_payments
    )
    payout_net = payout_goods - withheld

    net_units = aggregate.sold_units - aggregate.returned_units
    cogs = cost_price * net_units if cost_price is not None else None
    net_profit = payout_net - cogs - (advertising or _ZERO) if cogs is not None else None

    return PnlSkuRow(
        nm_id=nm_id,
        sa_name=sa_name,
        orders_units=orders,
        sold_units=aggregate.sold_units,
        returned_units=aggregate.returned_units,
        return_rate_pct=_pct(Decimal(aggregate.returned_units), Decimal(aggregate.sold_units)),
        sales_amount=aggregate.sales_gross,
        returns_amount=aggregate.returns_gross,
        revenue_paid=revenue_paid,
        revenue_seller_price=revenue_seller,
        spp_amount=revenue_seller - revenue_paid,
        spp_pct=_pct(revenue_seller - revenue_paid, revenue_seller),
        logistics_forward=aggregate.logistics_forward,
        logistics_return=aggregate.logistics_return,
        logistics_total=logistics,
        logistics_pct=_pct(logistics, revenue_paid),
        penalties_total=aggregate.penalties,
        penalties=penalties,
        cost_price=cost_price,
        cogs=cogs,
        advertising=advertising,
        advertising_pct=_pct(advertising, revenue_paid) if advertising is not None else None,
        payout_for_goods=payout_goods,
        payout_net=payout_net,
        net_profit=net_profit,
        net_profit_pct=_pct(net_profit, revenue_paid) if net_profit is not None else None,
    )


def build_sku_report(
    *,
    sku_aggregates: list[SettlementAggregate],
    total_aggregate: SettlementAggregate,
    costs: dict[int, Decimal],
    orders: dict[int, int] | None,
    ad_spend: dict[int, Decimal] | None,
    penalties: list[tuple[int, str, Decimal]],
) -> tuple[list[PnlSkuRow], PnlSkuRow | None, PnlSkuRow]:
    """Assemble the report's rows, its unallocated bucket and its totals row.

    Args:
        sku_aggregates: Per-SKU aggregates (``key`` = ``nm_id``, 0 included).
        total_aggregate: The whole-window aggregate, for the totals row.
        costs: Seller cost per ``nm_id`` (settlement currency only).
        orders: Funnel orders per ``nm_id``; ``None`` = no coverage at all.
        ad_spend: Promotion-API spend per ``nm_id``; ``None`` = no coverage.
        penalties: ``(nm_id, reason, amount)`` categories for the window.

    Returns:
        ``(rows sorted by net revenue, unallocated row or None, totals row)``.
    """
    penalty_map: dict[int, list[SkuPenalty]] = {}
    for nm_id, reason, amount in penalties:
        penalty_map.setdefault(nm_id, []).append(SkuPenalty(reason=reason, amount=amount))

    rows: list[PnlSkuRow] = []
    unallocated: PnlSkuRow | None = None
    for aggregate in sku_aggregates:
        nm_id = int(str(aggregate.key))
        row = build_sku_row(
            aggregate,
            nm_id=nm_id,
            sa_name=aggregate.label or (UNALLOCATED_NAME if nm_id == 0 else f"nm {nm_id}"),
            orders=None if orders is None else orders.get(nm_id, 0),
            cost_price=costs.get(nm_id),
            advertising=None if ad_spend is None else ad_spend.get(nm_id, _ZERO),
            penalties=penalty_map.get(nm_id, []),
        )
        if nm_id == 0:
            row.sa_name = UNALLOCATED_NAME
            # Orders/costs/ads are per-product concepts; the account bucket
            # carries settlement money only.
            row.orders_units = None
            row.advertising = None
            row.advertising_pct = None
            unallocated = row
        else:
            rows.append(row)
    rows.sort(key=lambda r: r.revenue_paid, reverse=True)

    total_costed_units = sum(
        (r.sold_units - r.returned_units) for r in rows if r.cost_price is not None
    )
    totals = build_sku_row(
        total_aggregate,
        nm_id=0,
        sa_name="Итого",
        orders=None if orders is None else sum(orders.values()),
        cost_price=None,
        advertising=None if ad_spend is None else sum(ad_spend.values(), _ZERO),
        penalties=_merged_reasons(penalties),
    )
    # The totals row's COGS is the sum of the costed rows, not price x units (no
    # single price exists across SKUs); profit follows from it.
    totals.cogs = sum((r.cogs for r in rows if r.cogs is not None), _ZERO)
    totals.net_profit = totals.payout_net - totals.cogs - (totals.advertising or _ZERO)
    totals.net_profit_pct = _pct(totals.net_profit, totals.revenue_paid)
    _ = total_costed_units  # coverage is reported by the service's notes
    return rows, unallocated, totals


def _merged_reasons(penalties: list[tuple[int, str, Decimal]]) -> list[SkuPenalty]:
    """Collapse the per-SKU penalty categories into window-level ones."""
    merged: dict[str, Decimal] = {}
    for _nm_id, reason, amount in penalties:
        merged[reason] = merged.get(reason, _ZERO) + amount
    ordered = sorted(merged.items(), key=lambda item: item[1], reverse=True)
    return [SkuPenalty(reason=reason, amount=amount) for reason, amount in ordered]
