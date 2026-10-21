"""One lock between rebuilding a workspace's rollup and rewriting its detail.

The rollup proves a day by row count, and the detail upsert deletes the rollup
of every day it touches so a rewrite the count cannot see is rebuilt. That
leaves one interleaving: a read's rebuild takes its snapshot of the detail,
an ingest commits new figures and deletes the rollup days — which the rebuild
has not committed yet, so there is nothing to delete — and then the rebuild
commits the OLD figures. Same row count, so they are never rebuilt again.

A transaction-scoped advisory lock closes it. Rebuilds take it SHARED, so reads
never wait on each other; an ingest takes it EXCLUSIVE, so it waits for a
rebuild in flight and a rebuild waits for an ingest in flight. Either order
then ends with the rollup describing the committed detail.
"""

from __future__ import annotations

import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

#: The advisory-lock namespace (the first of the two int4 keys), so these locks
#: cannot collide with any other advisory lock in the database.
_ROLLUP_LOCK_CLASS = 7_300_001


async def hold_rollup_lock(session: AsyncSession, workspace_id: uuid.UUID, *, shared: bool) -> None:
    """Take the workspace's rollup lock until the session's transaction ends.

    Args:
        session: The session whose transaction holds the lock.
        workspace_id: Whose rollup.
        shared: ``True`` for a rebuild, ``False`` for a detail write.
    """
    lock = func.pg_advisory_xact_lock_shared if shared else func.pg_advisory_xact_lock
    await session.execute(select(lock(_ROLLUP_LOCK_CLASS, func.hashtext(str(workspace_id)))))


__all__ = ["hold_rollup_lock"]
