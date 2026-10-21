"""The P&L's aggregate shape and the SQL expressions that fill it.

Split out of the repository so the two concerns can be read apart: this module
says *what* each statement input is, in terms of a settlement column and a row
filter, and :mod:`.repository` says how it is queried. The expression list is the
part worth reviewing carefully, and it should not sit at the bottom of a file of
query plumbing.

**Why the charge lines carry no operation filter.** Aggregating every money
column against every ``supplier_oper_name`` over the seller's whole settled
history shows each column is populated by exactly one family of operations and
is identically zero on all the others: ``delivery_rub`` only ever by
«Логистика»/«Коррекция логистики», ``storage_fee`` only by the three storage
operations, ``penalty`` only by «Штраф», and so on. Summing the column over all
rows is therefore both simpler *and* safer than filtering by operation — if WB
introduces an operation tomorrow that withholds storage, it lands in the storage
line instead of vanishing. Only the revenue/units/payout lines need the operation
split, because there the sign depends on it: refunds are served POSITIVE.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from enum import StrEnum
from typing import Any

from sqlalchemy import ColumnElement, and_, case, func, literal

from src.modules.finreports.constants import (
    ADVERTISING_DEDUCTION_MARKER,
    REFUND_DOC_TYPE,
    RETURN_OPERS,
    SALE_OPERS,
    SEPARATELY_BILLED_ACQUIRING,
)
from src.modules.finreports.models import LogisticsTransaction

_ZERO = Decimal(0)
_T = LogisticsTransaction

#: Any SQL expression these helpers may be handed. SQLAlchemy hands out several
#: unrelated types here — ``InstrumentedAttribute``, ``Function``, ``Case``,
#: ``BindParameter`` — and no public supertype unifies them for ``mypy --strict``,
#: so the alias documents the intent that the annotation cannot.
SqlExpr = Any


class PnlGrouping(StrEnum):
    """How the statement's rows are cut."""

    TOTAL = "total"
    #: One bucket per settlement date. The chart cut: WB dates every row it
    #: calculates, so a window of weekly reports still has a row on most days.
    DAY = "day"
    WEEK = "week"
    MONTH = "month"
    SKU = "sku"


