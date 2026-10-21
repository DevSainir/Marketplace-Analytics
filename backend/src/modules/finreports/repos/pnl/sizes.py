"""Per-size aggregation of one SKU's settlement rows.

WB publishes no size in any of its report AGGREGATES, but it stamps ``ts_name``
on every settlement row it bills — measured over «Демо»'s last quarter, all
76 017 «Логистика», 13 101 «Продажа» and 1 560 «Возврат» rows carry one, and the
only rows without are the 126 account-level «Хранение»/«Удержание» lines that
belong to no article either. So a size cut of one article is a regrouping of the
rows the article's own row is already built from, not an allocation: Σ sizes =
the article, exactly, and that is what
``test_sizes_match_the_article`` holds us to.

Deliberately NOT a :class:`~.aggregate.SettlementAggregate`. That dataclass is
sliced by position into the rollup's column order
(:data:`~.aggregate._GROUP_EXPRESSIONS`), so a field added for this cut would
silently move every rollup column; and this cut needs one figure the statement
never wanted — the count of forward logistics legs, which is the only
measurement of "how many units reached a buyer" that carries a size.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any

from sqlalchemy import ColumnElement, case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.modules.finreports.constants import REFUND_DOC_TYPE, RETURN_OPERS, SALE_OPERS
from src.modules.finreports.models import LogisticsTransaction

_ZERO = Decimal(0)
_T = LogisticsTransaction


@dataclass(frozen=True)
class SizeSettlement:
    """One size's settlement rows, summed.

    Every field is a ``SUM`` over a filtered set of the article's own rows —
    nothing is derived and nothing is smeared, so each figure on the rendered
    size line traces back to a column and a row filter.

    Attributes:
        ts_name: WB's size label (``""`` on the rows WB bills without one).
        sold_units / returned_units: Units on «Продажа» / «Возврат» rows.
        delivered_units: Σ ``delivery_amount`` — forward logistics legs, i.e.
            how many units WB actually carried to a buyer. The size-level
            denominator of «Выкуп»: the funnel's orders have no size.
        sales_gross / returns_gross: ``retail_amount`` — paid and refunded.
        sales_before_spp / returns_before_spp: ``retail_price_withdisc_rub`` —
            the same at the seller's own price, before WB's SPP.
        payout_sales / payout_returns / payout_other: ``ppvz_for_pay`` on sale
            rows, refund rows, and everything else (WB's compensations).
        logistics_forward / logistics_return / logistics_unlegged:
            ``delivery_rub`` split by which leg counter WB set on the row.
        penalties / storage / acceptance / deductions / additional_payments /
            rebill_logistic_cost: The withholdings, each from its own column —
            carried so this cut's «К перечислению» is the SAME formula the
            article's is, and therefore sums back to it.
        rows: How many settlement rows fed this size.
    """

    ts_name: str
    sold_units: int
    returned_units: int
    delivered_units: int
    sales_gross: Decimal
    returns_gross: Decimal
    sales_before_spp: Decimal
    returns_before_spp: Decimal
    payout_sales: Decimal
    payout_returns: Decimal
    payout_other: Decimal
    logistics_forward: Decimal
    logistics_return: Decimal
    logistics_unlegged: Decimal
    penalties: Decimal
    storage: Decimal
    acceptance: Decimal
    deductions: Decimal
    additional_payments: Decimal
    rebill_logistic_cost: Decimal
    rows: int


def _sum(expression: Any) -> ColumnElement[Any]:
    """Sum a money column, substituting 0 for an empty set."""
    return func.coalesce(func.sum(expression), _ZERO)


def _on(opers: tuple[str, ...], column: Any) -> ColumnElement[Any]:
    """Sum a column over the given operations only."""
    return _sum(case((_T.supplier_oper_name.in_(list(opers)), column), else_=_ZERO))


def _units(opers: tuple[str, ...]) -> ColumnElement[Any]:
    """Count units on the given operations only.

    Never a bare ``SUM(quantity)`` — «Возмещение издержек» carries a constant
    filler quantity, the same trap the statement's own unit counters avoid.
    """
    return func.coalesce(
        func.sum(case((_T.supplier_oper_name.in_(list(opers)), _T.quantity), else_=0)), 0
    )


#: The summed columns, in :class:`SizeSettlement` field order after ``ts_name``.
_COLUMNS: tuple[Any, ...] = (
    _units(SALE_OPERS),
    _units(RETURN_OPERS),
    func.coalesce(func.sum(_T.delivery_amount), 0),
    _on(SALE_OPERS, _T.retail_amount),
    _on(RETURN_OPERS, _T.retail_amount),
    _on(SALE_OPERS, _T.retail_price_withdisc_rub),
    _on(RETURN_OPERS, _T.retail_price_withdisc_rub),
    _on(SALE_OPERS, _T.ppvz_for_pay),
    _on(RETURN_OPERS, _T.ppvz_for_pay),
    _sum(
        case(
            (_T.supplier_oper_name.in_(list(SALE_OPERS) + list(RETURN_OPERS)), _ZERO),
            (_T.doc_type_name == REFUND_DOC_TYPE, -_T.ppvz_for_pay),
            else_=_T.ppvz_for_pay,
        )
    ),
    _sum(case(((_T.delivery_amount > 0) & (_T.return_amount == 0), _T.delivery_rub), else_=_ZERO)),
    _sum(case((_T.return_amount > 0, _T.delivery_rub), else_=_ZERO)),
    _sum(case(((_T.delivery_amount == 0) & (_T.return_amount == 0), _T.delivery_rub), else_=_ZERO)),
    _sum(_T.penalty),
    _sum(_T.storage_fee),
    _sum(_T.acceptance),
    _sum(_T.deduction),
    _sum(_T.additional_payment),
    _sum(_T.rebill_logistic_cost),
    func.count(),
)


async def aggregate_by_size(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    nm_id: int,
    date_from: date,
    date_to: date,
) -> list[SizeSettlement]:
    """Roll one SKU's settlement rows up per ``ts_name``.

    Aggregated in PostgreSQL like every other P&L read, and scoped to a single
    ``nm_id`` — which is what keeps it cheap enough to run on a click:
    ``ix_logistics_txn_nm_id_rr_dt`` covers exactly this predicate.

    Args:
        session: Request-scoped async session.
        workspace_id: Tenancy scope.
        nm_id: The article whose sizes are wanted.
        date_from: Inclusive settlement-date start.
        date_to: Inclusive settlement-date end.

    Returns:
        One entry per size the article has any row for, ordered by size label.
    """
    stmt = (
        select(_T.ts_name, *_COLUMNS)
        .where(
            _T.workspace_id == workspace_id,
            _T.nm_id == nm_id,
            _T.rr_dt >= date_from,
            _T.rr_dt <= date_to,
        )
        .group_by(_T.ts_name)
        .order_by(_T.ts_name)
    )
    rows = (await session.execute(stmt)).all()
    return [
        SizeSettlement(
            ts_name=str(row[0] or ""),
            sold_units=int(row[1]),
            returned_units=int(row[2]),
            delivered_units=int(row[3]),
            sales_gross=Decimal(row[4]),
            returns_gross=Decimal(row[5]),
            sales_before_spp=Decimal(row[6]),
            returns_before_spp=Decimal(row[7]),
            payout_sales=Decimal(row[8]),
            payout_returns=Decimal(row[9]),
            payout_other=Decimal(row[10]),
            logistics_forward=Decimal(row[11]),
            logistics_return=Decimal(row[12]),
            logistics_unlegged=Decimal(row[13]),
            penalties=Decimal(row[14]),
            storage=Decimal(row[15]),
            acceptance=Decimal(row[16]),
            deductions=Decimal(row[17]),
            additional_payments=Decimal(row[18]),
            rebill_logistic_cost=Decimal(row[19]),
            rows=int(row[20]),
        )
        for row in rows
    ]
