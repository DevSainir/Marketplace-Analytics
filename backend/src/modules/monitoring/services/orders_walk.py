"""Walking a кабинет's whole ordering history, one page at a time.

Why this lane exists at all: «Воронка продаж» is WB's analytics surface, and it
answers for a rolling window — in practice a кабинет has funnel days from the
moment this service started harvesting it, 17.07.2025 for the oldest one, while
its settlements go back to 2024. `supplier/orders` has no such horizon: it
answers from any `dateFrom`, so this is the only way «Заказы» can cover the same
period as the money.

Shaped like the other lanes — one bounded step, report, return — but the unit is
a PAGE rather than a day, because the feed paginates by `lastChangeDate` and
serves up to 80 000 lines at a time. A кабинет's whole history is a handful of
pages, so the walk is short; what it must not do is hold all of them at once,
which is why the client hands back one page and this persists it before asking
for the next.

Progress is reported in DAYS COVERED rather than pages: pages are invisible to
the seller and their number is unknowable in advance, while «история заказов
собрана с 11.07.2024» is the thing being waited for.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, time

from src.core.config import settings
from src.core.database import AsyncSessionLocal
from src.core.logging import get_logger
from src.core.timeutils import moscow_today
from src.integrations.wildberries import build_statistics_client
from src.modules.monitoring.repos import OrderRepository
from src.modules.monitoring.services.backfill import build_ingestion_service
from src.modules.workspaces.contract import LaneStep, WorkspaceTokenBundle

logger = get_logger(__name__)

#: Where a walk with no cursor starts. Before WB existed in its current form, so
#: it is "everything" without pretending to know when the seller began: the feed
#: simply answers with their first order.
ORDERS_EPOCH = date(2019, 1, 1)


def _resume_from(cursor: str | None) -> datetime:
    """Turn a stored cursor into the `dateFrom` of the next request."""
    if not cursor:
        return datetime.combine(ORDERS_EPOCH, time.min)
    return datetime.fromisoformat(cursor)


async def advance_orders(tokens: WorkspaceTokenBundle, *, cursor: str | None) -> LaneStep:
    """Fetch one page of the orders feed, persist it, and say where it got to.

    Args:
        tokens: The workspace's decrypted credentials.
        cursor: ISO `lastChangeDate` to resume from; ``None`` starts at
            :data:`ORDERS_EPOCH`, which is "from the seller's first order".

    Returns:
        The step's outcome. ``finished`` is set when WB answered with less than
        a full page — there is nothing after it.
    """
    if not tokens.statistics:
        return LaneStep(0, 0, None, True, "Нет токена «Статистика» — заказы пропущены.")

    since = _resume_from(cursor)
    async with build_statistics_client(settings, token=tokens.statistics) as client:
        page = await client.fetch_orders_page(changed_since=since)

    async with AsyncSessionLocal() as session:
        rows = await build_ingestion_service(session).ingest_orders(page.records)
        await session.commit()

    async with AsyncSessionLocal() as session:
        first, last = await OrderRepository(session).covered_span(workspace_id=tokens.workspace_id)

    next_cursor = page.next_cursor.isoformat() if page.next_cursor else None
    finished = next_cursor is None
    # Days between the seller's first order and today is the whole job; days
    # between it and the newest one stored is how much of it is done. Both are
    # zero until the first page lands, which is honest — nothing is known about
    # the history before WB has answered once.
    total = (moscow_today() - first).days + 1 if first else 0
    done = (last - first).days + 1 if first and last else 0
    message = (
        f"История заказов собрана с {first:%d.%m.%Y}."
        if finished and first
        else f"Загружено заказов: {rows}."
    )
    logger.info(
        "orders walk for %s: %d rows, cursor=%s, finished=%s",
        tokens.workspace_id,
        rows,
        next_cursor,
        finished,
    )
    return LaneStep(min(done, total), total, next_cursor, finished, message)


async def orders_span(workspace_id: uuid.UUID) -> tuple[date | None, date | None]:
    """``(first, last)`` ordered day on record — what the lane has collected."""
    async with AsyncSessionLocal() as session:
        return await OrderRepository(session).covered_span(workspace_id=workspace_id)


__all__ = ["ORDERS_EPOCH", "advance_orders", "orders_span"]
