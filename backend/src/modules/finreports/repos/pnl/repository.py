"""Read-side aggregation over the settlement rows, for the P&L.

A second repository on ``logistics_transaction``, deliberately. The existing
:class:`~src.modules.finreports.repos.transaction.LogisticsTransactionRepository`
answers one question — what did WB charge for logistics and how should it have
been charged — and is already near the module's file-size ceiling. The statement
asks a different question of the same table (what was sold, what was withheld,
what was paid out), so it gets its own module. Both are read-only projections.

Everything aggregates **in PostgreSQL**. The full history is 620k+ rows;
hydrating them to sum in Python would take seconds per request for a result that
is a few dozen numbers. The expressions themselves live in :mod:`.aggregate`.
"""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal
from typing import Any

from sqlalchemy import ColumnElement, case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.modules.finreports.constants import (
    ADVERTISING_DEDUCTION_MARKER,
    CLASSIFIED_OPERS,
    RETURN_OPERS,
    SALE_OPERS,
    SUBSCRIPTION_DEDUCTION_MARKER,
    TRANSIT_DEDUCTION_MARKER,
)
from src.modules.finreports.repos.pnl.aggregate import (
    _AGGREGATES,
    _GROUP_KEYS,
    _T,
    _ZERO,
    PnlGrouping,
    ReasonAmount,
    SettlementAggregate,
    SkuUnits,
    SqlExpr,
    _sum,
    _to_aggregate,
    _units,
)


