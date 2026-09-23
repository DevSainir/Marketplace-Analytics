"""The freshness gate in front of the finreports harvest.

**One list request per workspace per tick, and it answers everything.**
``sales-reports/list`` names every report WB has formed, so «is there a report we
do not hold» is a set difference against the ids on file. Nothing is derived and
nothing is guessed.

That is a change of kind from what came before. On the endpoint this replaced a
settlement request cost one of about 94 a day, so the gate spent a great deal of
care NOT asking: it derived which periods WB must have formed (Sunday or month
end, ``create_dt = date_to + 1``, measured over 142 reports) and it throttled how
often a listed report might be *fetched*, because 21 attempts a day at a report
WB had stamped and was not yet serving would have eaten the budget twice over.
The Finance surface serves one request per minute per method — 1 440 a day — and
both of those controls were removed on 2026-09-23 along with the calendar that
drove them. A report the list names is now fetched on the tick that named it,
which is the whole of the freshness this gate is for.

The gate is deliberately asymmetric. Skipping is only ever decided by an answer
that came back *empty*; a list that raised harvests anyway. A gate that fails
closed would turn a transient WB error into a silently skipped settlement day,
which is the failure mode this module exists to avoid, not to introduce.

**It does fail closed on one thing, on purpose: a standing penalty block.**
Before 2026-09-19 the probe went out first and its refusal was read as «we
learned nothing, harvest anyway», so a blocked endpoint got a probe AND a walk,
each of which restarted WB's window longer. That is the loop that took the old
settlement endpoint from a 28 197 s block to a 302 940 s one in three steps on
2026-09-17. A block is not an unanswered question — it is an answer, and the
answer is «do not ask».

What the gate cannot see is whether WB will SERVE a report it has listed. One
formed on 01.09 was first served on 09.09. A report stays on the missing list
until its rows are actually held, so a late one is asked about every tick until
it arrives rather than being left behind a watermark that jumped over it; and
«WB has formed nothing for a day inside our history» is a different question,
answered in SQL by :func:`~src.modules.finreports.tasks.gaps.survey_settlement_gaps`.

The verdict it reaches is not thrown away: it is recorded per workspace (see
:mod:`src.modules.finreports.services.freshness_record`) so the P&L page can say
in words why the statement stops where it does. «Новых отчётов нет» means
nothing without «и мы спросили 12 минут назад» — and since every tick now asks,
every tick records a true one.
"""

from __future__ import annotations

import uuid
from collections.abc import Collection
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta

from src.core.config import settings
from src.core.database import AsyncSessionLocal
from src.core.exceptions import IntegrationError
from src.core.logging import get_logger
from src.core.redis import get_redis
from src.integrations.wildberries.clients import WBFinanceReportsClient
from src.integrations.wildberries.endpoints import SALES_REPORTS_DETAILED_PATH
from src.integrations.wildberries.rate_limit import finance_reports_rate_gate
from src.integrations.wildberries.schemas import WBFinanceReportHeader
from src.modules.finreports.constants import (
    FRESHNESS_RECORD_TTL_SECONDS,
    SETTLEMENT_LIST_WINDOW_DAYS,
)
from src.modules.finreports.repos import FinancialReportRepository
from src.modules.finreports.services.freshness_record import (
    FreshnessOutcome,
    FreshnessRecordStore,
    FreshnessVerdict,
    RedisFreshnessRecordStore,
)
from src.modules.finreports.tasks.settlement import MissingReport
from src.modules.workspaces.contract import WorkspaceTokenBundle

logger = get_logger(__name__)


async def settlement_blocked_for(tokens: WorkspaceTokenBundle) -> float:
    """Seconds WB has this workspace's settlement endpoint shut for, or 0.

    Answered from the shared Redis bucket, which `penalise` writes WB's own
    ``X-Ratelimit-Retry`` into. It takes no token and sends nothing: asking WB
    whether WB will accept a request is the one thing that cannot be done
    here, and a peek that spent a slot would cost the harvest a quarter of an
    hour every time a tick looked.

    Args:
        tokens: The workspace whose bucket to inspect. Buckets are per seller
            token, so one tenant's block says nothing about another's — which
            is the assumption the 23.09.2026 experiment is meant to test.

    Returns:
        Seconds to wait, or ``0.0`` when nothing stands in the way — including
        when Redis is unreachable or the workspace has no statistics token.
        Fails open, because a bucket we cannot read is not a block.
    """
    if not tokens.finance:
        return 0.0
    gate = finance_reports_rate_gate(settings, token=tokens.finance)
    return await gate.retry_after(SALES_REPORTS_DETAILED_PATH)


