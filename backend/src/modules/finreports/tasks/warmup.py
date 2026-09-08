
Split out of :mod:`.harvest` because it is a different responsibility with a
different failure rule: the harvest must fail loudly and this must never fail at
all — it only makes an already-correct answer faster to fetch. Keeping the two
apart is also what stops a warming bug from being able to lose a settlement.
"""

from __future__ import annotations

import uuid

from src.core.config import settings
from src.core.database import AsyncSessionLocal
from src.core.logging import get_logger
from src.core.redis import get_redis
from src.modules.finreports.repos import (
    FinancialReportRepository,
    LogisticsTransactionRepository,
)

logger = get_logger(__name__)



    the same for every viewer until the next harvest, so computing it once here,
    off the request path, means the first user to open it hits a warm cache
    instead of a 30-60 s recompute. The window is the full report span
    (min..max period), matching what the frontend requests for «за всю историю»
    so the cache key lines up.

    A warming failure must never fail the harvest that produced the data, so
    every error is logged and swallowed.
    """
    if settings.finreports_summary_cache_ttl_seconds <= 0:
        return
    try:
        async with AsyncSessionLocal() as session:
            report_repo = FinancialReportRepository(session)
            periods = await report_repo.list_periods(workspace_id=workspace_id)
            if not periods:
                return
            date_from = min(df for (_rid, df, _dt) in periods)
            date_to = max(dt for (_rid, _df, dt) in periods)
                transaction_repo=LogisticsTransactionRepository(session),
                report_repo=report_repo,
                    get_redis(), ttl_seconds=settings.finreports_summary_cache_ttl_seconds
                ),
            )
                workspace_id=workspace_id, date_from=date_from, date_to=date_to
            )
        logger.info(
            name,
            date_from,
            date_to,
        )
    except Exception:
        # Warming is best-effort — a failure here must never fail the harvest
        # that already committed the data it warms.


