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

from collections.abc import Callable
from decimal import Decimal

from src.modules.finreports.repos import SettlementAggregate
from src.modules.finreports.schemas.sku_report import PnlDashboard, PnlSkuRow, SkuPenalty

_ZERO = Decimal(0)
_HUNDRED = Decimal(100)
_CENTS = Decimal("0.01")

#: Grouping label of the row that carries WB's account-level (nm_id = 0) money.
UNALLOCATED_NAME = "Без привязки к артикулу (счёт целиком)"


def _pct(part: Decimal, whole: Decimal) -> Decimal | None:
    """Return ``part`` as a percentage of ``whole``, or ``None`` if undefined."""
    if whole == _ZERO:
        return None
    return (part / whole * _HUNDRED).quantize(Decimal("0.01"))


def _logistics(aggregate: SettlementAggregate) -> Decimal:
    """Every logistics leg the SKU's own rows carry, forward, return and unlegged."""
    return aggregate.logistics_forward + aggregate.logistics_return + aggregate.logistics_unlegged


def _payout_goods(aggregate: SettlementAggregate) -> Decimal:
    """What WB owes for the goods themselves, before anything is withheld."""
    return aggregate.payout_sales - aggregate.payout_returns + aggregate.payout_other


def sku_payout_net(aggregate: SettlementAggregate) -> Decimal:
    """The payout for a SKU's own rows, net of what WB withheld on them.

    The same net-of-withholdings formula the window statement uses, applied to
    this SKU's own rows. For a real SKU the storage/acceptance/deduction terms
    are almost always zero (WB bills them at account level); for the nm_id = 0
    bucket they are the whole point. Keeping ONE formula — here, and called by
    every cut that needs it — is what makes Σ payout_net over rows +
    unallocated equal the window's «Итого к оплате», and what keeps a per-day
    cut of the same SKU from drifting off its per-window row.
    """
    withheld = (
        _logistics(aggregate)
        + aggregate.storage
        + aggregate.acceptance
        + aggregate.penalties
        + aggregate.deductions
        + aggregate.rebill_logistic_cost
        - aggregate.additional_payments
    )
    return _payout_goods(aggregate) - withheld


