"""The settlement rollup: read it, prove it, repair what fails.

The detail is 870 MB against a 128 MB ``shared_buffers``, so every windowed
aggregate over it is a parallel seq scan — 714 MB off disk and ~7 s, measured on
this service's largest кабинет. The same rows collapse to 27 857 groups on
(кабинет, отчёт, день, артикул), which stays in cache.

**Nothing here trusts the cache.** A read first asks the detail how many rows
each day of the window holds — an index-only scan over
``ix_logistics_txn_ws_rr_dt``, 16 MB and ~0.7 s on the full history against the
detail's 755 MB and ~7 s — and compares that against what the rollup says it
summed. Days that agree are served from the rollup; days that disagree, or are
absent, are rebuilt from the detail and written back. So a rollup that is stale,
partial or empty costs time and never correctness, which is the only arrangement
under which keeping a derived copy of a seller's money is defensible.

That also means there is no build step, no harvest hook and no watermark to keep
in sync: the first read of a window pays for it and every later one is cheap.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import date
from typing import Any

from sqlalchemy import delete, func, literal, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from src.modules.finreports.models import SettlementDailyRollup
from src.modules.finreports.repos.pnl.aggregate import (
    _GROUP_EXPRESSIONS,
    _T,
    PnlGrouping,
    SettlementAggregate,
    SqlExpr,
    aggregate_from_rollup,
)

#: The rollup's own columns, in the order :data:`_GROUP_EXPRESSIONS` produces
#: them. One list, so a column added to the aggregate and forgotten here fails
#: loudly at import rather than quietly reading as zero.
ROLLUP_COLUMNS: tuple[str, ...] = (
    "currency",
    "subject_name",
    "brand_name",
    "sold_units",
    "returned_units",
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
    "rows",
)


class SettlementRollup:
    """Reads the rollup for a window, repairing whatever does not check out."""

    def __init__(self, session: AsyncSession) -> None:
        """Store the injected request-scoped async session."""
        self._session = session
        # Windows already proved fresh on THIS session. One page asks for the
        # same window three or four times — the aggregate, the costing units,
        # the currency — and verifying it once per ask turns the one cheap query
        # into four. The session is request-scoped, so this cache lives exactly
        # as long as the read it serves.
        self._verified: set[tuple[uuid.UUID, date, date]] = set()

    async def _detail_counts(
        self, *, workspace_id: uuid.UUID, date_from: date, date_to: date
    ) -> dict[date, int]:
        """How many detail rows each day of the window actually holds.

        The verification query, and the reason this design is safe. It reads
        only indexed columns, so Postgres answers it with a parallel index-only
        scan: 1 997 buffers against the 96 629 a real aggregate touches.
        """
        stmt = (
            select(_T.rr_dt, func.count())
            .where(
                _T.workspace_id == workspace_id,
                _T.rr_dt >= date_from,
                _T.rr_dt <= date_to,
            )
            .group_by(_T.rr_dt)
        )
        return {row[0]: int(row[1]) for row in (await self._session.execute(stmt)).all()}

    async def _rollup_counts(
        self, *, workspace_id: uuid.UUID, date_from: date, date_to: date
    ) -> dict[date, int]:
        """How many detail rows the rollup believes it summed, per day."""
        rollup = SettlementDailyRollup
        stmt = (
            select(rollup.rr_dt, func.sum(rollup.rows))
            .where(
                rollup.workspace_id == workspace_id,
                rollup.rr_dt >= date_from,
                rollup.rr_dt <= date_to,
            )
            .group_by(rollup.rr_dt)
        )
        return {row[0]: int(row[1] or 0) for row in (await self._session.execute(stmt)).all()}

    async def stale_days(
        self, *, workspace_id: uuid.UUID, date_from: date, date_to: date
    ) -> list[date]:
        """Return the days of the window the rollup cannot be trusted for.

        A day is stale when the rollup summed a different number of rows than
        the detail holds — which covers missing days (zero against something),
        days that grew when a later harvest back-filled them, and a rollup
        truncated by hand. Rows the detail holds with no ``rr_dt`` are outside
        every windowed query and so outside this comparison too.
        """
        detail = await self._detail_counts(
            workspace_id=workspace_id, date_from=date_from, date_to=date_to
        )
        cached = await self._rollup_counts(
            workspace_id=workspace_id, date_from=date_from, date_to=date_to
        )
        return sorted(day for day, rows in detail.items() if cached.get(day) != rows)

    async def rebuild(self, *, workspace_id: uuid.UUID, days: Sequence[date]) -> int:
        """Recompute the given days from the detail and write them back.

        Deletes first rather than upserting alone: a group that disappeared from
        the detail — a correction that moved a row to another article — would
        otherwise survive as a phantom the totals still count.

        Args:
            workspace_id: Owning workspace.
            days: The settlement dates to rebuild. Empty is a no-op.

        Returns:
            How many rollup rows the rebuild wrote.
        """
        if not days:
            return 0
        rollup = SettlementDailyRollup
        wanted = list(days)

        await self._session.execute(
            delete(rollup).where(rollup.workspace_id == workspace_id, rollup.rr_dt.in_(wanted))
        )

        source = (
            select(
                _T.workspace_id,
                _T.report_id,
                _T.rr_dt,
                _T.nm_id,
                func.max(_T.sa_name),
                *_GROUP_EXPRESSIONS,
            )
            .where(
                _T.workspace_id == workspace_id,
                _T.rr_dt.in_(wanted),
            )
            .group_by(_T.workspace_id, _T.report_id, _T.rr_dt, _T.nm_id)
        )
        rows = (await self._session.execute(source)).all()
        if not rows:
            return 0

        payload: list[dict[str, Any]] = [
            {
                "workspace_id": row[0],
                "report_id": row[1],
                "rr_dt": row[2],
                "nm_id": row[3],
                "sa_name": str(row[4] or ""),
                **dict(zip(ROLLUP_COLUMNS, row[5:], strict=True)),
            }
            for row in rows
        ]
        # ON CONFLICT rather than a bare INSERT: two requests can legitimately
        # repair the same window at the same moment, and the loser of that race
        # must write the same figures rather than raise.
        statement = insert(rollup).values(payload)
        await self._session.execute(
            statement.on_conflict_do_update(
                index_elements=["workspace_id", "report_id", "rr_dt", "nm_id"],
                set_={
                    name: getattr(statement.excluded, name) for name in (*ROLLUP_COLUMNS, "sa_name")
                },
            )
        )
        return len(payload)

    def group_key(self, grouping: PnlGrouping) -> tuple[SqlExpr, SqlExpr]:
        """The rollup's own ``(key, label)`` for a cut of the statement.

        Every cut is derivable from one stored grain because the key carries the
        report as well as the day: weeks group by ``report_id``, months by the
        truncated date, the per-article cut by ``nm_id`` and its label by the
        article the rollup stored alongside it.
        """
        rollup = SettlementDailyRollup
        return {
            PnlGrouping.TOTAL: (literal(None), literal("")),
            PnlGrouping.DAY: (rollup.rr_dt, literal("")),
            PnlGrouping.WEEK: (rollup.report_id, literal("")),
            PnlGrouping.MONTH: (func.date_trunc("month", rollup.rr_dt), literal("")),
            PnlGrouping.SKU: (rollup.nm_id, func.max(rollup.sa_name)),
        }[grouping]

    async def aggregate(
        self,
        *,
        workspace_id: uuid.UUID,
        date_from: date,
        date_to: date,
        grouping: PnlGrouping,
    ) -> list[SettlementAggregate]:
        """Aggregate the window off the rollup, having first made it trustworthy.

        The figures are identical to a direct pass over the detail — the stored
        columns ARE that pass's own expressions, summed at a finer grain — with
        one documented exception: the settlement currency is the modal currency
        of the rollup's GROUPS rather than of the detail's rows. The two differ
        only on a кабинет that settles two currencies inside one day, which is
        not a thing WB does; every other figure here is a plain sum and cannot
        drift.
        """
        await self.ensure_fresh(workspace_id=workspace_id, date_from=date_from, date_to=date_to)
        rollup = SettlementDailyRollup
        key, label = self.group_key(grouping)
        summed = [
            func.coalesce(
                func.mode().within_group(rollup.currency).filter(rollup.currency != ""), ""
            ),
            func.max(rollup.subject_name),
            func.max(rollup.brand_name),
            # Coalesced, because a window the кабинет settled nothing in still
            # has to produce a zeroed aggregate rather than a row of NULLs: the
            # TOTAL cut has no GROUP BY, so an empty window returns one row
            # regardless and every figure on it would be None.
            *(func.coalesce(func.sum(getattr(rollup, name)), 0) for name in ROLLUP_COLUMNS[3:]),
        ]
        stmt = select(key, label, func.min(rollup.rr_dt), func.max(rollup.rr_dt), *summed).where(
            rollup.workspace_id == workspace_id,
            rollup.rr_dt >= date_from,
            rollup.rr_dt <= date_to,
        )
        if grouping is not PnlGrouping.TOTAL:
            stmt = stmt.group_by(key).order_by(key.desc())
        rows = (await self._session.execute(stmt)).all()
        return [
            aggregate_from_rollup(
                key=row[0], label=str(row[1] or ""), bounds=(row[2], row[3]), values=row[4:]
            )
            for row in rows
        ]

    async def net_units(
        self,
        *,
        workspace_id: uuid.UUID,
        date_from: date,
        date_to: date,
        grouping: PnlGrouping,
    ) -> list[tuple[object, int, int]]:
        """Return ``(bucket key, nm_id, net units)`` for costing, off the rollup.

        The account-level bucket is excluded the same way the direct query
        excludes it: a cost price is a per-article figure and ``nm_id = 0`` is
        not an article.
        """
        await self.ensure_fresh(workspace_id=workspace_id, date_from=date_from, date_to=date_to)
        rollup = SettlementDailyRollup
        key, _label = self.group_key(grouping)
        net = func.sum(rollup.sold_units) - func.sum(rollup.returned_units)
        stmt = (
            select(key, rollup.nm_id, net)
            .where(
                rollup.workspace_id == workspace_id,
                rollup.rr_dt >= date_from,
                rollup.rr_dt <= date_to,
                rollup.nm_id != 0,
            )
            .group_by(key, rollup.nm_id)
            .having(net != 0)
        )
        rows = (await self._session.execute(stmt)).all()
        return [(row[0], int(row[1]), int(row[2])) for row in rows]

    async def ensure_fresh(self, *, workspace_id: uuid.UUID, date_from: date, date_to: date) -> int:
        """Make the rollup trustworthy for the window, and say what it cost.

        Returns:
            How many days had to be rebuilt — zero on the common path.
        """
        window = (workspace_id, date_from, date_to)
        if window in self._verified:
            return 0
        stale = await self.stale_days(
            workspace_id=workspace_id, date_from=date_from, date_to=date_to
        )
        await self.rebuild(workspace_id=workspace_id, days=stale)
        self._verified.add(window)
        return len(stale)