@dataclass(frozen=True)
class SettlementAggregate:
    """Every P&L input for one grouping key, summed straight out of Postgres.

    Nothing here is derived — each field is a ``SUM`` over a filtered set of
    settlement rows — so every line of the rendered statement traces back to a
    column and a row filter.

    Attributes:
        key: Grouping value (``report_id``, month start, ``nm_id``, or ``None``).
        label: Human-readable name for the key (``sa_name`` for a SKU cut).
        date_from / date_to: Settlement dates actually observed in this group.
        currency: Settlement currency observed on the rows.
        subject_name / brand_name: WB's catalogue identity for the row («Тип
            предмета» / «Бренд»). Meaningful on the SKU cut only.
        sold_units / returned_units: Units on «Продажа» / «Возврат» rows.
        sales_gross / returns_gross: ``retail_amount`` — what buyers paid and
            what was refunded.
        sales_before_spp / returns_before_spp: ``retail_price_withdisc_rub`` on
            sale and refund rows — the price before WB's own SPP discount, so the
            gap WB co-funded is visible. Both are needed: netting refunds out of
            the pre-SPP revenue at their *post*-SPP amount mixes two bases and
            misstates the discount line by the refunds' own SPP.
        payout_sales / payout_returns / payout_other: ``ppvz_for_pay`` on sale
            rows, on refund rows, and on everything else. The third bucket is
            not padding: WB's standalone compensations (damage, defects, substituted
            goods, lost goods) populate ``ppvz_for_pay`` and no other
            money column, so filtering the payout to «Продажа» would drop them —
            33 433 KGS in a single quarter of this seller's history.
        wb_commission_reported / wb_commission_vat: ``ppvz_vw`` and
            ``ppvz_vw_nds`` as WB publishes them, over the SALE rows only. The
            statement does NOT add these two to get the commission line — it
            derives that as a residual of the authoritative 2-decimal figures, so
            the printed lines add up exactly. Their sum cross-checks that residual
            instead, and that check RUNS:
            ``test_the_residual_commission_matches_the_one_wb_published``. They
            agree exactly on the fixture and to 0.075 % over a full seller history.
            ``wb_commission_vat`` is additionally printed as the «в т.ч. НДС» of
            the commission line, so both must be summed over the same rows the
            residual is; see the expression's own comment for what widening
            them costs.
        wb_reward: ``ppvz_reward`` (the agent's reward), over the sale rows.
            Zero in 2026 but 47 396 KGS in one 2024 quarter — omitting it makes
            the payout fail to reconcile by exactly that amount.
        acquiring_withheld: ``acquiring_fee`` that WB actually deducted from the
            payout, net of refunds.
        acquiring_billed_apart: ``acquiring_fee`` labelled «Комиссия за
            организацию платежа с НДС», which WB bills separately instead of
            withholding — a memo figure, never a deduction from the payout.
        agency_vat: «НДС агента» (agent's VAT) — a memo figure, NOT part of the payout.
        logistics_forward / logistics_return / logistics_unlegged:
            ``delivery_rub`` split by which leg counter WB set on the row. The
            third bucket is «Коррекция логистики», which sets neither.
        storage / acceptance / penalties / deductions / additional_payments /
            rebill_logistic_cost: The withholdings, each from its own column.
        advertising: The «ВБ.Продвижение» share of ``deductions``. Aggregated
            here rather than read off the reason drill-down, because the
            drill-down is only built for the whole window — computing it there
            would leave every period row reporting zero advertising while the
            total reported millions.
        rows: How many settlement rows fed this aggregate.
        delivered_units: Σ ``delivery_amount`` — forward logistics legs, i.e.
            units carried to a buyer. The denominator of the per-SKU «Выкуп»,
            the same one the size cut uses (:mod:`.sizes`). Defaulted only so
            the period cuts, which never read it, need not spell it out.
    """

    key: object
    label: str
    date_from: date | None
    date_to: date | None
    currency: str
    #: Catalogue identity WB stamps on the row. Meaningful only on the SKU cut
    #: (all of a SKU's rows share them, so ``max`` = the value); on period/total
    #: cuts they are an arbitrary max and go unused.
    subject_name: str
    brand_name: str
    sold_units: int
    returned_units: int
    sales_gross: Decimal
    returns_gross: Decimal
    sales_before_spp: Decimal
    returns_before_spp: Decimal
    payout_sales: Decimal
    payout_returns: Decimal
    payout_other: Decimal
    wb_commission_reported: Decimal
    wb_commission_vat: Decimal
    wb_reward: Decimal
    acquiring_withheld: Decimal
    acquiring_billed_apart: Decimal
    agency_vat: Decimal
    logistics_forward: Decimal
    logistics_return: Decimal
    logistics_unlegged: Decimal
    storage: Decimal
    acceptance: Decimal
    penalties: Decimal
    deductions: Decimal
    additional_payments: Decimal
    rebill_logistic_cost: Decimal
    advertising: Decimal
    rows: int
    delivered_units: int = 0


@dataclass(frozen=True)
class ReasonAmount:
    """One ``bonus_type_name`` bucket of a charge, for the drill-downs."""

    reason: str
    amount: Decimal
    rows: int


@dataclass(frozen=True)
class SkuUnits:
    """Units settled for one SKU — the cost-price editor's coverage list."""

    nm_id: int
    vendor_code: str
    sold_units: int
    returned_units: int


def _sum(expression: SqlExpr) -> ColumnElement[Any]:
    """Sum a money column, substituting 0 for an empty set."""
    return func.coalesce(func.sum(expression), _ZERO)


def _is_return() -> ColumnElement[bool]:
    """True on the rows WB serves positive but that must be subtracted."""
    return _T.supplier_oper_name.in_(list(RETURN_OPERS))