class PnlRepository:
    """Settlement aggregation for the profit-and-loss statement."""

    def __init__(self, session: AsyncSession) -> None:
        """Store the injected request-scoped async session."""
        self._session = session

    def _window(self, workspace_id: uuid.UUID, date_from: date, date_to: date) -> list[SqlExpr]:
        """The settlement-date window every query in here is scoped to."""
        return [
            _T.workspace_id == workspace_id,
            _T.rr_dt >= date_from,
            _T.rr_dt <= date_to,
        ]

    async def aggregate(
        self,
        *,
        workspace_id: uuid.UUID,
        date_from: date,
        date_to: date,
        grouping: PnlGrouping,
    ) -> list[SettlementAggregate]:
        """Return the statement's inputs, cut by ``grouping``.

        Args:
            workspace_id: Owning workspace.
            date_from: Inclusive settlement-date start.
            date_to: Inclusive settlement-date end.
            grouping: Whole period, per weekly report, per month, or per SKU.

        Returns:
            One aggregate per group, newest/largest first for period cuts.
        """
        key, label = _GROUP_KEYS[grouping]
        stmt = select(key, label, *_AGGREGATES).where(
            *self._window(workspace_id, date_from, date_to)
        )
        if grouping is not PnlGrouping.TOTAL:
            stmt = stmt.group_by(key).order_by(key.desc())
        rows = (await self._session.execute(stmt)).all()
        return [_to_aggregate(row) for row in rows]

    async def reason_breakdown(
        self,
        *,
        workspace_id: uuid.UUID,
        date_from: date,
        date_to: date,
        column: str,
    ) -> list[ReasonAmount]:
        """Split one charge column by WB's own ``bonus_type_name`` reason.

        Args:
            workspace_id: Owning workspace.
            date_from: Inclusive settlement-date start.
            date_to: Inclusive settlement-date end.
            column: Money column to split (``delivery_rub``, ``penalty``, …).

        Returns:
            Non-zero buckets, largest first.
        """
        money = getattr(_T, column)
        reason = _deduction_bucket() if column == "deduction" else _T.bonus_type_name
        stmt = (
            select(reason, _sum(money), func.count())
            .where(*self._window(workspace_id, date_from, date_to), money != 0)
            .group_by(reason)
            .order_by(_sum(money).desc())
        )
        rows = (await self._session.execute(stmt)).all()
        return [
            ReasonAmount(reason=str(r[0] or "—"), amount=Decimal(r[1]), rows=int(r[2]))
            for r in rows
        ]

    async def sku_units(
        self, *, workspace_id: uuid.UUID, date_from: date, date_to: date
    ) -> list[SkuUnits]:
        """Return settled units per SKU, most-sold first.

        Feeds the cost-price editor's "which SKUs still have no cost" list, so
        the seller costs the SKUs that actually move rather than working down an
        alphabetical catalogue.
        """
        stmt = (
            select(
                _T.nm_id,
                func.max(_T.sa_name),
                _units(SALE_OPERS),
                _units(RETURN_OPERS),
            )
            .where(*self._window(workspace_id, date_from, date_to), _T.nm_id != 0)
            .group_by(_T.nm_id)
            .having(_units(SALE_OPERS) > 0)
            .order_by(_units(SALE_OPERS).desc())
        )
        rows = (await self._session.execute(stmt)).all()
        return [
            SkuUnits(
                nm_id=int(r[0]),
                vendor_code=str(r[1] or ""),
                sold_units=int(r[2]),
                returned_units=int(r[3]),
            )
            for r in rows
        ]

    async def cogs_inputs(
        self,
        *,
        workspace_id: uuid.UUID,
        date_from: date,
        date_to: date,
        grouping: PnlGrouping,
    ) -> list[tuple[object, int, int]]:
        """Return ``(bucket key, nm_id, net units)`` for costing.

        Cut per bucket AND per SKU, because a cost price is per SKU while the
        statement is per period: costing a bucket from its total units would need
        an average cost, and an average across a catalogue whose costs are only
        15 % known is a fabricated number.

        Net units per (bucket, SKU) legitimately go NEGATIVE — 32 of this
        seller's 2 473 reportxSKU cells are refund-only weeks — so the caller
        must let COGS go negative too rather than clamping, or a refunded week
        overstates profit.
        """
        key, _label = _GROUP_KEYS[grouping]
        net = _units(SALE_OPERS) - _units(RETURN_OPERS)
        stmt = (
            select(key, _T.nm_id, net)
            .where(*self._window(workspace_id, date_from, date_to), _T.nm_id != 0)
            .group_by(key, _T.nm_id)
            .having(net != 0)
        )
        rows = (await self._session.execute(stmt)).all()
        return [(r[0], int(r[1]), int(r[2])) for r in rows]

    async def sku_penalties(
        self, *, workspace_id: uuid.UUID, date_from: date, date_to: date
    ) -> list[tuple[int, str, Decimal]]:
        """Return each SKU's penalties split by WB's own reason.

        Feeds the per-SKU report's «Штрафы» column, which shows the categories
        the категории are what tell a seller which penalty is disputable.

        Returns:
            ``(nm_id, reason, amount)`` triples, non-zero only. ``nm_id = 0``
            rows are account-level fines and belong to the unallocated bucket.
        """
        stmt = (
            select(_T.nm_id, _T.bonus_type_name, _sum(_T.penalty))
            .where(*self._window(workspace_id, date_from, date_to), _T.penalty != _ZERO)
            .group_by(_T.nm_id, _T.bonus_type_name)
            .order_by(_sum(_T.penalty).desc())
        )
        rows = (await self._session.execute(stmt)).all()
        return [(int(r[0]), str(r[1] or "—"), Decimal(r[2])) for r in rows]

    async def revenue_coverage(
        self, *, workspace_id: uuid.UUID, date_from: date, date_to: date
    ) -> tuple[int, int]:
        """Return ``(sale rows, sale rows carrying revenue)`` for the window.

        The P&L columns were added to an existing 620k-row table zero-filled, so a
        window that has not been through ``scripts/backfill_pnl_columns.py`` has
        sale rows with no revenue and no payout — while its logistics, storage and
        penalties are complete, because those columns always existed. «Итого к
        оплате» then reports a full period of withholdings against a partial
        payout: a large, plausible loss. The caller turns this into a caveat.
        """
        stmt = select(
            func.count().filter(_T.supplier_oper_name.in_(list(SALE_OPERS))),
            func.count().filter(
                _T.supplier_oper_name.in_(list(SALE_OPERS)), _T.retail_amount != _ZERO
            ),
        ).where(*self._window(workspace_id, date_from, date_to))
        row = (await self._session.execute(stmt)).one()
        return int(row[0]), int(row[1])

    async def unclassified_opers(
        self, *, workspace_id: uuid.UUID, date_from: date, date_to: date
    ) -> list[str]:
        """Return operations in the window the statement has no rule for.

        The taxonomy in :mod:`~src.modules.finreports.constants` was derived from
        the history WB had published by 2026-07. A new operation would otherwise
        contribute to the charge lines (which sum whole columns) but silently
        miss the units and payout split, so the endpoint surfaces it as a caveat
        instead of quietly reporting a number that is a little bit wrong.
        """
        stmt = (
            select(_T.supplier_oper_name)
            .where(
                *self._window(workspace_id, date_from, date_to),
                _T.supplier_oper_name.notin_(list(CLASSIFIED_OPERS)),
            )
            .group_by(_T.supplier_oper_name)
        )
        return [str(row[0]) for row in (await self._session.execute(stmt)).all()]


def _deduction_bucket() -> ColumnElement[Any]:
    """Bucket «Удержание» reasons, which embed an invoice number.

    Advertising is 95 % of everything WB has ever withheld from this seller, so
    it gets its own line; the rest degrade into «Прочие удержания» rather than
    fragmenting the statement into one row per invoice.
    """
    return case(
        (_T.bonus_type_name.contains(ADVERTISING_DEDUCTION_MARKER), "Реклама (ВБ.Продвижение)"),
        (_T.bonus_type_name.contains(SUBSCRIPTION_DEDUCTION_MARKER), "Подписка «Джем»"),
        (_T.bonus_type_name.contains(TRANSIT_DEDUCTION_MARKER), "Доставка транзитных поставок"),
        else_="Прочие удержания",
    )
