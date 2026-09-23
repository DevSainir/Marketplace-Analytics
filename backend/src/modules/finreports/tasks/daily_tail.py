"""The provisional daily tail: settlement days the weekly report has not reached.

WB forms a realization report per day as well as per week — ``period: "daily"``
on the same two methods, defaulting to ``weekly``, which is the whole reason this
existed unread until 2026-09-23. A daily report is stamped ``date_to + 1`` and
served that morning, against the one-to-eight days a weekly report takes, so this
lane is what lets the P&L reach **yesterday** instead of last Sunday.

It is deliberately an addition rather than a replacement, and the shape follows
from what is and is not proven:

* **The rows are the same rows.** Measured over the closed week 14.09-20.09 on
  «Демо»: seven daily reports and weekly report 989438999 are the same 4 424
  rows sharing their ``rrdId`` one for one, every money column summing to the same
  figure. So they go into ``logistics_transaction`` like any others and the P&L
  picks them up by ``rr_dt`` — there is nothing to change on the read side, and
  the rollup rebuilds any day whose row count it disagrees with.
* **What is NOT proven is whether a daily report is revised after WB serves it.**
  So this lane never writes a weekly header, never moves the settlement
  watermark, and never claims a day is settled. It records what it fetched and
  :func:`verify_daily_tail` re-reads it a day later to find out.
* **It walks only ahead of the settled frontier.** A day at or behind the
  frontier belongs to the weekly lane, which is the authority; re-fetching it
  here would do nothing but flip those rows' ``report_id`` to a daily id.
* **It takes the weekly harvest's own lock.** Both lanes spend the same
  one-request-a-minute WB buckets, so running them at once would only make each
  429 the other. Losing the lock costs a tick, and on the six days a week the
  weekly tick finds nothing, the lock is free.
"""

from __future__ import annotations

from datetime import date, timedelta

