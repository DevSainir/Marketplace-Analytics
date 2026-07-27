"""Data access for logistics settlement transactions (the finance-report rows)."""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from sqlalchemy import case, func, select

from src.modules.finreports.constants import (
    LOGISTICS_OPER,
    PENALTY_OPER,
)
from src.modules.finreports.models import LogisticsTransaction
from src.modules.finreports.repos.base import BaseRepository


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

    async def aggregate_by_sku(
        self, *, workspace_id: uuid.UUID, date_from: date, date_to: date
    ) -> list[SkuLogisticsAggregate]:

        Args:
            workspace_id: Tenancy scope.
            date_from: Inclusive settlement-date start.
            date_to: Inclusive settlement-date end.

        Returns:
            One :class:`SkuLogisticsAggregate` per SKU that has any settlement row
            in the window, ordered by logistics billed (descending).
        """
        txn = LogisticsTransaction
        is_logistics = txn.supplier_oper_name == LOGISTICS_OPER
        )
        logistics_billed = func.coalesce(
            func.sum(case((is_logistics, txn.delivery_rub), else_=0)), 0
        )
        logistics_rows = func.coalesce(func.sum(case((is_logistics, 1), else_=0)), 0)
        delivery_units = func.coalesce(
            func.sum(case((is_logistics, txn.delivery_amount), else_=0)), 0
        )
        stmt = (
            select(
                txn.nm_id,
                func.max(txn.sa_name),
                logistics_billed,
                logistics_rows,
                delivery_units,
                func.max(txn.currency_name),
            )
            .where(
                txn.workspace_id == workspace_id,
                txn.rr_dt >= date_from,
                txn.rr_dt <= date_to,
            )
            .group_by(txn.nm_id)
            .order_by(logistics_billed.desc())
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
    ) -> list[LogisticsTransaction]:
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
            select(txn)
            .where(
                txn.workspace_id == workspace_id,
                txn.nm_id.in_(nm_ids),
                txn.rr_dt >= date_from,
                txn.rr_dt <= date_to,
            )
            .order_by(txn.report_id, txn.rr_dt, txn.rrd_id)
        )
        return list((await self._session.execute(stmt)).scalars().all())
