"""Which reports the history walk still owes this workspace, and in what order.

The half that used to be :mod:`span`, and it is a different question now. The
old endpoint took a PERIOD, so "what is missing" had to be inferred from the
settlement days already stored: a hole was a run of empty days long enough not
to be the ordinary weekly rhythm (a fourteen-day tolerance), a
span was the newest such hole cut to a month, and the whole thing was a
heuristic reading tea leaves out of ``logistics_transaction``. It failed in
production more than once, and always the same way — a hole it could not see,
declared complete.

``sales-reports/list`` answers the question outright. WB names every report it
has formed; we hold a set of ``reportId``; the backlog is the difference. There
is nothing to infer, no tolerance to tune, and a hole in the middle of a
seller's history is not a special case — it is one of the ids in the set.

Measured on one workspace 2026-09-23, which is what makes this affordable:

* **one list request covers the whole history, at any width.** A 1095-day
  window returned all 143 reports, back to the account's first week in January
  2024, and an 11.7-year one returned exactly the same 143 rather than refusing
  or truncating. Discovery is one request, not a walk, and it is on its own
  1/min bucket — so a tick that re-lists costs the fetching budget nothing.
* **no report needs a second page.** The largest of the 143 held 16 801 rows
  against WB's 100 000-row page. One report is one request by id — and since
  2026-09-23 a contiguous run of them is cheaper still by period (:mod:`batch`).

So the lane re-asks every tick and keeps almost no state. What little it does
keep is the ceiling and the sweep counter below, and both exist for one reason
each.
"""

from __future__ import annotations

import uuid
from collections.abc import Collection
from dataclasses import dataclass
from datetime import date, timedelta
from typing import NamedTuple

from src.core.config import settings
from src.core.database import AsyncSessionLocal
from src.integrations.wildberries.clients import WBFinanceReportsClient
from src.integrations.wildberries.schemas import WBFinanceReportHeader
from src.modules.finreports.constants import SETTLEMENT_LIST_WINDOW_DAYS, WB_REPORTS_EPOCH
from src.modules.finreports.repos import FinancialReportRepository
from src.modules.finreports.tasks.settlement import MissingReport
from src.modules.workspaces.contract import WorkspaceTokenBundle

#: Cursor field separator.
_SEP = "|"


@dataclass(frozen=True, slots=True)
class Backlog:
    """What the history walk still owes, as of one list request.

    Attributes:
        due: Reports missing at or below the ceiling, **newest first** — what
            this tick may fetch. Newest first because a backfill is interrupted
            far more often than it is finished, and what a seller needs is this
            month's P&L rather than the archive.
        outstanding: Every missing report in scope, ceiling or not. What the
            sweep rule compares against, and the only number that says whether
            a sweep achieved anything.
        total: Reports in scope, held or not — the progress bar's denominator.
        listed: WB's whole answer, scope and harvest window alike. Carried so
            the caller can record the per-report totals on the reports it holds
            — this lane lists the ENTIRE history every tick, where the forward
            harvest only ever sees its own 45-day window, so it is the only
            place the deep archive's totals can be filled in at all.
    """

    due: tuple[MissingReport, ...]
    outstanding: int
    total: int
    listed: tuple[WBFinanceReportHeader, ...] = ()

    @property
    def done(self) -> int:
        """Reports in scope already on file."""
        return self.total - self.outstanding


async def survey_backlog(
    *, tokens: WorkspaceTokenBundle, floor: date, ceiling: date, today: date
) -> Backlog:
    """Ask WB what it has formed, and subtract what this workspace holds.

    One request, on the list bucket. It is re-asked every tick rather than
    cached into the cursor, and that is deliberate: a cursor carrying the
    backlog is a second copy of the truth, and every production failure this
    lane has had was a stale second copy — a span chosen from coverage taken
    before the rows it had just written existed, a lane declaring itself
    complete over a hole its own picture could not see. WB's list is cheap
    enough to be the only copy.

    **Reports the forward harvest owns are not offered.** It walks everything
    inside :data:`SETTLEMENT_LIST_WINDOW_DAYS` — its scheduled ticks while a
    report is due, and the 04:00 pass every night regardless — so a
    backfill reaching into that window would spend a minute-long token racing
    it for rows that were arriving anyway. The two lanes meet at that boundary
    and neither has a hole on its side of it.

    Args:
        tokens: The workspace's decrypted WB credentials.
        floor: The oldest settlement day worth asking for. Production passes
            :data:`WB_REPORTS_EPOCH`; it is a parameter so a test can narrow the
            history without narrowing what a seller gets.
        ceiling: Ignore reports ending after this — already attempted in this
            sweep. See :func:`advance_ceiling`.
        today: Today in Moscow time.

    Returns:
        The backlog. ``due`` is empty when this sweep has attempted everything
        it can reach, which is not the same as the lane being finished.

    Raises:
        IntegrationError: When WB did not answer. The caller decides what an
            unanswered question means; this does not guess.
    """
    horizon = today - timedelta(days=SETTLEMENT_LIST_WINDOW_DAYS)
    async with WBFinanceReportsClient(settings, token=tokens.finance) as client:
        listed = await client.list_reports(date_from=floor, date_to=today)
    in_scope = [header for header in listed if floor <= header.date_to < horizon]
    held = await held_report_ids(tokens.workspace_id, since=floor)
    missing = [header for header in in_scope if header.report_id not in held]
    due = tuple(
        MissingReport(report_id=header.report_id, date_to=header.date_to, header=header)
        for header in sorted(missing, key=lambda header: header.date_to, reverse=True)
        if header.date_to <= ceiling
    )
    return Backlog(due=due, outstanding=len(missing), total=len(in_scope), listed=tuple(listed))


