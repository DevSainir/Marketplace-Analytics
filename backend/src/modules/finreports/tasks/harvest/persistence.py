"""Where one workspace's harvest becomes durable: the watermark, then the rows.

Two writes, each in its own transaction and each with a reason for being
separate. The watermark records how far the settlement walk got and is written
the moment the walk ends, because the walk has already committed its pages; the
row commit is the all-or-nothing one the read phase feeds.

The settlement pages themselves are committed by
:mod:`src.modules.finreports.tasks.settlement`, a week at a time — a settlement
window is too large to hold, and waiting between weeks is the one thing an open
transaction may not do.
"""

from __future__ import annotations

import uuid
from datetime import date

from src.core.database import AsyncSessionLocal
from src.modules.finreports.repos import (
    FinancialReportRepository,
    SettlementWatermarkRepository,
)
from src.modules.finreports.tasks.ingestion_factory import build_ingestion
from src.modules.finreports.tasks.spans import settlement_frontier


async def advance_watermark(*, workspace_id: uuid.UUID, completed_through: date) -> None:
    """Move the settlement watermark to what is both walked and covered.

    The watermark moves on what the walk FINISHED **and** on what a report
    actually covers — the same `settlement_frontier` the gate reads, applied
    here so the mark is never poisoned in the first place rather than only
    corrected when read.

    Reading the minimum is not enough on its own, and NEVA proved it on
    2026-09-14: an earlier tick had already marched this mark to 13.09 over days
    WB had published nothing for, and once a later walk wrote the week's header
    from its first page, coverage reached 13.09 too. Both dates then said 13.09
    over a week held one page deep, `min` of them said 13.09, and the incomplete
    week became invisible — a header claiming days we do not hold is exactly the
    2026-09-07 failure, arrived at from the other side.

    Written as the minimum, neither can be poisoned by the other: an empty walk
    cannot outrun the coverage, and a half-walked week cannot outrun the walk. A
    workspace with no report at all is unconstrained — there is no coverage to
    be behind, and the mark is what keeps its next tick cheap.

    Args:
        workspace_id: The workspace whose mark is moving.
        completed_through: The last day the walk finished.
    """
    async with AsyncSessionLocal() as session:
        covered_through = await FinancialReportRepository(session).latest_settled_date(
            workspace_id=workspace_id
        )
        settled = settlement_frontier(watermark=completed_through, covered_through=covered_through)
        if settled is not None:
            await SettlementWatermarkRepository(session).advance_to(
                workspace_id=workspace_id, day=settled
            )
        await session.commit()


async def persist_sources(
) -> dict[str, int]:
    """Write every non-settlement source in one transaction.

    All of it or none of it: the four ingests share a session and a single
    commit, so a failure part-way through leaves no half-harvested day behind.

    Args:
        sources: What the read phase produced.
        workspace_id: The tenant being written for.
        on_date: Snapshot day for the baseline (Moscow time).

    Returns:
        ``penalties``, ``measurements``.
    """
    async with AsyncSessionLocal() as session:
        ingestion = build_ingestion(session)
        counts = {
            "baselines": await ingestion.ingest_baselines(
                sources.cards, workspace_id=workspace_id, snapshot_date=on_date
            ),
                sources.penalties, workspace_id=workspace_id
            ),
                sources.measurements, workspace_id=workspace_id
            ),
        }
        await session.commit()
    return counts


__all__ = ["advance_watermark", "persist_sources"]
