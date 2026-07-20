"""Data access for per-day SKU notes (a free-text comment plus its header).

Sole owner of SQL for ``monitoring.sku_day_comment`` — services depend on this
repository and never issue queries themselves. One row per day that has either
field; a day with neither is absent from
:meth:`SkuDayCommentRepository.map_for_window` (the service deletes such rows).

The header's day-boundary carry lives here as a single set-based statement
(:meth:`carry_headers_to_day`) rather than a per-SKU loop: it runs for the whole
catalogue once a day. All writes are idempotent.
"""

from __future__ import annotations

from datetime import date
from typing import Any, cast

from sqlalchemy import Date, Text, delete, func, literal, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.engine import CursorResult
from sqlalchemy.ext.asyncio import AsyncSession

from src.modules.monitoring.models.sku_day_comment import SkuDayComment


class SkuDayCommentRepository:
    """Reads and writes the per-day notes of one SKU (and the global carry)."""

    def __init__(self, session: AsyncSession) -> None:
        """Bind the repository to the request-scoped session.

        Args:
            session: The request's async SQLAlchemy session.
        """
        self._session = session

    async def map_for_window(
        self, *, nm_id: int, date_from: date, date_to: date
    ) -> dict[date, SkuDayComment]:
        """Return the SKU's note rows in the window, keyed by day.

        Args:
            nm_id: WB SKU identifier.
            date_from: Inclusive window start.
            date_to: Inclusive window end.

        Returns:
            ``{day: row}`` for the days that carry a note (others are absent).
        """
        stmt = select(SkuDayComment).where(
            SkuDayComment.nm_id == nm_id,
            SkuDayComment.comment_date >= date_from,
            SkuDayComment.comment_date <= date_to,
        )
        rows = (await self._session.execute(stmt)).scalars().all()
        return {row.comment_date: row for row in rows}

    async def get(self, *, nm_id: int, comment_date: date) -> SkuDayComment | None:
        """Return one day's note row, or ``None`` when the day has none.

        Args:
            nm_id: WB SKU identifier.
            comment_date: The day to read.
        """
        stmt = select(SkuDayComment).where(
            SkuDayComment.nm_id == nm_id,
            SkuDayComment.comment_date == comment_date,
        )
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def set(self, *, nm_id: int, comment_date: date, body: str, header: str) -> None:
        """Upsert one day's full note (last write wins).

        Args:
            nm_id: WB SKU identifier.
            comment_date: The day the note describes.
            body: The comment text (already stripped; may be empty).
            header: The header text (already stripped; may be empty).
        """
        stmt = (
            pg_insert(SkuDayComment)
            .values(nm_id=nm_id, comment_date=comment_date, body=body, header=header)
            .on_conflict_do_update(
                index_elements=[SkuDayComment.nm_id, SkuDayComment.comment_date],
                set_={"body": body, "header": header, "updated_at": func.now()},
            )
        )
        await self._session.execute(stmt)
        # The session runs with autoflush disabled — flush so a follow-up read
        # in the same request sees the write before the request-level commit.
        await self._session.flush()

    async def clear(self, *, nm_id: int, comment_date: date) -> None:
        """Delete one day's note row (no-op when the day has none).

        Args:
            nm_id: WB SKU identifier.
            comment_date: The day to un-note.
        """
        stmt = delete(SkuDayComment).where(
            SkuDayComment.nm_id == nm_id,
            SkuDayComment.comment_date == comment_date,
        )
        await self._session.execute(stmt)
        await self._session.flush()

    async def carry_headers_to_day(self, *, source_day: date, target_day: date) -> int:
        """Copy every SKU's ``source_day`` header onto ``target_day``.

        The day-boundary carry: when a new day starts, each SKU's running title
        continues onto it as a REAL row, so it can then be edited or cleared on
        that day alone. Only non-empty headers carry (a SKU whose previous day
        had no header starts the new day blank), and a target day that already
        has a header is never overwritten — the carry seeds a day, it does not
        re-assert itself over what someone has since written.

        Args:
            source_day: The day to copy headers from (the previous day).
            target_day: The day to copy them onto (the new day).

        Returns:
            The number of headers carried.
        """
        source = select(
            SkuDayComment.nm_id,
            literal(target_day, Date).label("comment_date"),
            # The new day starts with the title only: the comment is per-day
            # and never carries.
            literal("", Text).label("body"),
            SkuDayComment.header,
        ).where(
            SkuDayComment.comment_date == source_day,
            SkuDayComment.header != "",
        )
        insert_stmt = pg_insert(SkuDayComment).from_select(
            ["nm_id", "comment_date", "body", "header"], source
        )
        stmt = insert_stmt.on_conflict_do_update(
            index_elements=[SkuDayComment.nm_id, SkuDayComment.comment_date],
            set_={"header": insert_stmt.excluded.header, "updated_at": func.now()},
            # Only seed a header that is not there yet. A day that already
            # carries one keeps it (the carry must never overwrite a title
            # someone wrote on the new day before this pass ran), and a
            # comment-only row still receives it.
            where=SkuDayComment.header == "",
        )
        # DML always yields a CursorResult; only that one carries `rowcount`.
        result = cast("CursorResult[Any]", await self._session.execute(stmt))
        await self._session.flush()
        return int(result.rowcount or 0)
