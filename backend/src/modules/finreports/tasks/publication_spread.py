"""How far apart sellers receive the same settlement period.

One measurement, recorded to answer one question: **is shared discovery worth
building?**

On the day WB forms a report, every seller currently spends its own
quarter-hourly requests asking the same thing — «are you serving it yet» — and
one seller's answer could serve the whole fleet. At five кабинеты that saves a
handful of requests; at fifty it is the difference between a ceiling of
eighteen sellers per egress address and one of sixty (see
``docs/finreports/RATE_LIMIT_EXPERIMENT.md`` for the arithmetic).

It is only true if WB publishes to every seller at once, and **nothing we hold
says whether it does.** So this measures it before anything is built on it.

What is measured is an UPPER BOUND on WB's own spread, and the distinction
matters for reading the result. The figure is taken from our own
``harvested_at``, so it includes our probe cadence, our rate budget, and any
tick a seller missed. A distribution piled into the bottom bucket is therefore
conclusive — WB published simultaneously and we saw it happen — while a wide
one is ambiguous and has to be read against the logs, which name the seller.

The query costs one indexed read per harvest and no WB request.
"""

from __future__ import annotations

import uuid
from datetime import date

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.logging import get_logger
from src.core.observability.metrics import SETTLEMENT_PUBLICATION_SPREAD
from src.modules.finreports.models import FinancialReport

logger = get_logger(__name__)


async def record_publication_spread(
    session: AsyncSession, *, workspace_id: uuid.UUID, period_end: date, name: str
) -> float | None:
    """Record how long after the first seller this one received ``period_end``.

    Deliberately cross-tenant, and deliberately not exposed to anyone: the
    question is about WB's behaviour towards the fleet, which no single
    tenant's rows can answer. The metric carries no tenant label — `/metrics`
    has no tenancy check because it has no tenant — and the log line, which
    does carry ``workspace_id``, is where the per-seller detail goes.

    Args:
        session: An open session. The caller owns the transaction; nothing
            here writes.
        workspace_id: The seller that just received the period.
        period_end: ``date_to`` of the period, which is what identifies it
            across sellers — ``report_id`` does not, since WB numbers them per
            seller.
        name: The seller's name, for the log line only.

    Returns:
        The lag in hours, or ``None`` when it cannot be computed — this seller
        is the first to hold the period, or holds no row for it at all. Both
        are ordinary: the first seller has nothing to be later than.
    """
    rows = (
        await session.execute(
            select(FinancialReport.workspace_id, FinancialReport.harvested_at).where(
                FinancialReport.date_to == period_end
            )
        )
    ).all()
    if not rows:
        return None
    first = min(row.harvested_at for row in rows)
    mine = next((row.harvested_at for row in rows if row.workspace_id == workspace_id), None)
    if mine is None:
        return None
    lag_hours = float((mine - first).total_seconds()) / 3600.0
    SETTLEMENT_PUBLICATION_SPREAD.observe(max(lag_hours, 0.0))
    logger.info(
        "finreports: %s received period ending %s %.2f h after the first of %d seller(s).",
        name,
        period_end,
        lag_hours,
        len(rows),
    )
    return lag_hours


__all__ = ["record_publication_spread"]
