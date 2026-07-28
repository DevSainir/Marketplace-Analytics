"""Celery background tasks for the Users module (auth housekeeping)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from src.core.celery_app import celery_app
from src.core.database import AsyncSessionLocal, run_task
from src.core.logging import get_logger
from src.modules.users.repos import RefreshTokenRepository

logger = get_logger(__name__)

#: How long expired refresh-token rows are retained before deletion. The grace
#: window keeps recent lineage data available for breach forensics (the family
#: tree of a replayed token) without letting the table grow forever.
_EXPIRED_TOKEN_RETENTION_DAYS: int = 30


@celery_app.task(  # type: ignore[untyped-decorator]
    name="auth.purge_expired_refresh_tokens", bind=False
)
def purge_expired_refresh_tokens() -> int:
    """Scheduled entrypoint: delete long-expired refresh-token rows.

    Every login and refresh inserts a permanent ``auth.refresh_tokens`` row;
    without this job the table grows without bound. Rows are deleted once they
    have been expired for :data:`_EXPIRED_TOKEN_RETENTION_DAYS`.

    Returns:
        The number of rows deleted.
    """

    async def _run() -> int:
        cutoff = datetime.now(UTC) - timedelta(days=_EXPIRED_TOKEN_RETENTION_DAYS)
        async with AsyncSessionLocal() as session:
            deleted = await RefreshTokenRepository(session).delete_expired(before=cutoff)
            await session.commit()
        return deleted

    deleted = run_task(_run())
    logger.info("Purged %d expired refresh-token rows.", deleted)
    return deleted
