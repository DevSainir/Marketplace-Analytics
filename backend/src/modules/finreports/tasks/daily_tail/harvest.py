"""Covering the days between the settled frontier and yesterday.

The fetching half of the provisional tail; the day-later check is in
:mod:`.verify`. Why the lane exists at all, and why it books itself instead of
writing a weekly header, is in the package docstring.
"""

from __future__ import annotations

import uuid
from datetime import date, timedelta

from src.core.database import AsyncSessionLocal
from src.core.exceptions import IntegrationError
from src.core.locks import single_flight
from src.core.logcontext import bind_workspace
from src.core.logging import get_logger
from src.core.redis import get_redis
from src.core.timeutils import moscow_today
from src.integrations.wildberries.schemas import WBFinanceReportHeader
from src.modules.finreports.constants import (
    DAILY_TAIL_LOCK_PREFIX,
    DAILY_TAIL_LOOKBACK_DAYS,
    HARVEST_LOCK_TTL_SECONDS,
)
from src.modules.finreports.repos import DailySettlementRepository, ListedTotals
from src.modules.finreports.tasks.daily_tail.common import (
    list_daily,
    listed_totals,
    settled_frontier,
)
from src.modules.finreports.tasks.ingestion_factory import build_ingestion
from src.modules.finreports.tasks.settlement import (
    MissingReport,
    ingest_rows_only,
    walk_settlement_reports,
)
from src.modules.workspaces.contract import (
    WorkspaceTokenBundle,
    load_workspace_token_bundle,
)

logger = get_logger(__name__)

#: Zeroed result shape, so a locked-out run reports the keys a full one does.
_EMPTY: dict[str, int] = {
    "reports": 0,
    "rows": 0,
    "reports_failed": 0,
    "workspaces_skipped": 0,
    "skipped_locked": 0,
}


async def harvest_daily_tail(*, workspace_id: uuid.UUID) -> dict[str, int]:
    """Cover one workspace's days between the settled frontier and yesterday.

    **Scoped only, and that is deliberate.** The fleet sweep is not here: it runs
    inside the settled harvest's own tick (:mod:`.harvest.fleet`), after that
    workspace's weekly walk, so the two lanes share one lock, one pass over the
    sellers and one order of spend on the same WB buckets. A second way to sweep
    the fleet would be a second place for those decisions to drift.

    What is left is the path «Обновить» takes. It cannot go through the harvest's
    lock — a click landing while the sweep runs would answer «already running»
    and fetch nothing, which is the case the button exists for — so it takes a
    key of its own. It spends one seller's budget, WB's buckets are per token,
    and pacing is the rate gate's job; the lock only has to stop two clicks on
    the same кабинет walking it twice.

    Args:
        workspace_id: The workspace to cover. Required: a click by one tenant
            must not spend every other tenant's WB budget.

    Returns:
        ``reports`` daily reports completed, ``rows`` settlement rows written,
        ``reports_failed`` reports that stopped early, ``workspaces_skipped`` 1
        when there was nothing to do, and ``skipped_locked`` 1 when an identical
        run was already in flight.
    """
    async with single_flight(
        f"{DAILY_TAIL_LOCK_PREFIX}{workspace_id}",
        ttl_seconds=HARVEST_LOCK_TTL_SECONDS,
        redis=get_redis(),
    ) as acquired:
        if not acquired:
            logger.info("finreports: a daily tail run already holds %s — skipping.", workspace_id)
            return dict(_EMPTY, skipped_locked=1)
        async with AsyncSessionLocal() as session:
            bundle = await load_workspace_token_bundle(session, workspace_id)
        if bundle is None or not bundle.finance:
            return dict(_EMPTY, workspaces_skipped=1)
        return await tail_one_workspace(tokens=bundle, today=moscow_today())