def build_sku_row(
    aggregate: SettlementAggregate,
    *,
    nm_id: int,
    sa_name: str,
    orders: int | None,
    buyouts: tuple[int, int] | None,
    cost_price: Decimal | None,
    advertising: Decimal | None,
    ad_bonus: Decimal | None,
    penalties: list[SkuPenalty],
    subject_name: str = "",
    brand_name: str = "",
    is_excluded: bool = False,
    photo_url: str | None = None,
) -> PnlSkuRow:
    """Compose one SKU's row from its aggregate and the cross-module figures.

    Args:
        aggregate: The summed settlement inputs for this SKU's rows.
        nm_id: The SKU (0 for the unallocated bucket).
        sa_name: Display article.
        orders: Ordered units from the funnel, ``None`` without coverage.
        buyouts: ``(buyouts, decided deliveries)`` from the funnel by order
            date, ``None`` without coverage.
        cost_price: The seller's per-unit cost, ``None`` when not on file.
        advertising: Promotion-API spend GROSS of funding source, ``None``
            without coverage.
        ad_bonus: The share of ``advertising`` WB funded from its bonus pool,
            as a positive magnitude. ``None`` when the write-off ledger has
            no coverage for the window — which must not be read as zero.
        penalties: This SKU's penalty categories.
        subject_name: WB's Тип предмета (blank on the totals/bucket rows).
        brand_name: WB's Бренд (blank on the totals/bucket rows).
        is_excluded: Whether the seller marked the SKU «Не включать в общий счёт».
        photo_url: The card's main image on WB's CDN, ``None`` when the
            monitoring catalogue holds none — and on the totals and
            account-level rows, which are not a product.

    Returns:
        The row, with every derived figure computed.
    """
    revenue_paid = aggregate.sales_gross - aggregate.returns_gross
    revenue_seller = aggregate.sales_before_spp - aggregate.returns_before_spp
    payout_goods = _payout_goods(aggregate)
    logistics = _logistics(aggregate)
    payout_net = sku_payout_net(aggregate)

    net_units = aggregate.sold_units - aggregate.returned_units
    cogs = cost_price * net_units if cost_price is not None else None
    # What the advertising actually cost: WB's bonuses bought impressions that
    # appear in `advertising` but never left the seller's account, and they
    # never reach the settlement either (a bonus write-off has no invoice). The
    # bonus is clamped at the spend it belongs to — a ledger row dated just
    # inside the window whose impressions fell just outside it must not turn an
    # advertising cost negative.
    #
    # The clamp is applied ONCE, here, and the clamped figure is what the row
    # reports: «Реклама» minus «Бонусы» has to equal the cash cost on screen,
    # which it cannot if the printed bonus is the unclamped one.
    bonus_applied = None if advertising is None or ad_bonus is None else min(ad_bonus, advertising)
    advertising_cash = None if advertising is None else advertising - (bonus_applied or _ZERO)
    net_profit = payout_net - cogs - (advertising_cash or _ZERO) if cogs is not None else None

    return PnlSkuRow(
        nm_id=nm_id,
        sa_name=sa_name,
        photo_url=photo_url,
        subject_name=subject_name,
        brand_name=brand_name,
        is_excluded=is_excluded,
        orders_units=orders,
        sold_units=aggregate.sold_units,
        returned_units=aggregate.returned_units,
        return_rate_pct=_pct(Decimal(aggregate.returned_units), Decimal(aggregate.sold_units)),
        buyout_units=None if buyouts is None else buyouts[0],
        decided_units=None if buyouts is None else buyouts[1],
        buyout_pct=None if buyouts is None else _pct(Decimal(buyouts[0]), Decimal(buyouts[1])),
        sales_amount=aggregate.sales_gross,
        returns_amount=aggregate.returns_gross,
        revenue_paid=revenue_paid,
        revenue_seller_price=revenue_seller,
        spp_amount=revenue_seller - revenue_paid,
        spp_pct=_pct(revenue_seller - revenue_paid, revenue_seller),
        average_cheque=((revenue_paid / net_units).quantize(_CENTS) if net_units else None),
        logistics_forward=aggregate.logistics_forward,
        logistics_return=aggregate.logistics_return,
        logistics_total=logistics,
        logistics_pct=_pct(logistics, revenue_seller),
        penalties_total=aggregate.penalties,
        penalties=penalties,
        cost_price=cost_price,
        cogs=cogs,
        advertising=advertising,
        advertising_pct=_pct(advertising, revenue_seller) if advertising is not None else None,
        ad_bonus=bonus_applied,
        advertising_cash=advertising_cash,
        payout_for_goods=payout_goods,
        payout_net=payout_net,
        net_profit=net_profit,
        net_profit_pct=_pct(net_profit, revenue_seller) if net_profit is not None else None,
        # Profit-based, per the seller's choice: ROI against cost. None the
        # moment the cost is missing or zero — net_profit is already None
        # without a cost, so ROI follows.
        roi_pct=(_pct(net_profit, cogs) if net_profit is not None and cogs else None),
    )


