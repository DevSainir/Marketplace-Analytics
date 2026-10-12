"""Persistence for hand-uploaded weekly reports and the rows they stand in with.

Two kinds of write, kept in one place because they must agree on one rule:
**an uploaded row is a row with a negative ``rrd_id``**. Everything that has to
tell a file's row from WB's reads that sign, and nothing else marks it.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator, Sequence
from datetime import UTC, date, datetime, timedelta
from typing import Any

from sqlalchemy import delete, func, select, update

from src.modules.finreports.models import (
    UPLOAD_ROW_SEQUENCE,
    FinancialReport,
    LogisticsTransaction,
    SettlementDailyRollup,
    SettlementUpload,
    UploadStatus,
)
from src.modules.finreports.repos.base import BaseRepository
from src.modules.finreports.repos.pnl.rollup_lock import hold_rollup_lock

_T = LogisticsTransaction

#: An upload the worker has held longer than this is presumed dead — killed
#: mid-read — and no longer blocks the next one.
_STALE_AFTER = timedelta(minutes=30)

_IN_FLIGHT = (UploadStatus.QUEUED, UploadStatus.PROCESSING)


class SettlementUploadRepository(BaseRepository):
    """Uploads, and the settlement rows that came from them."""

    model = SettlementUpload

    async def create(self, upload: SettlementUpload) -> SettlementUpload:
        """Add a new upload and flush, so its id is known."""
        self._session.add(upload)
        await self._session.flush()
        return upload

    async def get(
        self, *, workspace_id: uuid.UUID, upload_id: uuid.UUID
    ) -> SettlementUpload | None:
        """One upload, only within its own workspace."""
        stmt = select(SettlementUpload).where(
            SettlementUpload.workspace_id == workspace_id, SettlementUpload.id == upload_id
        )
        return (await self._session.execute(stmt)).scalars().first()

    async def in_flight(self, *, workspace_id: uuid.UUID) -> bool:
        """Whether this workspace has an upload the worker has not finished."""
        stmt = select(func.count()).where(
            SettlementUpload.workspace_id == workspace_id,
            SettlementUpload.status.in_(_IN_FLIGHT),
            SettlementUpload.uploaded_at > datetime.now(UTC) - _STALE_AFTER,
        )
        return bool((await self._session.execute(stmt)).scalar_one())

    async def claim(self, *, upload_id: uuid.UUID) -> SettlementUpload | None:
        """Take a queued upload for processing; ``None`` if it is not queued.

        A conditional ``UPDATE``, so two deliveries of the task cannot both
        process one file.
        """
        stmt = (
            update(SettlementUpload)
            .where(SettlementUpload.id == upload_id, SettlementUpload.status == UploadStatus.QUEUED)
            .values(status=UploadStatus.PROCESSING)
            .returning(SettlementUpload.id)
        )
        if (await self._session.execute(stmt)).scalar_one_or_none() is None:
            return None
        return await self._session.get(SettlementUpload, upload_id)

    async def standing(self, *, workspace_id: uuid.UUID) -> list[SettlementUpload]:
        """Uploads whose rows stand in the P&L now, newest period first."""
        stmt = (
            select(SettlementUpload)
            .where(
                SettlementUpload.workspace_id == workspace_id,
                SettlementUpload.status == UploadStatus.WRITTEN,
            )
            .order_by(SettlementUpload.date_to.desc())
        )
        return list((await self._session.execute(stmt)).scalars())

    async def standing_for_report(
        self, *, workspace_id: uuid.UUID, report_id: int
    ) -> SettlementUpload | None:
        """The upload standing in for one WB report, if any."""
        stmt = select(SettlementUpload).where(
            SettlementUpload.workspace_id == workspace_id,
            SettlementUpload.report_id == report_id,
            SettlementUpload.status == UploadStatus.WRITTEN,
        )
        return (await self._session.execute(stmt)).scalars().first()

    async def report_is_booked(self, *, workspace_id: uuid.UUID, report_id: int) -> bool:
        """Whether WB's API has served this report whole — its header is on file."""
        stmt = select(func.count()).where(
            FinancialReport.workspace_id == workspace_id, FinancialReport.report_id == report_id
        )
        return bool((await self._session.execute(stmt)).scalar_one())

    async def rows_in_period(
        self, *, workspace_id: uuid.UUID, date_from: date, date_to: date, columns: Sequence[str]
    ) -> AsyncIterator[dict[str, Any]]:
        """Stream the named columns of every row we hold for the period's days."""
        stmt = select(*(getattr(_T, column) for column in columns)).where(
            _T.workspace_id == workspace_id, _T.rr_dt >= date_from, _T.rr_dt <= date_to
        )
        result = await self._session.stream(stmt.execution_options(yield_per=5000))
        async for row in result.mappings():
            yield dict(row)

    async def report_rows(
        self, *, workspace_id: uuid.UUID, report_id: int, columns: Sequence[str]
    ) -> AsyncIterator[dict[str, Any]]:
        """Stream the named columns of one report's rows as WB's API served them."""
        stmt = select(*(getattr(_T, column) for column in columns)).where(
            _T.workspace_id == workspace_id, _T.report_id == report_id, _T.rrd_id > 0
        )
        result = await self._session.stream(stmt.execution_options(yield_per=5000))
        async for row in result.mappings():
            yield dict(row)

    async def next_row_ids(self, count: int) -> list[int]:
        """``count`` fresh ids for uploaded rows — negative, so never a WB id."""
        if count <= 0:
            return []
        stmt = select(UPLOAD_ROW_SEQUENCE.next_value()).select_from(
            func.generate_series(1, count).table_valued("n")
        )
        return [-int(value) for value in (await self._session.execute(stmt)).scalars()]

    async def drop_uploaded_rows(self, *, workspace_id: uuid.UUID, report_id: int) -> int:
        """Delete one report's uploaded rows and forget the rollup of their days.

        The same invalidation :class:`TransactionRepository` does on a write,
        and for the same reason: the rollup proves itself by row count, and a
        day whose rows were swapped one for one keeps its count.
        """
        await hold_rollup_lock(self._session, workspace_id, shared=False)
        days = (
            await self._session.execute(
                select(_T.rr_dt)
                .distinct()
                .where(_T.workspace_id == workspace_id, _T.report_id == report_id, _T.rrd_id < 0)
            )
        ).scalars()
        touched = sorted(day for day in days if day is not None)
        result = await self._session.execute(
            delete(_T).where(
                _T.workspace_id == workspace_id, _T.report_id == report_id, _T.rrd_id < 0
            )
        )
        if touched:
            await self._session.execute(
                delete(SettlementDailyRollup).where(
                    SettlementDailyRollup.workspace_id == workspace_id,
                    SettlementDailyRollup.rr_dt.in_(touched),
                )
            )
        return int(getattr(result, "rowcount", 0) or 0)


__all__ = ["SettlementUploadRepository"]
