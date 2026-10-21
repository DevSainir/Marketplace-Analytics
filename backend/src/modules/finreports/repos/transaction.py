"""Data access for logistics settlement transactions (the finance-report rows)."""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import date
from typing import Any

from sqlalchemy import delete, exists, select

from src.modules.finreports.models import LogisticsTransaction, SettlementDailyRollup
from src.modules.finreports.repos.base import BaseRepository
from src.modules.finreports.repos.pnl.rollup_lock import hold_rollup_lock


class LogisticsTransactionRepository(BaseRepository):
    """Settlement-row storage."""

    model = LogisticsTransaction

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
        # two writers of the same workspaces take them in one order.
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
        """Whether any row of this report that WB's API served is on file.

        Rows from a hand-uploaded file carry the report's number too, with a
        negative ``rrd_id``; they must not let the header be booked over a report
        the API has not served — booked, it would count as held and never be
        fetched.
        """
        txn = LogisticsTransaction
        stmt = select(
            exists().where(
                txn.workspace_id == workspace_id, txn.report_id == report_id, txn.rrd_id > 0
            )
        )
        return bool((await self._session.execute(stmt)).scalar())
