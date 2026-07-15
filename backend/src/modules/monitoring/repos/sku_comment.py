"""Data access for per-SKU comments (free-text notes).

Sole owner of SQL for ``monitoring.sku_comment`` — services depend on this
repository and never issue queries themselves. One row per SKU that has a note;
saving a blank note deletes the row, so ``get`` returns ``None`` for an
un-commented SKU. Both writes are idempotent.
"""

from __future__ import annotations

from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from src.modules.monitoring.models.sku_comment import SkuComment


class SkuCommentRepository:
    """Reads and writes the per-SKU comment note."""

    def __init__(self, session: AsyncSession) -> None:
        """Bind the repository to the request-scoped session.

        Args:
            session: The request's async SQLAlchemy session.
        """
        self._session = session

    async def get(self, *, nm_id: int) -> str | None:
        """Return the SKU's comment body, or ``None`` when it has no note.

        Args:
            nm_id: WB SKU identifier.

        Returns:
            The comment text, or ``None`` when the SKU is un-commented.
        """
        stmt = select(SkuComment.body).where(SkuComment.nm_id == nm_id)
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def set(self, *, nm_id: int, body: str) -> None:
        """Upsert the SKU's comment body (last write wins).

        Args:
            nm_id: WB SKU identifier.
            body: The note text (assumed already stripped and non-empty).
        """
        stmt = (
            pg_insert(SkuComment)
            .values(nm_id=nm_id, body=body)
            .on_conflict_do_update(
                index_elements=[SkuComment.nm_id],
                set_={"body": body, "updated_at": func.now()},
            )
        )
        await self._session.execute(stmt)
        # The session runs with autoflush disabled — flush so a follow-up read
        # in the same request sees the write before the request-level commit.
        await self._session.flush()

    async def clear(self, *, nm_id: int) -> None:
        """Delete the SKU's comment (no-op when it has none).

        Args:
            nm_id: WB SKU identifier.
        """
        stmt = delete(SkuComment).where(SkuComment.nm_id == nm_id)
        await self._session.execute(stmt)
        await self._session.flush()
