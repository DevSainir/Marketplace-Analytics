"""Data access for logistics settlement transactions (the finance-report rows)."""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any, NamedTuple

from sqlalchemy import case, delete, exists, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.modules.finreports.constants import (
    LOGISTICS_OPER,
    PENALTY_OPER,
)
from src.modules.finreports.models import LogisticsTransaction, SettlementDailyRollup
from src.modules.finreports.repos.base import BaseRepository
from src.modules.finreports.repos.pnl.rollup import SettlementRollup
from src.modules.finreports.repos.pnl.rollup_lock import hold_rollup_lock



    Deliberately NOT the ORM entity. The claim window returns ~17k rows, and
    hydrating them as ``LogisticsTransaction`` instances cost 1.07 s against
    production data while the SQL itself ran in 66 ms — the time was going into
    building 17k objects with all 32 mapped columns, ~13 of which the ledger
    never reads. Selecting only these columns into a tuple measured **3.5x**
    faster end to end (1.07 s -> 0.31 s).

    A ``NamedTuple`` keeps the call sites unchanged: the ledger builder reaches
    for ``t.delivery_rub`` and friends by name exactly as it did on the entity,
    and ``_make`` costs nothing meaningful over the raw row.

    Field order MUST match :data:`_CLAIM_SOURCE_COLUMNS`.
    """

    report_id: int
    rrd_id: int
    rr_dt: date | None
    nm_id: int
    sa_name: str
    barcode: str
    srid: str
    shk_id: int | None
    gi_id: int | None
    office_name: str
    supplier_oper_name: str
    bonus_type_name: str
    currency_name: str
    delivery_amount: int
    dlv_prc: Decimal | None
    delivery_rub: Decimal
    penalty: Decimal
    fix_tariff_date_from: date | None
    fix_tariff_date_to: date | None


_CLAIM_SOURCE_COLUMNS = (
    LogisticsTransaction.report_id,
    LogisticsTransaction.rrd_id,
    LogisticsTransaction.rr_dt,
    LogisticsTransaction.nm_id,
    LogisticsTransaction.sa_name,
    LogisticsTransaction.barcode,
    LogisticsTransaction.srid,
    LogisticsTransaction.shk_id,
    LogisticsTransaction.gi_id,
    LogisticsTransaction.office_name,
    LogisticsTransaction.supplier_oper_name,
    LogisticsTransaction.bonus_type_name,
    LogisticsTransaction.currency_name,
    LogisticsTransaction.delivery_amount,
    LogisticsTransaction.dlv_prc,
    LogisticsTransaction.delivery_rub,
    LogisticsTransaction.penalty,
    LogisticsTransaction.fix_tariff_date_from,
    LogisticsTransaction.fix_tariff_date_to,
)


@dataclass(frozen=True)
class SkuRepricingPlan:
    """Instructions for re-pricing one SKU's logistics inside the database.

    Attributes:
        nm_id: The SKU.
        timeline: ``[(start_date, ratio), ...]`` ordered by start date, where
            the first start is ``None`` (unbounded) and each ratio applies until
            the next entry's start — exactly the shape
            produces.
    """

    nm_id: int
    timeline: list[tuple[date | None, Decimal]]


@dataclass(frozen=True)
    """One SKU's logistics re-priced against WB's own measurement record.

    Attributes:
        nm_id: The SKU.
        charged: Σ ``delivery_rub`` WB actually withheld.
        fair: Σ of what each row should have cost at the reference volume.
        overpay: ``charged - fair`` (never negative in aggregate — credit notes
    """

    nm_id: int
    charged: Decimal
    fair: Decimal
    overpay: Decimal


@dataclass(frozen=True)
class SkuLogisticsAggregate:
    """Per-SKU rollup of the raw settlement facts over a window.

    Attributes:
        nm_id: WB SKU identifier.
        sa_name: Representative seller article code.
        logistics_billed: Sum of ``delivery_rub`` on logistics rows.
        logistics_rows: Count of logistics rows.
        delivery_units: Sum of ``delivery_amount`` on logistics rows.
        currency: Representative settlement currency (e.g. ``KGS``).
    """

    nm_id: int
    sa_name: str
    logistics_billed: Decimal
    logistics_rows: int
    delivery_units: int
    currency: str


class LogisticsTransactionRepository(BaseRepository):

    model = LogisticsTransaction

    def __init__(self, session: AsyncSession) -> None:
        """Store the session, and the rollup the summary's aggregates are read from."""
        super().__init__(session)
        self._rollup = SettlementRollup(session)

    async def bulk_upsert(
        self,
        rows: Sequence[dict[str, Any]],
        *,
        conflict_columns: Sequence[str],
        update_columns: Sequence[str],
    ) -> int:
        """Upsert settlement rows and forget the rollup of every day they touch.

        The rollup proves itself by row count, and a row rewritten in place does
        not change the count: the weekly report rewrites every row the daily
        lane wrote, under a new ``report_id``, and a restated daily report comes
        back with new amounts on the same ``rrd_id``. Deleting those days here,
        in the same transaction as the write, makes them miss on the next read,
        which rebuilds them from the detail — see
        :mod:`src.modules.finreports.repos.pnl.rollup`.
        """
        touched: dict[uuid.UUID, set[date]] = {}
        for row in rows:
            if row.get("rr_dt") is not None:
                touched.setdefault(row["workspace_id"], set()).add(row["rr_dt"])
        # Exclusive, and taken BEFORE the write, so a rebuild in flight finishes
        # first and its days are deleted below — see `rollup_lock`. Sorted so
        # two writers of the same кабинеты take them in one order.
        for workspace_id in sorted(touched, key=str):
            await hold_rollup_lock(self._session, workspace_id, shared=False)
        written = await super().bulk_upsert(
            rows, conflict_columns=conflict_columns, update_columns=update_columns
        )
        for workspace_id, days in touched.items():
            await self._session.execute(
                delete(SettlementDailyRollup).where(
                    SettlementDailyRollup.workspace_id == workspace_id,
                    SettlementDailyRollup.rr_dt.in_(sorted(days)),
                )
            )
        return written

    async def holds_report(self, *, workspace_id: uuid.UUID, report_id: int) -> bool:
        """Whether any settlement row of this report is on file for the workspace."""
        txn = LogisticsTransaction
        stmt = select(exists().where(txn.workspace_id == workspace_id, txn.report_id == report_id))
        return bool((await self._session.execute(stmt)).scalar())

    async def aggregate_by_sku(
        self, *, workspace_id: uuid.UUID, date_from: date, date_to: date
    ) -> list[SkuLogisticsAggregate]:

        Off the settlement rollup, which stores these four figures per
        (отчёт, день, артикул) — see
        detail is no longer read here. The currency is the modal one of the
        SKU's groups, as everywhere else the rollup is read: ``max()`` is
        lexical and would call a KGS article "RUB" over one stray row.

        Args:
            workspace_id: Tenancy scope.
            date_from: Inclusive settlement-date start.
            date_to: Inclusive settlement-date end.

        Returns:
            One :class:`SkuLogisticsAggregate` per SKU that has any settlement row
            in the window, ordered by logistics billed (descending).
        """
        await self._rollup.ensure_fresh(
            workspace_id=workspace_id, date_from=date_from, date_to=date_to
        )
        rollup = SettlementDailyRollup
        stmt = (
            select(
                rollup.nm_id,
                func.max(rollup.sa_name),
                billed,
                func.mode().within_group(rollup.currency).filter(rollup.currency != ""),
            )
            .where(
                rollup.workspace_id == workspace_id,
                rollup.rr_dt >= date_from,
                rollup.rr_dt <= date_to,
            )
            .group_by(rollup.nm_id)
            .order_by(billed.desc())
        )
        result = await self._session.execute(stmt)
        return [
            SkuLogisticsAggregate(
                nm_id=row[0],
                sa_name=row[1] or "",
                logistics_billed=Decimal(row[2]),
                logistics_rows=int(row[3]),
                delivery_units=int(row[4]),
                currency=row[6] or "",
            )
            for row in result.all()
        ]

        self,
        *,
        workspace_id: uuid.UUID,
        date_from: date,
        date_to: date,
        plans: Sequence[SkuRepricingPlan],
        """Re-price each SKU's logistics in SQL and return the per-SKU totals.

        row — ``ROUND(delivery_rub * ratio, 2)`` per row, then summed — so the
        the kopeck, without the page paying for 83 443 hydrated rows (~6 s) to
        get there. ``ROUND(numeric, 2)`` is half-up away from zero, matching
        :data:`decimal.ROUND_HALF_UP` on the non-negative amounts re-priced here.

        Credit notes (``delivery_rub < 0``) pass through untouched: re-pricing a

        Args:
            workspace_id: Tenancy scope.
            date_from: Inclusive settlement-date start.
            date_to: Inclusive settlement-date end.
            plans: Per-SKU re-pricing timelines (empty → empty mapping).

        Returns:
            logistics row in the window.
        """
        if not plans:
            return {}
        txn = LogisticsTransaction
        # One CASE over every (SKU, date range). Ranges are emitted newest-first
        # so the first matching branch is the latest measurement in force —
        # the SQL twin of `applicable_basis`, whose opening range is unbounded.
        whens = []
        for plan in plans:
            for start, ratio in reversed(plan.timeline):
                condition = txn.nm_id == plan.nm_id
                if start is not None:
                    condition = condition & (txn.rr_dt >= start)
                whens.append((condition & (txn.delivery_rub > 0), ratio))
        # `else_` is a Decimal, not the int 1, so the CASE (and the product with
        # it) stays `numeric` — exact — instead of collapsing to a float.
        fair_expr = func.round(txn.delivery_rub * case(*whens, else_=Decimal(1)), 2)
        charged = func.coalesce(func.sum(txn.delivery_rub), 0)
        fair = func.coalesce(func.sum(fair_expr), 0)
        stmt = (
            select(txn.nm_id, charged, fair)
            .where(
                txn.workspace_id == workspace_id,
                txn.nm_id.in_([p.nm_id for p in plans]),
                txn.rr_dt >= date_from,
                txn.rr_dt <= date_to,
                txn.supplier_oper_name == LOGISTICS_OPER,
            )
            .group_by(txn.nm_id)
        )
        result = await self._session.execute(stmt)
        return {
                nm_id=row[0],
                charged=Decimal(row[1]),
                fair=Decimal(row[2]),
                overpay=Decimal(row[1]) - Decimal(row[2]),
            )
            for row in result.all()
        }

    async def list_for_sku(
        self, *, nm_id: int, date_from: date, date_to: date
    ) -> list[LogisticsTransaction]:
        """Return every settlement row for one SKU in the window (evidence view).

        Args:
            nm_id: SKU to fetch rows for.
            date_from: Inclusive settlement-date start.
            date_to: Inclusive settlement-date end.

        Returns:
            The SKU's settlement rows ordered by settlement date.
        """
        stmt = (
            select(LogisticsTransaction)
            .where(
                LogisticsTransaction.nm_id == nm_id,
                LogisticsTransaction.rr_dt >= date_from,
                LogisticsTransaction.rr_dt <= date_to,
            )
            .order_by(LogisticsTransaction.rr_dt, LogisticsTransaction.rrd_id)
        )
        return list((await self._session.execute(stmt)).scalars().all())

    async def claim_ledger_rows(
        self,
        *,
        workspace_id: uuid.UUID,
        date_from: date,
        date_to: date,
        nm_ids: Sequence[int],
        """Return every logistics/penalty row backing a claim, ordered for audit.

        ledger reads in the same order as WB's own weekly reports.

        Args:
            workspace_id: Tenancy scope.
            date_from: Inclusive settlement-date start.
            date_to: Inclusive settlement-date end.

        Returns:
            The settlement rows, ordered by ``(report_id, rr_dt, rrd_id)``.
        """
        if not nm_ids:
            return []
        txn = LogisticsTransaction
        )
        stmt = (
            select(*_CLAIM_SOURCE_COLUMNS)
            .where(
                txn.workspace_id == workspace_id,
                txn.nm_id.in_(nm_ids),
                txn.rr_dt >= date_from,
                txn.rr_dt <= date_to,
            )
            .order_by(txn.report_id, txn.rr_dt, txn.rrd_id)
        )
        result = await self._session.execute(stmt)

    async def window_checksum(
        self, *, workspace_id: uuid.UUID, date_from: date, date_to: date
    ) -> tuple[int, int]:

        Taken over the rollup, not the detail: hashing the detail was a 1.6 GB
        seq scan on every cache HIT of «Вся история» — 11.5 s to learn that
        nothing had changed (measured 2026-10-09). The rollup answers the same
        question. Rows added or removed fail the day's row count and the day is
        rebuilt; a row restated in place comes through
        :meth:`bulk_upsert`, which deletes its day, so it is rebuilt too. Either
        way the day's groups come back with a new ``built_at``, and that is
        what moves this checksum — alongside the figures themselves, which
        :meth:`aggregate_by_sku` reads.

        What it cannot see is a detail row edited by hand with ``UPDATE``,
        which the P&L could not see either.
        """
        await self._rollup.ensure_fresh(
            workspace_id=workspace_id, date_from=date_from, date_to=date_to
        )
        rollup = SettlementDailyRollup
        return await self.checksum(
            rollup.report_id,
            rollup.rr_dt,
            rollup.nm_id,
            rollup.built_at,
            rollup.rows,
            rollup.sa_name,
            rollup.currency,
            where=(
                rollup.workspace_id == workspace_id,
                rollup.rr_dt >= date_from,
                rollup.rr_dt <= date_to,
            ),
            source=rollup,
        )

        self,
        *,
        workspace_id: uuid.UUID,
        date_from: date,
        date_to: date,
        nm_ids: Sequence[int],
    ) -> tuple[int, int]:
        """Checksum the same row set :meth:`claim_ledger_rows` returns.

        The predicate MUST stay identical to that method's, or the cache would
        key on a different population than it renders. Only the columns that
        reach a document are folded in — a change to any of them must produce a
        different package, and does.
        """
        if not nm_ids:
            return (0, 0)
        txn = LogisticsTransaction
        )
        return await self.checksum(
            *_CLAIM_SOURCE_COLUMNS,
            where=(
                txn.workspace_id == workspace_id,
                txn.nm_id.in_(nm_ids),
                txn.rr_dt >= date_from,
                txn.rr_dt <= date_to,
            ),
        )
