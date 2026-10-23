"""Warming the settlement rollup after a harvest or a deploy that changed it.

Split out of :mod:`.harvest` because it is a different responsibility with a
different failure rule: the harvest must fail loudly and this must never fail at
all — it only makes an already-correct answer faster to fetch. Keeping the two
apart is also what stops a warming bug from being able to lose a settlement.
"""

from __future__ import annotations

import uuid

from src.core.database import AsyncSessionLocal
from src.core.logging import get_logger
from src.modules.finreports.repos import FinancialReportRepository
from src.modules.finreports.repos.pnl.rollup import SettlementRollup

logger = get_logger(__name__)


async def warm_settlement_rollup(*, workspace_id: uuid.UUID, name: str) -> None:
    """Build the settlement rollup for everything WB has ever settled here.

    The rollup repairs itself on read, so this is purely about WHO pays for the
    repair. A harvest that lands a new week leaves those days stale, and without
    this the next person to open "All time" pays the rebuild — measured at
    17 s on the largest workspace, which the browser gives up on before it
    finishes. Done here, the same work costs a background minute and every
    window opens warm.

    It is best-effort: the figures are correct with or without it, so a failure
    is logged and swallowed rather than failing the harvest that already
    committed the data.
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
    "All time" waits out the rebuild.

    Returns:
        How many sellers were warmed.
    """
    async with AsyncSessionLocal() as session:
        workspace_ids = await FinancialReportRepository(session).workspaces_with_reports()
    for workspace_id in workspace_ids:
        await warm_settlement_rollup(workspace_id=workspace_id, name=str(workspace_id))
    return len(workspace_ids)


__all__ = ["warm_every_settlement_rollup", "warm_settlement_rollup"]
