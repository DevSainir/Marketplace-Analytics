"""The day-later check: does WB still serve the report it served us?

The measuring half of the provisional tail; the fetching half is in
:mod:`.harvest`. The screen is WB's own totals listed again, so a report whose
figures have not moved costs no detail request — see :func:`verify_daily_tail`.
"""

from __future__ import annotations

import uuid

from src.core.database import AsyncSessionLocal
from src.core.exceptions import IntegrationError
from src.core.locks import single_flight
from src.core.logcontext import bind_workspace
from src.core.logging import get_logger
from src.core.redis import get_redis
from src.modules.finreports.constants import (
    DAILY_TAIL_VERIFY_AFTER_HOURS,
    DAILY_TAIL_VERIFY_LIMIT,
    HARVEST_LOCK_KEY,
    HARVEST_LOCK_TTL_SECONDS,
)
from src.modules.finreports.models import DailyReportVerdict
from src.modules.finreports.repos import (
    DailySettlementRepository,
    ListedTotals,
    PendingVerification,
)
from src.modules.finreports.tasks.daily_tail.common import (
    list_daily,
    listed_totals,
    settled_frontier,
)
from src.modules.finreports.tasks.ingestion_factory import build_ingestion
from src.modules.finreports.tasks.settlement import (
    MissingReport,
    walk_settlement_reports,
)
from src.modules.workspaces.contract import WorkspaceTokenBundle, load_workspace_token_bundles

logger = get_logger(__name__)

#: Zeroed result shape for the verification pass.
_EMPTY_VERIFY: dict[str, int] = {
    "checked": 0,
    "screened": 0,
    "unchanged": 0,
    "changed": 0,
    "superseded": 0,
    "withdrawn": 0,
    "failed": 0,
    "skipped_locked": 0,
}

#: Most reports one run will look at per workspace.
#:
#: Not a WB cost — screening is arithmetic on a list answer already in hand — but
#: a bound on the SQL and the log volume of a run that finds a long backlog. High
#: enough that a fortnight of days drains in one go.
_VERIFY_SCREEN_LIMIT = 100


async def verify_daily_tail() -> dict[str, int]:
    """Check a day later whether WB still serves the report it served us.

    The one measurement this lane owes. A daily report is served the morning
    after its day; whether WB then revises it is unknown, and until it is known
    a daily figure must not be presented as final.

    **The check is one list request, not one detail request per report.**
    ``sales-reports/list`` carries WB's own totals per report, so a report whose
    totals are where they were is settled by arithmetic on an answer that covered
    every report in the window at once. Only a report whose totals MOVED — or one
    booked before those totals were kept — has its rows re-read and its digest
    compared, which is what says *what* changed rather than merely that it did.

    The comparison is WB's figure against WB's earlier figure. Deliberately not
    against anything we compute: our reconstruction of ``forPaySum`` is knowingly
    128.26 KGS out on report 989286628 because of how we bucket the sales
    correction, so a screen built on our own arithmetic would fire on a difference
    that is ours and hide the one that is WB's.

    Three outcomes need no request at all. A report the weekly lane has since
    taken over is ``SUPERSEDED`` — those rows belong to a settlement document
    now, and re-reading the daily copy would only flip their ``report_id`` back.
    One WB no longer lists is ``WITHDRAWN``. One whose totals match is
    ``UNCHANGED``.

    Returns:
        ``checked`` reports whose rows were re-read, ``screened`` settled from
        the list alone, split into ``unchanged`` / ``changed`` / ``superseded`` /
        ``withdrawn``, plus ``failed`` for reports WB would not serve and
        ``skipped_locked`` when a harvest held the lock.
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
    """Check one workspace's due daily reports. See :func:`verify_daily_tail`."""
    bind_workspace(tokens.workspace_id)
    frontier = await settled_frontier(workspace_id=tokens.workspace_id)
    async with AsyncSessionLocal() as session:
        # No WB-cost limit here any more: screening a report is free, so the
        # budget bound belongs on the DETAIL re-reads below. What remains is
        # `_VERIFY_SCREEN_LIMIT`, a generous bound on SQL and log volume, so a
        # backlog drains in one run instead of three a day at a time.
        pending = await DailySettlementRepository(session).due_for_verification(
            workspace_id=tokens.workspace_id,
            after_hours=DAILY_TAIL_VERIFY_AFTER_HOURS,
            limit=_VERIFY_SCREEN_LIMIT,
        )
    if not pending:
        return dict(_EMPTY_VERIFY)

    try:
        listed = await list_daily(
            tokens=tokens, span=(min(r.day for r in pending), max(r.day for r in pending))
        )
    except IntegrationError as exc:
        # Fail open and record nothing. Without WB's list there is no screen, and
        # guessing «unchanged» would retire the whole queue on a network blip.
        logger.warning(
            "finreports: daily list failed for %s — verification waits a day: %s",
            tokens.name,
            exc,
        )
        return dict(_EMPTY_VERIFY, failed=len(pending))
    served = {header.report_id: header for header in listed}

    totals = dict(_EMPTY_VERIFY)
    rereads_left = DAILY_TAIL_VERIFY_LIMIT
    for report in pending:
        if frontier is not None and report.day <= frontier:
            await _record(tokens.workspace_id, report.report_id, DailyReportVerdict.SUPERSEDED)
            totals["superseded"] += 1
            continue
        header = served.get(report.report_id)
        if header is None:
            # Withdrawn: WB no longer vouches for these rows, so they leave the
            # statement now rather than when the weekly report closes the day.
            async with AsyncSessionLocal() as session:
                repo = DailySettlementRepository(session)
                dropped = await repo.drop_rows(
                    workspace_id=tokens.workspace_id, report_ids=[report.report_id]
                )
                await repo.record_verification(
                    workspace_id=tokens.workspace_id,
                    report_id=report.report_id,
                    verdict=DailyReportVerdict.WITHDRAWN,
                )
                await session.commit()
            totals["withdrawn"] += 1
            logger.warning(
                "finreports: daily report %d (%s) for %s is no longer listed by WB; "
                "its %d provisional row(s) are removed from the statement.",
                report.report_id,
                report.day,
                tokens.name,
                dropped,
            )
            continue
        now = listed_totals(header)
        if report.totals.known() and now == report.totals:
            await _record(tokens.workspace_id, report.report_id, DailyReportVerdict.UNCHANGED)
            totals["screened"] += 1
            totals["unchanged"] += 1
            logger.info(
                "finreports: daily report %d (%s) for %s unchanged after %d h — "
                "WB still totals %s, screened from the list.",
                report.report_id,
                report.day,
                tokens.name,
                DAILY_TAIL_VERIFY_AFTER_HOURS,
                now.for_pay,
            )
            continue
        if rereads_left <= 0:
            # Left queued on purpose. The next run re-screens it and spends a
            # re-read then; recording a verdict here would retire a report whose
            # rows nobody has looked at.
            continue
        rereads_left -= 1
        counts = await _reread_and_compare(tokens=tokens, report=report, listed=now)
        for key, value in counts.items():
            totals[key] += value
    return totals