def _netted(column: SqlExpr) -> ColumnElement[Any]:
    """Sum a sale-side column with refunds subtracted.

    Refund rows carry the same columns as sales with the SAME positive sign, so
    netting has to be explicit. Every operation other than «Возврат» counts
    positively, which keeps WB's standalone compensations (they populate
    ``ppvz_for_pay`` and nothing else) inside the payout instead of dropping
    them because they are not literally «Продажа».
    """
    return _sum(case((_is_return(), -column), else_=column))


def _units(opers: Sequence[str]) -> ColumnElement[Any]:
    """Count units on the given operations only.

    Never a bare ``SUM(quantity)``: «Возмещение издержек» carries a constant
    ``quantity = 2`` on all 109 284 of its rows as filler, which would add
    206 937 phantom units to the seller's history.
    """
    return func.coalesce(
        func.sum(case((_T.supplier_oper_name.in_(list(opers)), _T.quantity), else_=0)), 0
    )


def _on(opers: Sequence[str], column: SqlExpr) -> ColumnElement[Any]:
    """Sum a column over the given operations only."""
    return _sum(case((_T.supplier_oper_name.in_(list(opers)), column), else_=_ZERO))


#: Aggregate expressions in :class:`SettlementAggregate` field order, after the
#: grouping key and label. Defined once so the total, period and SKU queries
#: cannot drift apart — three hand-written copies of this list is exactly how a
#: statement grows a total that disagrees with its own rows.
_AGGREGATES: tuple[SqlExpr, ...] = (
    func.min(_T.rr_dt),
    func.max(_T.rr_dt),
    # The MODAL currency, not max(): a workspace's settlements are effectively
    # single-currency (this seller: 436 742 KGS rows), but a couple of stray rows
    # in another currency exist, and max() is lexical — max("KGS","RUB") = "RUB",
    # which would mislabel the whole statement AND make every KGS cost price
    # unmatchable (costs are dropped when their currency differs, PNL.md §13).
    func.coalesce(func.mode().within_group(_T.currency_name).filter(_T.currency_name != ""), ""),
    _units(SALE_OPERS),
    _units(RETURN_OPERS),
    _on(SALE_OPERS, _T.retail_amount),
    _on(RETURN_OPERS, _T.retail_amount),
    _on(SALE_OPERS, _T.retail_price_withdisc_rub),
    _on(RETURN_OPERS, _T.retail_price_withdisc_rub),
    _on(SALE_OPERS, _T.ppvz_for_pay),
    _on(RETURN_OPERS, _T.ppvz_for_pay),
    # Everything that is neither a sale nor a refund but still pays out: WB's
    # compensations, and «Корректировка эквайринга», which refunds over-charged
    # acquiring as +ppvz_for_pay against a -acquiring_fee on the same row.
    _sum(
        case(
            (_T.supplier_oper_name.in_(list(SALE_OPERS) + list(RETURN_OPERS)), _ZERO),
            (_T.doc_type_name == REFUND_DOC_TYPE, -_T.ppvz_for_pay),
            else_=_T.ppvz_for_pay,
        )
    ),
    # SALE-side only, NOT _netted. «Возмещение издержек по перевозке» reuses these
    # two columns to express the VAT split of its own charge — 86 566 rows
    # carrying ppvz_vw -377 874.68 and ppvz_vw_nds -47 746.32, which add to its
    # 461 652.31 of rebill_logistic_cost. It is not commission at all.
    #
    # These two decompose the commission line, and that line is a residual over
    # the sale-side payout, so they must be aggregated over the same rows. On the
    # all-operation basis the printed «в т.ч. НДС комиссии» came out at 629 187.13
    # against a true 744 682.24 over the whole history, and carried the WRONG SIGN
    # on 16 of the 133 weekly reports (e.g. report 922728393: -1 350.10 printed
    # under a +23 241.61 commission).
    _on(SALE_OPERS, _T.ppvz_vw) - _on(RETURN_OPERS, _T.ppvz_vw),
    _on(SALE_OPERS, _T.ppvz_vw_nds) - _on(RETURN_OPERS, _T.ppvz_vw_nds),
    _on(SALE_OPERS, _T.ppvz_reward) - _on(RETURN_OPERS, _T.ppvz_reward),
    _netted(
        case(
            (_T.payment_processing == SEPARATELY_BILLED_ACQUIRING, _ZERO),
            else_=_T.acquiring_fee,
        )
    ),
    _netted(
        case(
            (_T.payment_processing == SEPARATELY_BILLED_ACQUIRING, _T.acquiring_fee),
            else_=_ZERO,
        )
    ),
    _netted(_T.agency_vat),
    # Forward vs return leg. WB sets exactly one of the two counters on a
    # «Логистика» row — 152 745 forward and 94 358 return over the history, none
    # with both or neither — so those two partition cleanly.
    #
    # «Коррекция логистики» rows carry NEITHER counter, though (all 8 591 of them,
    # 30 180 KGS). They are money on the logistics line that belongs to no leg, so
    # they get their own bucket rather than being folded into "forward" to make the
    # sub-lines add up. Three buckets that sum to the line beats two that lie.
    _sum(
        case(
            (
                and_(_T.delivery_amount > 0, _T.return_amount == 0),
                _T.delivery_rub,
            ),
            else_=_ZERO,
        )
    ),
    _sum(case((_T.return_amount > 0, _T.delivery_rub), else_=_ZERO)),
    _sum(
        case(
            (
                and_(_T.delivery_amount == 0, _T.return_amount == 0),
                _T.delivery_rub,
            ),
            else_=_ZERO,
        )
    ),
    # No operation filter — see the module docstring.
    _sum(_T.storage_fee),
    _sum(_T.acceptance),
    _sum(_T.penalty),
    _sum(_T.deduction),
    _sum(_T.additional_payment),
    _sum(_T.rebill_logistic_cost),
    _sum(
        case(
            (
                _T.bonus_type_name.contains(ADVERTISING_DEDUCTION_MARKER),
                _T.deduction,
            ),
            else_=_ZERO,
        )
    ),
    # Catalogue identity, carried for the SKU cut's «Тип предмета» / «Бренд» columns.
    # ``max`` because a SKU's rows all share them; ignored on period/total cuts.
    func.max(_T.subject_name),
    func.max(_T.brand_name),
    func.count(),
    # Appended rather than slotted in with the other units, so the positional
    # readers below keep their indices. Summed over every row, like the size
    # cut: only «Логистика» rows set it, so Σ sizes = the article, exactly.
    func.coalesce(func.sum(_T.delivery_amount), 0),
)


