"""The day-later re-read: what it concludes, and what it refuses to conclude.

This is the measurement the provisional lane owes. WB serves a day's realization
report the following morning; whether it then revises that report is **not
known** — re-reading one 42 minutes later found it identical, which rules out
minute-by-minute top-ups and nothing else. Until it is answered, no day in the
tail may be presented as settled, so the answer has to accumulate as recorded
data rather than as an assumption somebody makes later.

Three rules, each with a way of going quietly wrong:

* a re-read WB would not serve must **not** be recorded as a verdict — marking it
  verified would retire the only report that still needs asking about, and the
  register would then read as evidence of stability that nobody ever collected;
* a report the weekly lane has since taken over must **not** be re-fetched — those
  rows belong to a settlement document now, and re-reading the daily copy would
  spend a request only to flip their ``report_id`` back to a provisional one;
* a digest that moved is a **finding**, not a warning to be tidied away.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import date

import pytest

from src.modules.finreports.models import DailyReportVerdict
from src.modules.finreports.repos import Fingerprint, PendingVerification
from src.modules.finreports.tasks import daily_tail
from src.modules.finreports.tasks.settlement import MissingReport, SettlementWalk
from src.modules.workspaces.contract import WorkspaceTokenBundle

pytestmark = pytest.mark.unit

WORKSPACE = uuid.UUID("019f657a-a70c-780a-ac98-f010a1916615")

#: The weekly lane has settled through here; anything later is the tail's.
SETTLED = date(2026, 9, 20)

_AT_INGEST = Fingerprint(rows=763, digest="a" * 32)


@dataclass
class _Run:
    """What one verification pass did, as seen from outside the process.

    Attributes:
        recorded: Every verdict written, in order — the pass's whole deliverable.
        fetched: The report ids a WB request was actually spent on, so «recorded
            without asking» is expressible as an assertion rather than as trust.
    """

    recorded: list[tuple[int, DailyReportVerdict, Fingerprint | None]] = field(default_factory=list)
    fetched: list[int] = field(default_factory=list)

    @property
    def verdicts(self) -> list[DailyReportVerdict]:
        """Just the verdicts, which is what most of these tests are about."""
        return [entry[1] for entry in self.recorded]


class _FakeSession:
    """A session that is opened, committed and never queried."""

    async def __aenter__(self) -> _FakeSession:
        return self

    async def __aexit__(self, *_exc: object) -> None:
        return None

    async def commit(self) -> None:
        return None


class _FakeWatermarkRepo:
    """The walk's own mark, level with the weekly coverage."""

    def __init__(self, _session: object) -> None:
        pass

    async def get(self, *, workspace_id: uuid.UUID) -> date:
        return SETTLED


class _FakeReportRepo:
    """The weekly coverage the frontier is derived from."""

    def __init__(self, _session: object) -> None:
        pass

    async def latest_settled_date(self, *, workspace_id: uuid.UUID) -> date | None:
        return SETTLED


@pytest.fixture
def verified(monkeypatch: pytest.MonkeyPatch):
    """Drive one workspace's verification pass over a scripted queue.

    The seams are the two things that leave the process: the WB walk and the
    repository. Everything asserted is what was *recorded*, because the recorded
    row is the whole deliverable of this pass.
    """

    def _install(
        *,
        pending: tuple[PendingVerification, ...],
        found: Fingerprint | None,
        walk_completes: bool = True,
    ) -> _Run:
        run = _Run()

        class _FakeDailyRepo:
            def __init__(self, _session: object) -> None:
                pass

            async def due_for_verification(self, **_kwargs: object):
                return pending

            async def fingerprint(self, *, workspace_id: uuid.UUID, report_id: int):
                assert found is not None, "fingerprint asked for on a path that must not fetch"
                return found

            async def record_verification(
                self,
                *,
                report_id: int,
                verdict: DailyReportVerdict,
                found: Fingerprint | None = None,
            ) -> None:
                run.recorded.append((report_id, verdict, found))

        async def _walk(*, reports: tuple[MissingReport, ...], **_kwargs: object) -> SettlementWalk:
            run.fetched.append(reports[0].report_id)
            return (
                SettlementWalk(10, 0, reports[0].date_to)
                if walk_completes
                else SettlementWalk(0, 1, None)
            )

        monkeypatch.setattr(daily_tail, "AsyncSessionLocal", _FakeSession)
        monkeypatch.setattr(daily_tail, "DailySettlementRepository", _FakeDailyRepo)
        monkeypatch.setattr(daily_tail, "SettlementWatermarkRepository", _FakeWatermarkRepo)
        monkeypatch.setattr(daily_tail, "FinancialReportRepository", _FakeReportRepo)
        monkeypatch.setattr(daily_tail, "walk_settlement_reports", _walk)
        return run

    return _install