async def _reread_and_compare(
    *,
    tokens: WorkspaceTokenBundle,
    report: PendingVerification,
    listed: ListedTotals,
) -> dict[str, int]:
    """Re-read one report's rows and record how they differ from the first read.

    Reached only when the cheap screen could not settle it: WB's totals moved, or
    the report was booked before those totals were kept. The digest is what says
    *what* moved — a restatement need not change the row count, and usually would
    not.

    Args:
        tokens: The workspace's decrypted WB credentials.
        report: The queued report, carrying what the first ingest recorded.
        listed: WB's totals as just served, for the log line.

    Returns:
        A counts fragment: ``failed`` when WB would not serve the rows, otherwise
        ``checked`` plus one of ``changed`` / ``unchanged``.
    """
    # The old rows go first, so what is left afterwards is exactly what WB serves
    # now: an upsert alone would keep a row WB has since taken out of the report.
    async with AsyncSessionLocal() as session:
        await DailySettlementRepository(session).drop_rows(
            workspace_id=tokens.workspace_id, report_ids=[report.report_id]
        )
        await session.commit()
    walk = await walk_settlement_reports(
        tokens=tokens,
        reports=(MissingReport(report_id=report.report_id, date_to=report.day),),
        build_ingestion=build_ingestion,
    )
    if walk.completed_through is None:
        # Not a verdict — an unanswered question is not a finding. The rows are
        # gone, though, so the record goes too: the report then reads as missing
        # and the tail's next tick, a quarter of an hour away, fetches it anew.
        async with AsyncSessionLocal() as session:
            await DailySettlementRepository(session).forget(
                workspace_id=tokens.workspace_id, report_id=report.report_id
            )
            await session.commit()
        return {"failed": 1}
    async with AsyncSessionLocal() as session:
        repo = DailySettlementRepository(session)
        found = await repo.fingerprint(workspace_id=tokens.workspace_id, report_id=report.report_id)
        changed = found.rows != report.rows or found.digest != report.digest
        await repo.record_verification(
            workspace_id=tokens.workspace_id,
            report_id=report.report_id,
            verdict=DailyReportVerdict.CHANGED if changed else DailyReportVerdict.UNCHANGED,
            found=found,
        )
        await session.commit()
    if changed:
        # ERROR rather than warning: this is the finding that would mean a
        # provisional day may not be shown beside a settled one, and it must not
        # scroll past as routine noise.
        logger.error(
            "finreports: daily report %d (%s) for %s CHANGED after %d h — "
            "%d row(s)/%s at ingest, %d row(s)/%s now, WB totals %s against %s. "
            "A day in the tail is not stable; see the daily_settlement_report row.",
            report.report_id,
            report.day,
            tokens.name,
            DAILY_TAIL_VERIFY_AFTER_HOURS,
            report.rows,
            report.digest[:8],
            found.rows,
            found.digest[:8],
            listed.for_pay,
            report.totals.for_pay,
        )
        return {"checked": 1, "changed": 1}
    # The rows are identical and WB's totals were not — either WB restated its
    # own header over unchanged rows, or this report predates the stored totals
    # and there was nothing to screen against. Both are «unchanged» as far as the
    # statement goes, and the log says which.
    logger.info(
        "finreports: daily report %d (%s) for %s unchanged after %d h (%d rows, re-read; "
        "WB totals %s against stored %s).",
        report.report_id,
        report.day,
        tokens.name,
        DAILY_TAIL_VERIFY_AFTER_HOURS,
        found.rows,
        listed.for_pay,
        report.totals.for_pay,
    )
    return {"checked": 1, "unchanged": 1}


async def _record(workspace_id: uuid.UUID, report_id: int, verdict: DailyReportVerdict) -> None:
    """Record a verdict reached without fetching anything."""
    async with AsyncSessionLocal() as session:
        await DailySettlementRepository(session).record_verification(
            workspace_id=workspace_id, report_id=report_id, verdict=verdict
        )
        await session.commit()


__all__ = ["verify_daily_tail"]