def build_sku_report(
    *,
    sku_aggregates: list[SettlementAggregate],
    total_aggregate: SettlementAggregate,
    costs: dict[int, Decimal],
    orders: dict[int, int] | None,
    buyouts: dict[int, tuple[int, int]] | None,
    ad_spend: dict[int, Decimal] | None,
    ad_bonus: dict[int, Decimal] | None,
    penalties: list[tuple[int, str, Decimal]],
    excluded: set[int] | None = None,
    photos: dict[int, str] | None = None,
) -> tuple[list[PnlSkuRow], PnlSkuRow | None, PnlSkuRow]:
    """Assemble the report's rows, its unallocated bucket and its totals row.

    Args:
        sku_aggregates: Per-SKU aggregates (``key`` = ``nm_id``, 0 included).
        total_aggregate: The whole-window aggregate, for the totals row.
        costs: Seller cost per ``nm_id`` (settlement currency only).
        orders: Funnel orders per ``nm_id``; ``None`` = no coverage at all.
        buyouts: ``(buyouts, decided)`` per ``nm_id`` from the funnel;
            ``None`` = no coverage at all.
        ad_spend: Promotion-API spend per ``nm_id``; ``None`` = no coverage.
        ad_bonus: WB-funded share of that spend per ``nm_id``; ``None`` = the
            write-off ledger does not cover this window.
        penalties: ``(nm_id, reason, amount)`` categories for the window.
        excluded: ``nm_id``s marked «Не включать в общий счёт». Only flags the
            rows; ``totals`` stays the full reconciled window regardless (the
            exclusion-aware figures live in :func:`build_dashboard`).
        photos: Card thumbnails per ``nm_id``, from the monitoring catalogue.
            Absent ids simply get no thumbnail: a SKU can be in a settlement
            and not yet in the catalogue (a fresh workspace whose first harvest
            has not run), and that must cost a picture, not a row.

    Returns:
        ``(rows sorted by net revenue, unallocated row or None, totals row)``.
    """
    excluded = excluded or set()
    photos = photos or {}
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
            buyouts=None if buyouts is None else buyouts.get(nm_id, (0, 0)),
            cost_price=costs.get(nm_id),
            advertising=None if ad_spend is None else ad_spend.get(nm_id, _ZERO),
            ad_bonus=None if ad_bonus is None else ad_bonus.get(nm_id, _ZERO),
            penalties=penalty_map.get(nm_id, []),
            subject_name=aggregate.subject_name if nm_id else "",
            brand_name=aggregate.brand_name if nm_id else "",
            is_excluded=nm_id in excluded,
            photo_url=photos.get(nm_id) if nm_id else None,
        )
        if nm_id == 0:
            row.sa_name = UNALLOCATED_NAME
            # Orders/costs/ads are per-product concepts; the account bucket
            # carries settlement money only.
            row.orders_units = None
            row.buyout_units = None
            row.decided_units = None
            row.buyout_pct = None
            row.advertising = None
            row.advertising_pct = None
            row.ad_bonus = None
            row.advertising_cash = None
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
        buyouts=(
            None
            if buyouts is None
            else (sum(b for b, _ in buyouts.values()), sum(d for _, d in buyouts.values()))
        ),
        cost_price=None,
        advertising=None if ad_spend is None else sum(ad_spend.values(), _ZERO),
        ad_bonus=None if ad_bonus is None else sum(ad_bonus.values(), _ZERO),
        penalties=_merged_reasons(penalties),
    )
    # The totals row's COGS is the sum of the costed rows, not price x units (no
    # single price exists across SKUs); profit follows from it.
    totals.cogs = sum((r.cogs for r in rows if r.cogs is not None), _ZERO)
    # WB charges advertising twice over, in two units that are the same money:
    # a weekly «Оказание услуг «WB Продвижение»» invoice, withheld inside «к
    # перечислению», and the burn the Promotion API dates to the days the ads
    # ran. A SKU row only ever sees the second — the invoice carries no nm_id —
    # so its spend, net of WB's bonuses, is that row's advertising charge.
    #
    # «Итого» is the invoice: what WB billed the кабинет is the total, by the
    # owner's decision of 2026-10-02 (the burn differs from it by when it is
    # dated — a week's invoice was 0.77..1.13 of that week's burn on «Демо»
    # in September, 0.96 over five weeks — and, before 20.08.2026, by the rate:
    # WB converted the rouble invoices at the document day's rate, the burn is
    # converted at each impression day's). The invoice is already inside «к
    # перечислению», so the profit is the payout less the goods, and nothing is
    # added back or taken off. «Реклама» on this row is the invoice plus WB's
    # bonuses — the gross the rows sum towards — so «Реклама» minus «Бонусы» is
    # still the cash on screen.
    invoice = total_aggregate.advertising
    totals.advertising_cash = invoice
    totals.advertising = invoice + (totals.ad_bonus or _ZERO)
    totals.advertising_pct = _pct(totals.advertising, totals.revenue_seller_price)
    totals.net_profit = totals.payout_net - totals.cogs
    totals.net_profit_pct = _pct(totals.net_profit, totals.revenue_seller_price)
    totals.roi_pct = _pct(totals.net_profit, totals.cogs) if totals.cogs else None
    _ = total_costed_units  # coverage is reported by the service's notes
    return rows, unallocated, totals