@dataclass(frozen=True, slots=True)
class Outstanding:
    """The reports WB has formed that this workspace does not hold.

    Attributes:
        reports: The missing reports, oldest first — the walk's unit of work.
        overdue_days: Days since WB stamped the oldest of them. Zero on the
            day it was formed, which is the day it nearly always arrives.
    """

    reports: tuple[MissingReport, ...]
    overdue_days: int

    @property
    def span(self) -> tuple[date, date]:
        """The settlement days these reports cover, for the recorded verdict."""
        return self.reports[0].date_to, self.reports[-1].date_to


async def outstanding_reports(
    *, tokens: WorkspaceTokenBundle, held: Collection[int], today: date
) -> tuple[Outstanding | None, tuple[WBFinanceReportHeader, ...]]:
    """Ask WB which reports it has formed, and return the ones we lack.

    One request, on a bucket of its own. That separation is the point: on the
    endpoint this replaced, discovery and fetching were the same request
    against the same one-per-quarter-hour budget, which is the whole reason
    :mod:`src.modules.finreports.services.publication` derives a calendar
    instead of asking. Here asking is cheap and WB's answer is authoritative.

    Args:
        tokens: The workspace's decrypted WB credentials.
        held: ``reportId`` of every report already on file.
        today: Today in Moscow time.

    Returns:
        ``(outstanding, listed)``. The first is ``None`` when we hold everything
        WB has formed; the second is WB's whole answer either way, because the
        per-report totals on it are worth recording for the reports we DO hold
        and there is nowhere else they appear.

    Raises:
        IntegrationError: When WB did not answer. The caller decides what an
            unanswered question means; this does not guess.
    """
    since = today - timedelta(days=SETTLEMENT_LIST_WINDOW_DAYS)
    async with WBFinanceReportsClient(settings, token=tokens.finance) as client:
        listed = await client.list_reports(date_from=since, date_to=today)
    missing = tuple(
        MissingReport(report_id=header.report_id, date_to=header.date_to, header=header)
        for header in sorted(listed, key=lambda h: h.date_to)
        if header.report_id not in held
    )
    if not missing:
        return None, tuple(listed)
    oldest = min(
        header.create_date for header in listed if header.report_id == missing[0].report_id
    )
    return Outstanding(reports=missing, overdue_days=(today - oldest).days), tuple(listed)


