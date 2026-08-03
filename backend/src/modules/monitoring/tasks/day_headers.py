"""The day-boundary carry of the matrix note headers onto the new day."""

from __future__ import annotations

from datetime import timedelta

from src.core.celery_app import celery_app
from src.core.database import AsyncSessionLocal
from src.core.logging import get_logger
from src.core.tasks import run_task
from src.core.timeutils import operating_today
from src.modules.monitoring.repos import SkuDayCommentRepository
from src.modules.monitoring.tasks.common import _TASK_RETRY_KWARGS

logger = get_logger(__name__)


@celery_app.task(  # type: ignore[untyped-decorator]
    name="monitoring.carry_day_headers",
    bind=False,
    **_TASK_RETRY_KWARGS,
)
def carry_day_headers() -> dict[str, int]:
    """Scheduled entrypoint: carry the previous day's note headers onto the new one.

    The matrix's notes row has two fields per day: a free-text comment, which
    is purely per-day, and a header — a running title that should continue onto
    each new day without being retyped. That continuation happens HERE, once,
    when the day rolls over, and it writes a real row for the new day. Making
    the carry a stored fact rather than a live inheritance is what lets a
    manager then edit or clear any single day's header without disturbing the
    days around it.

    The source is STRICTLY the previous day — never the last day that happened
    to have a title. A blank header yesterday means the new day starts blank,
    even when an older day still carries one.

    Dated on the TEAM's clock (:func:`operating_today`), not WB's: the day the
    managers see turn over at 00:00 Bishkek is the one that should receive the
    title, and the beat fires at exactly that instant (21:00 MSK).

    A day that already has a header is never overwritten, so re-running the
    task is a no-op.

    Returns:
        ``{"headers_carried": n}``.
    """

    async def _run() -> dict[str, int]:
        today = operating_today()
        async with AsyncSessionLocal() as session:
            repo = SkuDayCommentRepository(session)
            carried = await repo.carry_headers_to_day(
                source_day=today - timedelta(days=1), target_day=today
            )
            await session.commit()
        logger.info("Carried %d note header(s) onto %s.", carried, today.isoformat())
        return {"headers_carried": carried}

    return run_task(_run())
