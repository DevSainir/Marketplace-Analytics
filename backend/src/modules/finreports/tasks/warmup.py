
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
from src.modules.finreports.repos.pnl.rollup import SettlementRollup

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


async def warm_settlement_rollup(*, workspace_id: uuid.UUID, name: str) -> None:
    """Build the settlement rollup for everything WB has ever settled here.

    The rollup repairs itself on read, so this is purely about WHO pays for the
    repair. A harvest that lands a new week leaves those days stale, and without
    this the next person to open «Вся история» pays the rebuild — measured at
    17 s on the largest workspace, which the browser gives up on before it
    finishes. Done here, the same work costs a background minute and every
    window opens warm.

    without it, so a failure is logged and swallowed rather than failing the
    harvest that already committed the data.
    """
    try:
        async with AsyncSessionLocal() as session:
            periods = await FinancialReportRepository(session).list_periods(
                workspace_id=workspace_id
            )
            if not periods:
                return
            date_from = min(df for (_rid, df, _dt) in periods)
            date_to = max(dt for (_rid, _df, dt) in periods)
            rebuilt = await SettlementRollup(session).ensure_fresh(
                workspace_id=workspace_id, date_from=date_from, date_to=date_to
            )
            await session.commit()
        logger.info(
            "finreports: warmed the settlement rollup for %s (%s..%s), %s days rebuilt.",
            name,
            date_from,
            date_to,
            rebuilt,
        )
    except Exception:
        logger.exception("finreports: failed to warm the settlement rollup for %s.", name)


async def warm_every_settlement_rollup() -> int:
    """Warm the rollup of every seller holding a report, one after another.

    Run when a worker starts. A deploy is when a migration may have cleared the
    rollup — it does whenever a money rule changes, because the stored sums
    were computed under the old one — and a worker starting is the first moment
    after that migration anything can rebuild it. Without this the rollup stays
    cold until a report lands or the 04:00 pass, and the first seller to open
    «Вся история» waits out the rebuild.

    Returns:
        How many sellers were warmed.
    """
    async with AsyncSessionLocal() as session:
        workspace_ids = await FinancialReportRepository(session).workspaces_with_reports()
    for workspace_id in workspace_ids:
        await warm_settlement_rollup(workspace_id=workspace_id, name=str(workspace_id))
    return len(workspace_ids)