async def check_freshness(
    *,
    tokens: WorkspaceTokenBundle,
    latest_settled: date | None,
    held: Collection[int],
    today: date,
    blocked_for: float = 0.0,
) -> tuple[FreshnessVerdict | None, tuple[MissingReport, ...], tuple[WBFinanceReportHeader, ...]]:
    """Ask WB whether it holds a report this workspace has not harvested.

    Returns a *recorded* verdict rather than a bare bool: a run that asked and
    found nothing used to leave exactly the trace a run that never happened
    did, which is why three days of a crashed harvest in August 2026 looked
    like a quiet week on the P&L.

    **Every tick asks, and every tick therefore reaches a verdict.** The cadence
    that used to pace this away on most hours existed to protect a budget of
    about 94 requests a day; the Finance surface serves 1 440, and a report found
    by the list is now fetched by the tick that found it.

    Args:
        tokens: The workspace's decrypted WB credentials.
        latest_settled: The settlement frontier, or ``None`` if this workspace
            has never been harvested.
        held: ``reportId`` of every report already on file.
        today: Today in Moscow time.
        blocked_for: Seconds WB has this workspace's report endpoint shut for,
            read from the shared rate bucket at no cost in WB requests.

    Returns:
        ``(verdict, missing reports, every report WB listed)``. The reports are
        empty whenever there is nothing to fetch, which includes the verdicts
        that say we could not ask. The third element is WB's whole answer, which
        the caller records the totals from — those exist on the list entry and
        on no settlement row, so this is the only place they are ever seen.
        The verdict is ``None`` for one case only — a workspace with no
        «Финансы» token, where nothing was asked and nothing can be. It used to
        also mean «the cadence paced this tick out», which no longer exists.
    """
    if not tokens.finance:
        logger.warning(
            "finreports: %s has no «Финансы» token — the P&L cannot be harvested.", tokens.name
        )
        return None, (), ()
    if latest_settled is None:
        logger.info("finreports: %s has no reports yet — harvesting.", tokens.name)

    # Checked before anything is sent, and before the cadence: both are free,
    # and a block is the true and stable answer a seller should read at every
    # tick of it rather than four times a day with silence in between.
    if blocked_for > 0:
        logger.warning(
            "finreports: WB has the report endpoint shut for %s for another %.0fs — "
            "not asking and not harvesting.",
            tokens.name,
            blocked_for,
        )
        return (
            FreshnessVerdict(outcome=FreshnessOutcome.RATE_BLOCKED, checked_at=datetime.now(UTC)),
            (),
            (),
        )

    try:
        outstanding, listed = await outstanding_reports(tokens=tokens, held=held, today=today)
    except IntegrationError as exc:
        # Fail open: an unanswered question is not a "no". The recorded verdict
        # says so, rather than reporting the silence as reassurance.
        logger.warning(
            "finreports: report list failed for %s — harvesting anyway: %s", tokens.name, exc
        )
        return (
            FreshnessVerdict(outcome=FreshnessOutcome.PROBE_FAILED, checked_at=datetime.now(UTC)),
            (),
            (),
        )

    if outstanding is None:
        logger.info(
            "finreports: %s holds every report WB has formed by %s — skipping.",
            tokens.name,
            today,
        )
        return (
            FreshnessVerdict(outcome=FreshnessOutcome.UP_TO_DATE, checked_at=datetime.now(UTC)),
            (),
            listed,
        )

    probe_from, probe_to = outstanding.span
    logger.info(
        "finreports: WB has %d report(s) %s does not hold (%s): harvesting.",
        len(outstanding.reports),
        tokens.name,
        ", ".join(str(report.report_id) for report in outstanding.reports),
    )
    return (
        FreshnessVerdict(
            outcome=FreshnessOutcome.WB_HAS_NEW,
            checked_at=datetime.now(UTC),
            probe_from=probe_from,
            probe_to=probe_to,
        ),
        outstanding.reports,
        listed,
    )


def freshness_record_store() -> FreshnessRecordStore:
    """The store the harvest records its verdicts in.

    A function rather than a module-level instance for the same reason
    :func:`src.core.redis.get_redis` is one: the client is resolved per call, so
    a test that swaps the shared Redis redirects this too.
    """
    return RedisFreshnessRecordStore(get_redis(), ttl_seconds=FRESHNESS_RECORD_TTL_SECONDS)


async def verdict_from_walk(
    *,
    workspace_id: uuid.UUID,
    settled_before: date | None,
    date_from: date,
    date_to: date,
) -> FreshnessVerdict:
    """Turn a completed settlement walk into the freshness verdict it proves.

    Only called when every finance window came back, so WB *did* answer about
    the walked span. What it answered is read off the settlement coverage: a day
    past where the history stood is a report we did not hold, and no movement
    means WB had nothing past it.

    Args:
        workspace_id: The workspace just harvested.
        settled_before: Its settlement coverage before this walk.
        date_from / date_to: The span the walk covered — the days WB was asked
            about, which is what the verdict's window means.

    Returns:
        ``WB_HAS_NEW`` when the walk moved the settlement coverage forward,
        ``WB_EMPTY`` when it did not.
    """
    async with AsyncSessionLocal() as session:
        settled_after = await FinancialReportRepository(session).latest_settled_date(
            workspace_id=workspace_id
        )
    moved = settled_after is not None and (settled_before is None or settled_after > settled_before)
    return FreshnessVerdict(
        outcome=FreshnessOutcome.WB_HAS_NEW if moved else FreshnessOutcome.WB_EMPTY,
        checked_at=datetime.now(UTC),
        probe_from=date_from,
        probe_to=date_to,
    )


__all__ = [
    "Outstanding",
    "check_freshness",
    "freshness_record_store",
    "settlement_blocked_for",
    "verdict_from_walk",
]
