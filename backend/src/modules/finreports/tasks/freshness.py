"""The freshness gate in front of the finreports harvest.

WB publishes the weekly realization report on no fixed day and no fixed hour —
usually one a week, sometimes two in a week, sometimes none — so the harvest
runs hourly and asks first: *is there a report we do not already hold?* One
request over the days after everything harvested answers it, and only a
windows per workspace).

This gate is what buys the schedule its frequency. Asking every hour is what
keeps a report published at 09:15 from sitting unharvested until the next
morning; asking cheaply is what makes twenty-odd ticks a day affordable on a
~1 req/min surface.

The gate is deliberately asymmetric. Skipping is only ever decided by a WB answer
that came back *empty*; every other outcome — a workspace never harvested, a
probe that raised — harvests. A gate that fails closed would turn a transient WB
error into a silently skipped settlement day, which is the failure mode this
module exists to avoid, not to introduce.

What the gate does NOT catch, by design: WB amending a report we already hold.
Its rows settle on days we have already covered, so the probe window excludes
them, and the amendment lands on the next harvest a genuinely new report
triggers.

The verdict it reaches is not thrown away: it is recorded per workspace (see
:mod:`src.modules.finreports.services.freshness_record`) so the P&L page can say
in words why the statement stops where it does. «Новых отчётов нет» means
nothing without «и мы спросили 12 минут назад».
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

from src.core.config import settings
from src.core.exceptions import IntegrationError
from src.core.logging import get_logger
from src.integrations.wildberries.clients import WBFinanceClient
from src.modules.finreports.services.freshness_record import (
    FreshnessOutcome,
    FreshnessVerdict,
)
from src.modules.workspaces.contract import WorkspaceTokenBundle

logger = get_logger(__name__)


def probe_window(*, latest_settled: date, today: date) -> tuple[date, date] | None:
    """The settlement window to ask WB about, or ``None`` if asking is pointless.

    Starts the day after the last settlement day already harvested — anything WB
    serves there belongs to a report we do not have. Ends yesterday, because WB
    has no data for today.

    Args:
        latest_settled: Last settlement day any harvested report covers.
        today: Today in Moscow time.

    Returns:
        The inclusive ``(date_from, date_to)`` to probe, or ``None`` when the
        harvested history already reaches yesterday and no unseen day exists.
    """
    date_from = latest_settled + timedelta(days=1)
    date_to = today - timedelta(days=1)
    return (date_from, date_to) if date_from <= date_to else None


async def check_freshness(
    *, tokens: WorkspaceTokenBundle, latest_settled: date | None, today: date
) -> FreshnessVerdict:
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
        latest_settled: Last settlement day already harvested, or ``None`` if the
            workspace has never been harvested.
        today: Today in Moscow time.

    Returns:
        The :class:`FreshnessVerdict` for this workspace, right now.
    """
    if latest_settled is None:
        logger.info("finreports: %s has no reports yet — harvesting.", tokens.name)
        return FreshnessVerdict(
            outcome=FreshnessOutcome.NEVER_HARVESTED, checked_at=datetime.now(UTC)
        )

    window = probe_window(latest_settled=latest_settled, today=today)
    if window is None:
        logger.info(
            "finreports: %s is settled through %s — nothing newer can exist yet, skipping.",
            tokens.name,
            latest_settled,
        )
        return FreshnessVerdict(outcome=FreshnessOutcome.UP_TO_DATE, checked_at=datetime.now(UTC))

    date_from, date_to = window
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


__all__ = ["check_freshness", "probe_window"]
