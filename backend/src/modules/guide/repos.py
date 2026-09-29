"""Persistence for the capture buffer: upsert rows, read and write watermarks."""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import date
from typing import Any

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.upsert import upsert_rows
from src.modules.guide.models import GuideRecord, GuideRun


class GuideRepository:
    """Reads and writes the two ``guide`` tables."""

    def __init__(self, session: AsyncSession) -> None:
        """Store the injected async session; the caller owns the transaction."""
        self._session = session

    async def upsert_records(
        self,
        *,
        source: str,
        workspace_id: uuid.UUID,
        rows: Sequence[tuple[str, date | None, dict[str, Any]]],
    ) -> int:
        """Store ``(key, day, payload)`` triples, overwriting what was there.

        Overwriting rather than skipping is the point: WB restates recent rows
        (an order gets cancelled, a claim changes status), so a re-read of a
        window that already landed must win, not be discarded as a duplicate.

        Args:
            source: Feed key.
            workspace_id: Owning tenant.
            rows: ``(record_key, recorded_for, payload)`` per WB row.

        Returns:
            How many rows were submitted.
        """
        if not rows:
            return 0
        payloads = [
            {
                "source": source,
                "workspace_id": workspace_id,
                "record_key": key[:160],
                "recorded_for": day,
                "payload": payload,
            }
            for key, day, payload in rows
        ]
        return await upsert_rows(
            self._session,
            GuideRecord,
            payloads,
            conflict_columns=["source", "workspace_id", "record_key"],
            update_columns=["recorded_for", "payload"],
            also_set={"captured_at": sa.func.now()},
        )

    async def load_run(self, *, source: str, workspace_id: uuid.UUID) -> GuideRun | None:
        """Return the watermark row for one source and tenant, if it exists."""
        result = await self._session.execute(
            sa.select(GuideRun).where(
                GuideRun.source == source, GuideRun.workspace_id == workspace_id
            )
        )
        return result.scalar_one_or_none()

    async def record_run(
        self,
        *,
        source: str,
        workspace_id: uuid.UUID,
        status: str,
        rows: int,
        cursor: str | None,
        captured_through: date | None,
        message: str = "",
    ) -> None:
        """Write where the walk got to, and how it went.

        Args:
            source: Feed key.
            workspace_id: Owning tenant.
            status: ``ok`` | ``empty`` | ``failed`` | ``skipped``.
            rows: Rows captured this run.
            cursor: New resume point, or the previous one when the run failed —
                the caller decides, because only it knows whether the failure
                left a gap behind the cursor.
            captured_through: Last fully covered day for a windowed walk.
            message: Short human-readable reason. Never a credential.
        """
        stmt = pg_insert(GuideRun).values(
            source=source,
            workspace_id=workspace_id,
            cursor=cursor,
            captured_through=captured_through,
            last_status=status,
            rows=rows,
            message=message[:500],
            last_run_at=sa.func.now(),
        )
        await self._session.execute(
            stmt.on_conflict_do_update(
                index_elements=["source", "workspace_id"],
                set_={
                    "cursor": stmt.excluded.cursor,
                    "captured_through": stmt.excluded.captured_through,
                    "last_status": stmt.excluded.last_status,
                    "rows": stmt.excluded.rows,
                    "message": stmt.excluded.message,
                    "last_run_at": sa.func.now(),
                },
            )
        )


__all__ = ["GuideRepository"]