def _pending(day: date) -> PendingVerification:
    """One queued report, as the first ingest recorded it."""
    return PendingVerification(
        report_id=938364620000000 + int(day.strftime("%Y%m%d")) % 1000000,
        day=day,
        rows=_AT_INGEST.rows,
        digest=_AT_INGEST.digest,
    )


def _tokens() -> WorkspaceTokenBundle:
    """A workspace with the «Финансы» token the re-read needs."""
    return WorkspaceTokenBundle(workspace_id=WORKSPACE, name="Демо", finance="a-finance-token")


async def test_the_same_rows_a_day_later_are_recorded_as_unchanged(verified) -> None:
    """The expected outcome, and the one the register is accumulating."""
    run = verified(pending=(_pending(date(2026, 9, 22)),), found=_AT_INGEST)

    counts = await daily_tail._verify_one_workspace(tokens=_tokens())

    assert run.verdicts == [DailyReportVerdict.UNCHANGED]
    assert counts["unchanged"] == 1
    assert counts["changed"] == 0


async def test_a_moved_digest_is_recorded_as_changed_with_both_halves(verified) -> None:
    """The finding that would mean a provisional day may not be shown as final.

    Both fingerprints are kept: «763 rows» against «765 rows» is the readable
    half, and the digest is what proves a change the counts would hide.
    """
    moved = Fingerprint(rows=765, digest="b" * 32)
    run = verified(pending=(_pending(date(2026, 9, 22)),), found=moved)

    counts = await daily_tail._verify_one_workspace(tokens=_tokens())

    assert run.verdicts == [DailyReportVerdict.CHANGED]
    assert run.recorded[0][2] == moved
    assert counts["changed"] == 1


async def test_the_same_row_count_with_a_different_digest_still_counts_as_changed(
    verified,
) -> None:
    """A restatement need not add rows, and usually would not.

    WB revising a figure in place is the shape this is watching for; a check that
    only counted rows would report it as stability.
    """
    restated = Fingerprint(rows=_AT_INGEST.rows, digest="c" * 32)
    run = verified(pending=(_pending(date(2026, 9, 22)),), found=restated)

    await daily_tail._verify_one_workspace(tokens=_tokens())

    assert run.verdicts == [DailyReportVerdict.CHANGED]


async def test_a_day_the_weekly_report_now_covers_is_superseded_without_a_request(
    verified,
) -> None:
    """Those rows belong to a settlement document; re-reading would only harm."""
    run = verified(pending=(_pending(SETTLED),), found=None)

    counts = await daily_tail._verify_one_workspace(tokens=_tokens())

    assert run.verdicts == [DailyReportVerdict.SUPERSEDED]
    assert run.recorded[0][2] is None, "no figure is invented for a report never fetched"
    assert run.fetched == [], "and no WB request is spent on it"
    assert counts["superseded"] == 1


async def test_a_re_read_wb_would_not_serve_records_no_verdict(verified) -> None:
    """An unanswered question is not a finding, and must stay on the queue."""
    run = verified(pending=(_pending(date(2026, 9, 22)),), found=None, walk_completes=False)

    counts = await daily_tail._verify_one_workspace(tokens=_tokens())

    assert run.recorded == [], (
        "recording a verdict here would retire the one report still needing a re-read"
    )
    assert counts["failed"] == 1
    assert counts["checked"] == 0