#: The same expressions, reordered for the rollup table's column order and
#: without the two ``rr_dt`` bounds — a rollup row IS one day, so its own key
#: carries them.
#:
#: SLICED from :data:`_AGGREGATES` rather than written out again, which is what
#: makes drift between the two impossible: a column added to the aggregate is a
#: column the rollup stores, or this slice stops lining up and every test that
#: compares the two paths fails at once.
_GROUP_EXPRESSIONS: tuple[SqlExpr, ...] = (
    _AGGREGATES[2],  # currency (modal)
    _AGGREGATES[28],  # subject_name
    _AGGREGATES[29],  # brand_name
    *_AGGREGATES[3:28],  # every summed figure, in order
    _AGGREGATES[31],  # delivered_units
    _AGGREGATES[30],  # rows
)


def aggregate_from_rollup(
    *, key: object, label: str, bounds: tuple[date | None, date | None], values: Sequence[Any]
) -> SettlementAggregate:
    """Rebuild an aggregate from summed rollup columns.

    ``values`` arrives in :data:`_GROUP_EXPRESSIONS` order — currency, subject,
    brand, the summed figures, the delivered units, the row count — because that is the order the
    rollup stores and the order a ``SELECT`` over it returns.

    Args:
        key: The grouping value this aggregate stands for.
        label: Its human-readable name.
        bounds: ``(min, max)`` settlement date, which the rollup's key carries
            rather than its columns.
        values: The summed rollup columns.

    Returns:
        The same dataclass a direct query over the detail produces.
    """
    currency, subject_name, brand_name, *rest = values
    figures = rest[:-1]
    rows = rest[-1]
    return SettlementAggregate(
        key=key,
        label=label,
        date_from=bounds[0],
        date_to=bounds[1],
        currency=str(currency or ""),
        subject_name=str(subject_name or ""),
        brand_name=str(brand_name or ""),
        sold_units=int(figures[0]),
        returned_units=int(figures[1]),
        **{
            name: Decimal(figures[index + 2])
            for index, name in enumerate(
                (
                    "sales_gross",
                    "returns_gross",
                    "sales_before_spp",
                    "returns_before_spp",
                    "payout_sales",
                    "payout_returns",
                    "payout_other",
                    "wb_commission_reported",
                    "wb_commission_vat",
                    "wb_reward",
                    "acquiring_withheld",
                    "acquiring_billed_apart",
                    "agency_vat",
                    "logistics_forward",
                    "logistics_return",
                    "logistics_unlegged",
                    "storage",
                    "acceptance",
                    "penalties",
                    "deductions",
                    "additional_payments",
                    "rebill_logistic_cost",
                    "advertising",
                )
            )
        },
        rows=int(rows),
        delivered_units=int(figures[25]),
    )


