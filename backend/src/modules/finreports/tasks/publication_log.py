"""Note the moment WB's API first names a report — our own publication statistics.

Called with every answer ``sales-reports/list`` gives a harvest tick, weekly and
daily lanes alike. It costs no WB request: the list was already fetched for the
gate, and this only compares it with what we hold.

Two instants are kept per report, because one would be a guess. A tick learns
that a report is listed NOW; it cannot know how long before that WB started
naming it. The previous answer that did not name it bounds that from below, so
each row says «reached the API between A and B». The cadence sets the width:
15 minutes on the day a weekly report is formed, an hour otherwise.

Never raises. This is measurement riding on the harvest, and a Redis or
database hiccup here must not cost a tick the report it was about to fetch.
"""

from __future__ import annotations

import uuid
from collections.abc import Collection, Sequence
from datetime import UTC, datetime

from redis.asyncio import Redis

from src.core.database import AsyncSessionLocal
from src.core.logging import get_logger
from src.core.redis import get_redis
from src.integrations.wildberries.schemas import WBFinanceReportHeader
from src.modules.finreports.constants import LIST_ANSWERED_KEY, LIST_ANSWERED_TTL_SECONDS
from src.modules.finreports.repos import ReportPublicationRepository

logger = get_logger(__name__)


async def _swap_answered_mark(
    redis: Redis, *, workspace_id: uuid.UUID, period: str, answered_at: datetime
) -> datetime | None:
    """Store this answer's instant and return the previous one, if any.

    ``SET … GET`` in one command, so two ticks cannot both read the same prior
    mark. Fails to ``None`` — a missing lower bound, which the row records as
    such rather than inventing one.
    """
    key = LIST_ANSWERED_KEY.format(period=period, workspace_id=workspace_id)
    try:
        previous = await redis.set(
            key, answered_at.isoformat(), ex=LIST_ANSWERED_TTL_SECONDS, get=True
        )
    except Exception:
        logger.warning("finreports: could not read the last list answer's time.", exc_info=True)
        return None
    if previous is None:
        return None
    try:
        raw = previous.decode() if isinstance(previous, bytes) else str(previous)
        return datetime.fromisoformat(raw)
    except ValueError:
        return None


async def log_first_listings(
    *,
    workspace_id: uuid.UUID,
    name: str,
    period: str,
    listed: Sequence[WBFinanceReportHeader],
    held: Collection[int],
    answered_at: datetime | None = None,
    redis: Redis | None = None,
) -> list[int]:
    """Record every listed report this workspace does not hold and the log lacks.

    Only reports we do not hold are candidates. A held report was listed some
    time before this log existed, and writing it now would stamp an old report
    with today's date — the one error that would make the statistics lie.

    Args:
        workspace_id: Tenancy scope.
        name: The seller, for the log line.
        period: ``weekly`` or ``daily`` — which list answered.
        listed: WB's whole answer, even when empty: an empty answer is still the
            lower bound for the next report.
        held: ``reportId`` of every report already on file for this lane.
        answered_at: When the answer arrived; now by default.
        redis: The client holding the answered-at mark; the shared one by default.

    Returns:
        The ids first seen by this answer, or ``[]`` when none were or when
        writing failed.
    """
    answered_at = answered_at or datetime.now(UTC)
    prior = await _swap_answered_mark(
        redis or get_redis(), workspace_id=workspace_id, period=period, answered_at=answered_at
    )
    candidates = [header for header in listed if header.report_id not in held]
    if not candidates:
        return []
    try:
        async with AsyncSessionLocal() as session:
            first_seen = await ReportPublicationRepository(session).record_first_listings(
                workspace_id=workspace_id,
                period=period,
                headers=candidates,
                listed_at=answered_at,
                prior_list_at=prior,
            )
            await session.commit()
    except Exception:
        logger.warning(
            "finreports: could not log when WB first listed a report; the harvest carries on.",
            exc_info=True,
        )
        return []
    headers = {header.report_id: header for header in candidates}
    for report_id in first_seen:
        header = headers[report_id]
        logger.info(
            "finreports: WB's API first listed %s report %d (%s..%s, created %s) for %s at %s; "
            "the previous answer without it was at %s.",
            period,
            report_id,
            header.date_from,
            header.date_to,
            header.create_date,
            name,
            answered_at.isoformat(),
            prior.isoformat() if prior else "unknown",
        )
    return first_seen


__all__ = ["log_first_listings"]