async def tail_one_workspace(*, tokens: WorkspaceTokenBundle, today: date) -> dict[str, int]:
    """Harvest one workspace's daily tail — the unit both callers share.

    Called per seller by the settled harvest's fleet tick, and by
    :func:`harvest_daily_tail` for «Обновить». Takes no lock of its own: each
    caller holds the one appropriate to its scope.

    Args:
        tokens: The workspace's decrypted WB credentials.
        today: Today in Moscow time.

    Returns:
        A counts fragment shaped like :data:`_EMPTY`.
    """
    bind_workspace(tokens.workspace_id)
    frontier = await settled_frontier(workspace_id=tokens.workspace_id)
    span = _tail_span(frontier=frontier, today=today)
    if span is None:
        return dict(_EMPTY, workspaces_skipped=1)
    async with AsyncSessionLocal() as session:
        held = await DailySettlementRepository(session).held_ids(
            workspace_id=tokens.workspace_id, since=span[0]
        )

    try:
        listed = await list_daily(tokens=tokens, span=span)
    except IntegrationError as exc:
        logger.warning(
            "finreports: daily report list failed for %s — the tail waits a tick: %s",
            tokens.name,
            exc,
        )
        return dict(_EMPTY, workspaces_skipped=1)

    missing = tuple(
        MissingReport(report_id=header.report_id, date_to=header.date_to)
        for header in sorted(listed, key=lambda h: h.date_to)
        # `date_to` rather than `date_from`: WB states both and they are equal on
        # a daily report, but the walk keys everything off `date_to` and a
        # report that ever disagreed must not be silently placed by the other
        # end.
        if header.report_id not in held and span[0] <= header.date_to <= span[1]
    )
    if not missing:
        logger.debug(
            "finreports: %s holds every daily report WB has formed for %s..%s.",
            tokens.name,
            *span,
        )
        return dict(_EMPTY, workspaces_skipped=1)

    headers = {header.report_id: header for header in listed}
    rows = 0
    done: list[date] = []
    failed = 0
    # One report per walk, deliberately. A day is booked the moment it is
    # complete — with its fingerprint, which can only be taken once the rows are
    # in — so a report that stops early costs that day and nothing else. The
    # settled lane batches its reports because it certifies an unbroken prefix of
    # them; nothing here certifies anything, so there is no prefix to keep.
    for report in missing:
        walk = await walk_settlement_reports(
            tokens=tokens,
            reports=(report,),
            build_ingestion=build_ingestion,
            ingest=ingest_rows_only,
        )
        rows += walk.rows
        if walk.completed_through is None:
            failed += 1
            continue
        async with AsyncSessionLocal() as session:
            repo = DailySettlementRepository(session)
            await repo.record_ingest(
                workspace_id=tokens.workspace_id,
                report_id=report.report_id,
                day=report.date_to,
                create_dt=_created(headers, report.report_id),
                fingerprint=await repo.fingerprint(
                    workspace_id=tokens.workspace_id, report_id=report.report_id
                ),
                # From the same list answer that discovered the report, so the
                # day-later screen has WB's own figure to compare against.
                totals=_totals(headers, report.report_id),
            )
            await session.commit()
        done.append(report.date_to)

    logger.info(
        "finreports: daily tail for %s covered %d day(s) through %s, %d row(s).",
        tokens.name,
        len(done),
        max(done) if done else span[0],
        rows,
    )
    return dict(_EMPTY, reports=len(done), rows=rows, reports_failed=failed)


def _created(headers: dict[int, WBFinanceReportHeader], report_id: int) -> date | None:
    """WB's ``createDate`` for one listed report, if it named one."""
    header = headers.get(report_id)
    return header.create_date if header else None


def _totals(headers: dict[int, WBFinanceReportHeader], report_id: int) -> ListedTotals:
    """WB's own totals for one listed report, all ``None`` when it is absent."""
    header = headers.get(report_id)
    if header is None:
        return ListedTotals(for_pay=None, retail_amount=None, bank_payment=None)
    return listed_totals(header)


def _tail_span(*, frontier: date | None, today: date) -> tuple[date, date] | None:
    """The days the tail should cover, or ``None`` when there are none.

    Starts the day after the settled frontier and ends **yesterday**: WB has no
    data for today anywhere, and the daily list confirms it — asked on 23.09 for
    a window including 23.09, the report for that day is simply absent.

    Args:
        frontier: The settled frontier, or ``None`` for a workspace the weekly
            lane has never covered.
        today: Today in Moscow time.

    Returns:
        ``(from, to)`` inclusive, or ``None`` when the settled history already
        reaches yesterday — the ordinary state of a Monday, and not a problem.
    """
    yesterday = today - timedelta(days=1)
    floor = today - timedelta(days=DAILY_TAIL_LOOKBACK_DAYS)
    start = floor if frontier is None else max(frontier + timedelta(days=1), floor)
    return None if start > yesterday else (start, yesterday)


__all__ = ["harvest_daily_tail", "tail_one_workspace"]
