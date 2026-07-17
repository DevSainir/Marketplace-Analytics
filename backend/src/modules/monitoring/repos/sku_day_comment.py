"""Data access for per-day SKU comments (free-text notes).

Sole owner of SQL for ``monitoring.sku_day_comment`` — services depend on this
repository and never issue queries themselves. One row per commented SKU-day;
saving a blank note deletes the row, so an un-commented day is simply absent
from :meth:`SkuDayCommentRepository.map_for_window`. Both writes are idempotent.
"""

from __future__ import annotations

from datetime import date

from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from src.modules.monitoring.models.sku_day_comment import SkuDayComment


class SkuDayCommentRepository:
    """Reads and writes the per-day comment notes of one SKU."""

    def __init__(self, session: AsyncSession) -> None:
        """Bind the repository to the request-scoped session.

        Args:
            session: The request's async SQLAlchemy session.
        """
        self._session = session

    async def map_for_window(
        self, *, nm_id: int, date_from: date, date_to: date
    ) -> dict[date, str]:
        """Return the SKU's comments in the window, keyed by day.

        Args:
            nm_id: WB SKU identifier.
            date_from: Inclusive window start.
            date_to: Inclusive window end.

        Returns:
            ``{day: body}`` for the commented days only (un-commented days are
            absent, never mapped to an empty string).
        """
        stmt = select(SkuDayComment.comment_date, SkuDayComment.body).where(
            SkuDayComment.nm_id == nm_id,
            SkuDayComment.comment_date >= date_from,
            SkuDayComment.comment_date <= date_to,
        )
        rows = (await self._session.execute(stmt)).all()
        return {row.comment_date: row.body for row in rows}

    async def set(self, *, nm_id: int, comment_date: date, body: str) -> None:
        """Upsert one day's comment body (last write wins).

        Args:
            nm_id: WB SKU identifier.
            comment_date: The day the note describes.
            body: The note text (assumed already stripped and non-empty).
        """
        stmt = (
            pg_insert(SkuDayComment)
            .values(nm_id=nm_id, comment_date=comment_date, body=body)
            .on_conflict_do_update(
                index_elements=[SkuDayComment.nm_id, SkuDayComment.comment_date],
                set_={"body": body, "updated_at": func.now()},
            )
        )
        await self._session.execute(stmt)
        # The session runs with autoflush disabled — flush so a follow-up read
        # in the same request sees the write before the request-level commit.
        await self._session.flush()

    async def clear(self, *, nm_id: int, comment_date: date) -> None:
        """Delete one day's comment (no-op when the day has none).

        Args:
            nm_id: WB SKU identifier.
            comment_date: The day to un-comment.
        """
        stmt = delete(SkuDayComment).where(
            SkuDayComment.nm_id == nm_id,
            SkuDayComment.comment_date == comment_date,
        )
        await self._session.execute(stmt)
        await self._session.flush()