def build_dashboard(
    *,
    rows: list[PnlSkuRow],
    totals: PnlSkuRow,
    total_aggregate: SettlementAggregate,
) -> PnlDashboard:
    """Compose the five dashboard cards, dropping the marked SKUs.

    Computed as ``totals - sum(marked rows)`` rather than ``sum(included rows)`` on
    purpose: with nothing marked the dashboard then equals the full reconciled
    ``totals`` to the kopeck (so «Продажи» matches WB's page and «Перечисление»
    matches «Итого к оплате»), and each mark subtracts exactly that SKU's share —
    including its slice of «Перечисление», which ``totals`` carries together with
    the account-level bucket. «Прочие удержания» is account-level (no ``nm_id``),
    so it is read off the window aggregate and a mark never moves it.

    Args:
        rows: The real-SKU rows (each carrying ``is_excluded``).
        totals: The full reconciled window row from :func:`build_sku_report`.
        total_aggregate: The window aggregate, for the account-level deductions.

    Returns:
        The exclusion-aware KPIs the cards render.
    """
    marked = [r for r in rows if r.is_excluded]

    def _less(total: Decimal, pick: Callable[[PnlSkuRow], Decimal]) -> Decimal:
        return total - sum((pick(r) for r in marked), _ZERO)

    # «Продажи» at the seller's own price (revenue_seller_price = «Цена розничная
    # с учётом согласованной скидки», before СПП); «оплачено покупателями» is the
    # after-СПП amount, kept as the card's qualifier.
    sales = _less(totals.revenue_seller_price, lambda r: r.revenue_seller_price)
    paid = _less(totals.revenue_paid, lambda r: r.revenue_paid)
    logistics = _less(totals.logistics_total, lambda r: r.logistics_total)
    sold_units = totals.sold_units - sum(r.sold_units for r in marked)
    returned_units = totals.returned_units - sum(r.returned_units for r in marked)
    cogs = (totals.cogs or _ZERO) - sum((r.cogs or _ZERO) for r in marked)

    return PnlDashboard(
        sales=sales,
        paid=paid,
        sold_units=sold_units,
        returned_units=returned_units,
        return_rate_pct=_pct(Decimal(returned_units), Decimal(sold_units)),
        logistics=logistics,
        logistics_pct=_pct(logistics, sales),
        cogs=cogs,
        uncosted_count=sum(
            1 for r in rows if not r.is_excluded and r.cost_price is None and r.sold_units
        ),
        payout_net=_less(totals.payout_net, lambda r: r.payout_net),
        other_deductions=total_aggregate.deductions,
        advertising=total_aggregate.advertising,
        excluded_count=len(marked),
    )


def _merged_reasons(penalties: list[tuple[int, str, Decimal]]) -> list[SkuPenalty]:
    """Collapse the per-SKU penalty categories into window-level ones."""
    merged: dict[str, Decimal] = {}
    for _nm_id, reason, amount in penalties:
        merged[reason] = merged.get(reason, _ZERO) + amount
    ordered = sorted(merged.items(), key=lambda item: item[1], reverse=True)
    return [SkuPenalty(reason=reason, amount=amount) for reason, amount in ordered]
