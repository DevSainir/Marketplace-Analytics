"""The freshness gate in front of the finreports harvest.

**Since 2026-09-19 this gate mostly answers without asking WB anything.** It
used to send one ``limit=1`` settlement request per workspace per hour on the
premise that WB publishes «on no fixed day and no fixed hour». The second half
is true; the first is not, and measuring it is what retired the hourly probe:
over all 142 reports «Демо» holds, ``create_dt`` is ``date_to + 1`` without
exception, and every settlement period ends on a Sunday or a month end. The
arithmetic is in :mod:`src.modules.finreports.services.publication`.

So the question «is there a report we do not hold» is now asked of our own
database first — which periods must WB have formed by today, and which of them
have no report — and of WB only when that list is non-empty. Between one report
and the next that is 147 requests per workspace not sent, and on the settlement
endpoint's ~94-per-day budget those 147 were most of it.

The gate is deliberately asymmetric. Skipping on the strength of WB's answer is
only ever decided by an answer that came back *empty*; a probe that raised
harvests anyway. A gate that fails closed would turn a transient WB error into
a silently skipped settlement day, which is the failure mode this module exists
to avoid, not to introduce.

**It does fail closed on one thing, on purpose: a standing penalty block.**
Before 2026-09-19 the probe went out first and its refusal was read as «we
learned nothing, harvest anyway», so a blocked endpoint got a probe AND a walk,
each of which restarted WB's window longer. That is the loop that took the
settlement endpoint from a 28 197 s block to a 302 940 s one in three steps on
2026-09-17. A block is not an unanswered question — it is an answer, and the
answer is «do not ask».

What the gate still cannot do is see the hour. A report formed on 01.09 may be
served on 01.09 or, as 983241109 was, on 09.09. That is why the missing-period
list is the trigger rather than a calendar: a period stays on it until its
report is actually held, so a late report is asked about every tick of every
day until it arrives instead of leaving the reachable window behind a watermark
that jumped over it.

The verdict it reaches is not thrown away: it is recorded per workspace (see
:mod:`src.modules.finreports.services.freshness_record`) so the P&L page can say
in words why the statement stops where it does. «Новых отчётов нет» means
nothing without «и мы спросили 12 минут назад».
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta

from src.core.config import settings
from src.core.database import AsyncSessionLocal
from src.core.exceptions import IntegrationError
from src.core.logging import get_logger
from src.core.redis import get_redis
from src.integrations.wildberries.clients import WBFinanceClient
from src.integrations.wildberries.endpoints import SETTLEMENT_REPORT_PATH
from src.integrations.wildberries.rate_limit import statistics_rate_gate
from src.modules.finreports.constants import FRESHNESS_RECORD_TTL_SECONDS
from src.modules.finreports.repos import FinancialReportRepository
from src.modules.finreports.services.freshness_record import (
    FreshnessOutcome,
    FreshnessRecordStore,
    FreshnessVerdict,
    RedisFreshnessRecordStore,
)
from src.modules.finreports.services.publication import is_probe_hour, missing_periods
from src.modules.workspaces.contract import WorkspaceTokenBundle

logger = get_logger(__name__)

#: The one Moscow hour every cadence in :func:`is_probe_hour` includes.
#:
#: The default for callers that have no clock of their own — tests, and any
#: future caller reasoning purely about dates. Defaulting to an hour that some
#: cadence excludes would make the gate answer «nothing to do» for a reason the
#: caller never asked about, which is the quietest way for this module to go
#: wrong.
_ALWAYS_A_PROBE_HOUR_MSK = 8


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
    if not tokens.statistics:
        return 0.0
    gate = statistics_rate_gate(settings, token=tokens.statistics)
    return await gate.retry_after(SETTLEMENT_REPORT_PATH)


@dataclass(frozen=True, slots=True)
class Outstanding:
    """A settlement window WB owes us, and how late it is.

    Attributes:
        date_from: First day to ask WB about — the oldest missing period's
            start, never a later one.
        date_to: Yesterday. WB serves nothing for today.
        overdue_days: Days since WB stamped the oldest missing report. Zero on
            the day it was formed, which is the day it nearly always arrives.
    """

    date_from: date
    date_to: date
    overdue_days: int


def probe_window(
    *, latest_settled: date, held_ends: Iterable[date], today: date
) -> Outstanding | None:
    """The settlement window to ask WB about, or ``None`` if asking is pointless.

    Asking is pointless in the one case WB's own arithmetic settles: every
    period WB can have formed by today already has a report on file. That is
    the common case by a wide margin — a report is published once a week and
    the tick runs twenty-one times a day — and it is the whole saving, so it is
    established before anything is sent.

    When something IS missing the window spans from the oldest missing
    period's first day to yesterday. The oldest, not the newest: a period that
    WB formed but has not served yet stays missing, and starting the window
    after it is precisely how 31.08.2026 was lost. Ending yesterday rather than
    at the missing period's end keeps one request answering for every missing
    period at once.

    Args:
        latest_settled: The settlement frontier: the last day that was both
            walked to completion and covered by a report we hold. A day the walk
            merely asked about and found empty is NOT settled — WB had not
            published it yet, which is the whole reason this is not the
            watermark.
        held_ends: ``date_to`` of every report already held, so a period served
            out of order is not counted as missing twice.
        today: Today in Moscow time.

    Returns:
        The window to ask about and how overdue it is, or ``None`` when every
        period WB has formed is already held.
    """
    missing = missing_periods(settled_through=latest_settled, held_ends=held_ends, today=today)
    if not missing:
        return None
    date_from = missing[0].date_from
    date_to = today - timedelta(days=1)
    if date_from > date_to:
        return None
    return Outstanding(
        date_from=date_from, date_to=date_to, overdue_days=(today - missing[0].created_on).days
    )


async def check_freshness(
    *,
    tokens: WorkspaceTokenBundle,
    latest_settled: date | None,
    held_ends: Iterable[date],
    today: date,
    hour_msk: int = _ALWAYS_A_PROBE_HOUR_MSK,
    paced: bool = True,
    blocked_for: float = 0.0,
) -> FreshnessVerdict | None:
    """Ask whether WB holds a settlement report this workspace has not harvested.

    Returns a *recorded* verdict rather than a bare ``bool``. The bool was
    enough for the branch and nothing else: a run that asked and found nothing
    left exactly the trace a run that never happened did, which is why three
    days of a crashed harvest in August 2026 looked like a quiet week on the
    P&L. The verdict carries the instant it was reached and the window asked
    about, so the page can say *why* the statement stops where it does.

    Whether the caller may skip is :attr:`FreshnessVerdict.should_harvest`, not
    a comparison written here — the fail-open rule lives in one place.

    Args:
        tokens: The workspace's decrypted WB credentials.
        latest_settled: The settlement frontier (see :func:`probe_window`), or
            ``None`` if the workspace has never been harvested.
        held_ends: ``date_to`` of every settlement report already held.
        today: Today in Moscow time.
        hour_msk: The hour now, Moscow time — the probe cadence decays with
            how overdue a report is, so not every tick asks.
        paced: Whether that cadence applies. False for the two callers that
            must reach WB whatever the hour: «Обновить», which exists for the
            case where waiting is not the answer and would be a poor button if
            it silently did nothing, and the nightly reconciliation pass,
            which is the safety net and costs one probe a day. A standing
            block still stops both — that is a claim about the channel, not
            about the clock.
        blocked_for: Seconds this workspace's settlement endpoint is shut for,
            read from the shared rate bucket at no cost in WB requests. Any
            positive value stops the tick dead — see :attr:`RATE_BLOCKED`.

    Returns:
        The :class:`FreshnessVerdict` for this workspace, or ``None`` when this
        tick asked nothing and learned nothing — a paced-out probe hour. The
        caller must skip the workspace and leave its recorded verdict alone:
        overwriting a true record with a verdict no request supports is the
        failure this module exists to prevent.
    """
    if latest_settled is None:
        logger.info("finreports: %s has no reports yet — harvesting.", tokens.name)
        return FreshnessVerdict(
            outcome=FreshnessOutcome.NEVER_HARVESTED, checked_at=datetime.now(UTC)
        )

    window = probe_window(latest_settled=latest_settled, held_ends=held_ends, today=today)
    if window is None:
        logger.info(
            "finreports: %s holds every report WB can have formed by %s — skipping.",
            tokens.name,
            today,
        )
        return FreshnessVerdict(outcome=FreshnessOutcome.UP_TO_DATE, checked_at=datetime.now(UTC))

    # Paced, and this is where «a missing period stays missing» stops being
    # free. Keeping a period on the list until its report is held is what makes
    # a late report reachable at all — but WB has been eight days late once
    # (983241109), and twenty-one ticks a day across eight days is 168 requests
    # against a budget of about 94. So the cadence decays with how overdue the
    # report is; see :func:`is_probe_hour`.
    #
    # `None`, not a verdict. A tick that did not ask learned nothing, and
    # writing any outcome here would overwrite a true record with a claim this
    # tick cannot support — «загружены по вчерашний день» over a week WB has
    # published, which is precisely the bug this module was rewritten to stop
    # telling. The previous verdict stands, and its `checked_at` ages honestly.
    if paced and not is_probe_hour(overdue_days=window.overdue_days, hour_msk=hour_msk):
        logger.debug(
            "finreports: %s has an outstanding report %d day(s) overdue, "
            "but %02d:00 MSK is not one of its probe hours.",
            tokens.name,
            window.overdue_days,
            hour_msk,
        )
        return None

    # Checked AFTER the cheap skip and BEFORE anything is sent. After, because
    # a workspace with nothing outstanding should not be reported as blocked —
    # it is simply done. Before, because this is the whole correction: the
    # probe used to go out into a standing block, be refused, and be read as
    # «we learned nothing, harvest anyway», so one blocked endpoint drew two
    # more requests per tick and each of them lengthened the block.
    if blocked_for > 0:
        logger.warning(
            "finreports: WB has the settlement endpoint shut for %s for another %.0fs "
            "— not probing and not harvesting; a request inside the block lengthens it.",
            tokens.name,
            blocked_for,
        )
        return FreshnessVerdict(outcome=FreshnessOutcome.RATE_BLOCKED, checked_at=datetime.now(UTC))

    date_from, date_to = window.date_from, window.date_to
    try:
        async with WBFinanceClient(settings, token=tokens.statistics) as client:
            row = await client.fetch_first_row(date_from=date_from, date_to=date_to)
    except IntegrationError as exc:
        # Fail open: an unanswered question is not a "no". Skipping here would
        # postpone a settlement day on nothing but a transient WB error — and
        # the recorded verdict says the question went unanswered, so the page
        # can admit the data may be incomplete instead of reporting the silence
        # as "nothing new".
        logger.warning(
            "finreports: freshness probe failed for %s (%s..%s) — harvesting anyway: %s",
            tokens.name,
            date_from,
            date_to,
            exc,
        )
        return FreshnessVerdict(
            outcome=FreshnessOutcome.PROBE_FAILED,
            checked_at=datetime.now(UTC),
            probe_from=date_from,
            probe_to=date_to,
        )

    if row is None:
        logger.info(
            "finreports: no new WB report for %s (%s..%s is empty) — skipping harvest.",
            tokens.name,
            date_from,
            date_to,
        )
        return FreshnessVerdict(
            outcome=FreshnessOutcome.WB_EMPTY,
            checked_at=datetime.now(UTC),
            probe_from=date_from,
            probe_to=date_to,
        )

    logger.info(
        "finreports: WB report %s (created %s) is new for %s — harvesting.",
        row.realizationreport_id,
        row.create_dt,
        tokens.name,
    )
    return FreshnessVerdict(
        outcome=FreshnessOutcome.WB_HAS_NEW,
        checked_at=datetime.now(UTC),
        probe_from=date_from,
        probe_to=date_to,
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
    "probe_window",
    "settlement_blocked_for",
    "verdict_from_walk",
]