async def held_report_ids(workspace_id: uuid.UUID, *, since: date) -> Collection[int]:
    """Every ``reportId`` this workspace has settlement rows for.

    Read here rather than handed in by the task, for the same reason the survey
    is: the walk commits reports as it goes, and a picture taken before the
    tick started would offer back the report it had that moment fetched.

    Args:
        workspace_id: The workspace being walked.
        since: The scope floor — ids older than this are nobody's business.

    Returns:
        The ids on file **whose rows add up to what WB says they should**. See
        :meth:`~src.modules.finreports.repos.financial_report.FinancialReportRepository.incomplete_report_ids`.
    """
    async with AsyncSessionLocal() as session:
        repo = FinancialReportRepository(session)
        held = await repo.report_ids_since(workspace_id=workspace_id, since=since)
        # A header is not proof of a report. One written beside the first batch
        # of rows — which is how they were written until 2026-09-23 — survives a
        # fetch that died half-way, and the id alone then says «held» for ever.
        # WB's own total is the proof, so what disagrees with it is subtracted
        # and asked for again.
        return held - await repo.incomplete_report_ids(workspace_id=workspace_id)


def advance_ceiling(attempted: tuple[MissingReport, ...], ceiling: date) -> date:
    """Move the ceiling below every report this tick attempted.

    The ceiling is what makes a sweep terminate, and it guards exactly one case:
    **a report that never stops being missing** — one WB lists and serves no
    rows for (a header is refused over no rows when WB lists money in it), or
    one that never adds up to WB's own total. Without a ceiling the lane would
    ask WB for it once a minute for ever. On this endpoint that is
    not a slow lane but a penalty block.

    It moves past reports that FAILED too, which is the sweep's other half: a
    report lost to a timeout or a refused page is not retried on the next tick
    but on the next sweep, once the ceiling has run off the bottom of the
    history. That is slower for the one report and far safer for the lane —
    retrying in place is how a single unservable report becomes an endless one.

    Args:
        attempted: The reports the tick asked WB for, newest first.
        ceiling: The ceiling it started with.

    Returns:
        The day before the oldest report attempted, or the ceiling unchanged
        when nothing was attempted.
    """
    if not attempted:
        return ceiling
    return min(report.date_to for report in attempted) - timedelta(days=1)


class InFlight(NamedTuple):
    """A window a previous tick opened and ran out of time on.

    Attributes:
        span_from / span_to: The period being walked. Kept rather than
            recomputed, because the run it was built from is a fact about the
            moment it started — re-deriving it after a page landed would give a
            different, shorter run and leave the rows already fetched orphaned.
        cursor: ``rrdId`` the walk reached.
    """

    span_from: date
    span_to: date
    cursor: int


def parse_cursor(cursor: str) -> tuple[date, int, int, InFlight | None] | None:
    """Read the cursor back: ceiling, sweep number, backlog at its start.

    Returns ``None`` for anything that is not this shape, which the caller
    treats as a fresh lane. The one thing it has to recognise and reject is the
    cursor this rewrite replaced — ``span_from|span_to|rrd_id|empties|search``,
    whose first field is also a date and would otherwise be read as a ceiling
    with an ``rrd_id`` mistaken for a backlog count. Rejecting it costs a lane
    mid-walk one restart from the top, which on this endpoint is minutes.

    A live lane DID need it, which this docstring got wrong first. It said no
    lane was mid-walk, on the strength of a diagnostic that came back empty —
    but `workspaces.workspace_backfill` carries a tenancy policy, so that probe
    could only ever see the diagnostic workspace, which has no lane row. Another
    workspace's was there the whole time: seeded 11.09, last moved 15.09, cursor
    `2026-06-17|2026-07-08|3128642845490|0|2026-07-08`. Rejected on 23.09
    exactly as intended, and the lane restarted from the top.

    Args:
        cursor: The stored cursor.

    Returns:
        ``(ceiling, sweep, outstanding_at_sweep_start, in_flight)``, or ``None``
        when the cursor is not one this lane wrote. ``in_flight`` is the window
        a previous tick left open, and is absent from most cursors.
    """
    parts = cursor.split(_SEP)
    if len(parts) not in (3, 6) or not (parts[1].isdigit() and parts[2].isdigit()):
        return None
    try:
        ceiling = date.fromisoformat(parts[0])
        in_flight = (
            InFlight(date.fromisoformat(parts[3]), date.fromisoformat(parts[4]), int(parts[5]))
            if len(parts) == 6
            else None
        )
    except ValueError:
        return None
    return ceiling, int(parts[1]), int(parts[2]), in_flight


def format_cursor(
    ceiling: date,
    sweep: int,
    outstanding_at_sweep_start: int,
    in_flight: InFlight | None = None,
) -> str:
    """Write the ceiling, the sweep, its opening backlog and any open window."""
    fields = [ceiling.isoformat(), str(sweep), str(outstanding_at_sweep_start)]
    if in_flight is not None:
        fields += [
            in_flight.span_from.isoformat(),
            in_flight.span_to.isoformat(),
            str(in_flight.cursor),
        ]
    return _SEP.join(fields)


__all__ = [
    "WB_REPORTS_EPOCH",
    "Backlog",
    "InFlight",
    "advance_ceiling",
    "format_cursor",
    "held_report_ids",
    "parse_cursor",
    "survey_backlog",
]