def _to_aggregate(row: Sequence[Any]) -> SettlementAggregate:
    """Build a :class:`SettlementAggregate` from a ``(key, label, *_AGGREGATES)`` row."""
    return SettlementAggregate(
        key=row[0],
        label=str(row[1] or ""),
        date_from=row[2],
        date_to=row[3],
        currency=str(row[4]),
        subject_name=str(row[30] or ""),
        brand_name=str(row[31] or ""),
        sold_units=int(row[5]),
        returned_units=int(row[6]),
        sales_gross=Decimal(row[7]),
        returns_gross=Decimal(row[8]),
        sales_before_spp=Decimal(row[9]),
        returns_before_spp=Decimal(row[10]),
        payout_sales=Decimal(row[11]),
        payout_returns=Decimal(row[12]),
        payout_other=Decimal(row[13]),
        wb_commission_reported=Decimal(row[14]),
        wb_commission_vat=Decimal(row[15]),
        wb_reward=Decimal(row[16]),
        acquiring_withheld=Decimal(row[17]),
        acquiring_billed_apart=Decimal(row[18]),
        agency_vat=Decimal(row[19]),
        logistics_forward=Decimal(row[20]),
        logistics_return=Decimal(row[21]),
        logistics_unlegged=Decimal(row[22]),
        storage=Decimal(row[23]),
        acceptance=Decimal(row[24]),
        penalties=Decimal(row[25]),
        deductions=Decimal(row[26]),
        additional_payments=Decimal(row[27]),
        rebill_logistic_cost=Decimal(row[28]),
        advertising=Decimal(row[29]),
        rows=int(row[32]),
        delivered_units=int(row[33]),
    )
    # Row layout: key(0), label(1), then _AGGREGATES in order (2..). subject_name and
    # brand_name are appended just before the count, taking 30 and 31; count is 32,
    # delivered_units 33.


#: Grouping key + label expression per :class:`PnlGrouping`. Only the SKU cut
#: has a label worth carrying; period cuts are named by the caller, which knows
#: the report's stated period (``min(rr_dt)`` is not it — a report routinely
#: settles nothing on its first or last day).
_GROUP_KEYS: dict[PnlGrouping, tuple[SqlExpr, SqlExpr]] = {
    PnlGrouping.TOTAL: (literal(None), literal("")),
    PnlGrouping.DAY: (_T.rr_dt, literal("")),
    PnlGrouping.WEEK: (_T.report_id, literal("")),
    PnlGrouping.MONTH: (func.date_trunc("month", _T.rr_dt), literal("")),
    PnlGrouping.SKU: (_T.nm_id, func.max(_T.sa_name)),
}