from src.core.config import settings
from src.core.database import AsyncSessionLocal
from src.core.exceptions import IntegrationError
from src.core.locks import single_flight
from src.core.logcontext import bind_workspace
from src.core.logging import get_logger
from src.core.redis import get_redis
from src.core.timeutils import moscow_today
from src.integrations.wildberries.clients import ReportPeriod, WBFinanceReportsClient
from src.integrations.wildberries.schemas import WBFinanceReportHeader
from src.modules.finreports.constants import (
    DAILY_TAIL_LOOKBACK_DAYS,
    DAILY_TAIL_VERIFY_AFTER_HOURS,
    DAILY_TAIL_VERIFY_LIMIT,
    HARVEST_LOCK_KEY,
    HARVEST_LOCK_TTL_SECONDS,
)
from src.modules.finreports.models import DailyReportVerdict
from src.modules.finreports.repos import (
    DailySettlementRepository,
    FinancialReportRepository,
    SettlementWatermarkRepository,
)
from src.modules.finreports.tasks.ingestion_factory import build_ingestion
from src.modules.finreports.tasks.settlement import (
    MissingReport,
    ingest_rows_only,
    walk_settlement_reports,
)
from src.modules.finreports.tasks.spans import settlement_frontier
from src.modules.workspaces.contract import (
    WorkspaceTokenBundle,
    load_workspace_token_bundles,
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

#: Zeroed result shape for the verification pass.
_EMPTY_VERIFY: dict[str, int] = {
    "checked": 0,
    "unchanged": 0,
    "changed": 0,
    "superseded": 0,
    "failed": 0,
    "skipped_locked": 0,
}


async def harvest_daily_tail() -> dict[str, int]:
    """Cover every workspace's days between the settled frontier and yesterday.

    Returns:
        ``reports`` daily reports completed, ``rows`` settlement rows written,
        ``reports_failed`` reports that stopped early, ``workspaces_skipped``
        workspaces with nothing to do, and ``skipped_locked`` 1 when the weekly
        harvest held the lock and this run did nothing.
    """
    async with single_flight(
        HARVEST_LOCK_KEY, ttl_seconds=HARVEST_LOCK_TTL_SECONDS, redis=get_redis()
    ) as acquired:
        if not acquired:
            logger.info("finreports: the settled harvest holds the lock — daily tail skipped.")
            return dict(_EMPTY, skipped_locked=1)
        today = moscow_today()
        async with AsyncSessionLocal() as session:
            bundles = list(await load_workspace_token_bundles(session))
        totals = dict(_EMPTY)
        for bundle in bundles:
            if not bundle.finance:
                continue
            counts = await _tail_one_workspace(tokens=bundle, today=today)
            for key, value in counts.items():
                totals[key] += value
        return totals


async def _tail_one_workspace(*, tokens: WorkspaceTokenBundle, today: date) -> dict[str, int]:
    """Harvest one workspace's daily tail. See :func:`harvest_daily_tail`."""
    bind_workspace(tokens.workspace_id)
    async with AsyncSessionLocal() as session:
        frontier = settlement_frontier(
            watermark=await SettlementWatermarkRepository(session).get(
                workspace_id=tokens.workspace_id
            ),
            covered_through=await FinancialReportRepository(session).latest_settled_date(
                workspace_id=tokens.workspace_id
            ),
        )
        span = _tail_span(frontier=frontier, today=today)
        if span is None:
            return dict(_EMPTY, workspaces_skipped=1)
        held = await DailySettlementRepository(session).held_ids(
            workspace_id=tokens.workspace_id, since=span[0]
        )

    try:
        listed = await _list_daily(tokens=tokens, span=span)
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

    create_dates = {header.report_id: header.create_date for header in listed}
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
                create_dt=create_dates.get(report.report_id),
                fingerprint=await repo.fingerprint(
                    workspace_id=tokens.workspace_id, report_id=report.report_id
                ),
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


async def _list_daily(
    *, tokens: WorkspaceTokenBundle, span: tuple[date, date]
) -> list[WBFinanceReportHeader]:
    """Ask WB which daily reports it has formed over ``span``.

    One request, on the list bucket rather than the detail one — the separation
    is what makes «is there anything to fetch» cost nothing the fetching needs.
    """
    async with WBFinanceReportsClient(settings, token=tokens.finance) as client:
        return list(
            await client.list_reports(date_from=span[0], date_to=span[1], period=ReportPeriod.DAILY)
        )


async def verify_daily_tail() -> dict[str, int]:
    """Re-read daily reports a day after harvesting them, and record what changed.

    The one measurement this lane owes. A daily report is served the morning
    after its day; whether WB then revises it is unknown, and until it is known
    a daily figure must not be presented as final. So each report is re-fetched
    once, at least :data:`DAILY_TAIL_VERIFY_AFTER_HOURS` after it was ingested,
    and the row count and content digest are compared against what the first
    ingest recorded.

    A report the weekly lane has since taken over is not fetched at all: those
    rows now belong to a settlement document, and re-reading the daily copy would
    only flip their ``report_id`` back. It is recorded as
    :attr:`~src.modules.finreports.models.daily_settlement_report.DailyReportVerdict.SUPERSEDED`
    so it leaves the queue honestly rather than sitting on it for ever.

    Returns:
        ``checked`` reports re-read, split into ``unchanged`` / ``changed`` /
        ``superseded``, plus ``failed`` for reports WB would not serve and
        ``skipped_locked`` when the harvest held the lock.
    """
    async with single_flight(
        HARVEST_LOCK_KEY, ttl_seconds=HARVEST_LOCK_TTL_SECONDS, redis=get_redis()
    ) as acquired:
        if not acquired:
            logger.info("finreports: the harvest holds the lock — daily verification skipped.")
            return dict(_EMPTY_VERIFY, skipped_locked=1)
        async with AsyncSessionLocal() as session:
            bundles = list(await load_workspace_token_bundles(session))
        totals = dict(_EMPTY_VERIFY)
        for bundle in bundles:
            if not bundle.finance:
                continue
            counts = await _verify_one_workspace(tokens=bundle)
            for key, value in counts.items():
                totals[key] += value
        return totals


async def _verify_one_workspace(*, tokens: WorkspaceTokenBundle) -> dict[str, int]:
    """Re-read one workspace's due daily reports. See :func:`verify_daily_tail`."""
    bind_workspace(tokens.workspace_id)
    async with AsyncSessionLocal() as session:
        frontier = settlement_frontier(
            watermark=await SettlementWatermarkRepository(session).get(
                workspace_id=tokens.workspace_id
            ),
            covered_through=await FinancialReportRepository(session).latest_settled_date(
                workspace_id=tokens.workspace_id
            ),
        )
        pending = await DailySettlementRepository(session).due_for_verification(
            workspace_id=tokens.workspace_id,
            after_hours=DAILY_TAIL_VERIFY_AFTER_HOURS,
            limit=DAILY_TAIL_VERIFY_LIMIT,
        )
    if not pending:
        return dict(_EMPTY_VERIFY)

    totals = dict(_EMPTY_VERIFY)
    for report in pending:
        if frontier is not None and report.day <= frontier:
            async with AsyncSessionLocal() as session:
                await DailySettlementRepository(session).record_verification(
                    report_id=report.report_id, verdict=DailyReportVerdict.SUPERSEDED
                )
                await session.commit()
            totals["superseded"] += 1
            continue
        walk = await walk_settlement_reports(
            tokens=tokens,
            reports=(MissingReport(report_id=report.report_id, date_to=report.day),),
            build_ingestion=build_ingestion,
            ingest=ingest_rows_only,
        )
        if walk.completed_through is None:
            # Not recorded as a verdict: an unanswered question is not a finding,
            # and marking it verified would retire the only report that still
            # needs asking about.
            totals["failed"] += 1
            continue
        async with AsyncSessionLocal() as session:
            repo = DailySettlementRepository(session)
            found = await repo.fingerprint(
                workspace_id=tokens.workspace_id, report_id=report.report_id
            )
            changed = found.rows != report.rows or found.digest != report.digest
            await repo.record_verification(
                report_id=report.report_id,
                verdict=DailyReportVerdict.CHANGED if changed else DailyReportVerdict.UNCHANGED,
                found=found,
            )
            await session.commit()
        totals["checked"] += 1
        if changed:
            totals["changed"] += 1
            # ERROR rather than warning: this is the finding that would mean a
            # provisional day may not be shown beside a settled one, and it must
            # not scroll past as routine noise.
            logger.error(
                "finreports: daily report %d (%s) for %s CHANGED after %d h — "
                "%d row(s)/%s at ingest, %d row(s)/%s now. A day in the tail is "
                "not stable; see the daily_settlement_report row.",
                report.report_id,
                report.day,
                tokens.name,
                DAILY_TAIL_VERIFY_AFTER_HOURS,
                report.rows,
                report.digest[:8],
                found.rows,
                found.digest[:8],
            )
        else:
            totals["unchanged"] += 1
            logger.info(
                "finreports: daily report %d (%s) for %s unchanged after %d h (%d rows).",
                report.report_id,
                report.day,
                tokens.name,
                DAILY_TAIL_VERIFY_AFTER_HOURS,
                found.rows,
            )
    return totals


__all__ = ["harvest_daily_tail", "verify_daily_tail"]
