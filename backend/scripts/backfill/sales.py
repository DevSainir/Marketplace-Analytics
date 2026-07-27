"""Backfill phase: the account-wide sale/return feed.

``supplier/sales`` takes a ``dateFrom`` and no SKU filter, so this phase is
account-wide by construction and sits on the harshest limiter WB operates.
"""

from __future__ import annotations

from datetime import date, timedelta

from sqlalchemy import func, select

from scripts.backfill.common import PhaseTotals, _build_service
from src.core.config import settings
from src.core.database import AsyncSessionLocal
from src.core.exceptions import IntegrationError
from src.core.logging import get_logger
from src.integrations.wildberries import WBStatisticsClient
from src.modules.monitoring.models import SaleRecord
from src.modules.workspaces.contract import WorkspaceTokenBundle

logger = get_logger(__name__)


# --------------------------------------------------------------------------- #
# Phase 1 — sale/return records (statistics API)
# --------------------------------------------------------------------------- #
async def _backfill_sales(
    tokens: WorkspaceTokenBundle, *, nm_ids: list[int], sales_from: date, totals: PhaseTotals
) -> None:
    """One deep ``supplier/sales`` pull (full visible window in a single call).

    The nightly harvest calls this feed with ``changed_since = window start``
    (7 days), which only picks up RECENTLY CHANGED records — months-old sales
    never re-enter it, so history must be pulled once with an old ``dateFrom``.

    Skips itself when the DB already holds sales older than the requested
    horizon (± a month) — the marker that a previous backfill succeeded. On
    the ~1-request-per-2-hours limiter the client fails fast; the phase is
    then simply reported as pending for the next run.
    """
    async with AsyncSessionLocal() as session:
        oldest = await session.scalar(
            select(func.min(SaleRecord.sale_date)).where(SaleRecord.nm_id.in_(nm_ids))
        )
    if oldest is not None and oldest <= sales_from + timedelta(days=30):
        logger.info(
            "Sales history already reaches %s (<= %s + 30d); skipping the deep pull.",
            oldest,
            sales_from,
        )
        return

    if not tokens.statistics:
        logger.warning("Workspace '%s' has no statistics token; sales skipped.", tokens.name)
        return

    async with WBStatisticsClient(settings, token=tokens.statistics) as client:
        try:
            records = await client.fetch_sales(changed_since=sales_from)
        except IntegrationError as exc:
            logger.warning(
                "Deep sales pull unavailable now (%s). The ~2h statistics slot is "
                "likely spent — re-run the script later to pick this phase up.",
                exc,
            )
            return
        # Fetch + ingest stay in ONE process run: losing the payload after a
        # successful fetch would waste a whole 2-hour rate-limit slot.
        async with AsyncSessionLocal() as session:
            service = _build_service(session)
            count = await service.ingest_sales(records)
            await session.commit()
    totals.add("sales_rows", count)
    logger.info("Sales backfill ingested %d records (dateFrom=%s).", count, sales_from)
