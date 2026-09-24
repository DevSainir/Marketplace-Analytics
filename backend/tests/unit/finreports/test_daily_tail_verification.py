"""The day-later check: what settles it for free, and what earns a request.

This is the measurement the provisional lane owes. WB serves a day's realization
report the following morning; whether it then revises that report is **not
known** — re-reading one 42 minutes later found it identical, which rules out
minute-by-minute top-ups and nothing else. Until it is answered, no day in the
tail may be presented as settled, so the answer has to accumulate as recorded
data rather than as an assumption somebody makes later.

**The screen is WB's own totals, listed again.** `sales-reports/list` carries
them per report, so one list answer covers every queued report at once and a
report whose totals have not moved needs no detail request at all. The
comparison is deliberately WB-against-WB: our own reconstruction of
``forPaySum`` was 128.26 KGS out on report 989286628 until «Коррекция продаж»
was found to be subtracted, and a screen built on our arithmetic would fire on
the next such difference of ours and hide the one that is WB's.

The rules each outcome has to keep, every one of which has a quiet failure:

* a re-read WB would not serve must **not** be recorded — marking it verified
  retires the only report that still needs asking about, and the register then
  reads as evidence of stability nobody collected;
* a report the weekly lane has taken over must **not** be fetched — those rows
  belong to a settlement document now, and re-reading the daily copy would spend
  a request only to flip their ``report_id`` back;
* a report WB has stopped listing is neither unchanged nor our failure to ask;
* and a moved digest is a **finding**, not a warning to be tidied away.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

import pytest

from src.integrations.wildberries.schemas import WBFinanceReportHeader
from src.modules.finreports.models import DailyReportVerdict
from src.modules.finreports.repos import Fingerprint, ListedTotals, PendingVerification
from src.modules.finreports.tasks.daily_tail import verify as daily_tail
from src.modules.finreports.tasks.settlement import MissingReport, SettlementWalk
from src.modules.workspaces.contract import WorkspaceTokenBundle

pytestmark = pytest.mark.unit

WORKSPACE = uuid.UUID("019f657a-a70c-780a-ac98-f010a1916615")

#: The weekly lane has settled through here; anything later is the tail's.
SETTLED = date(2026, 9, 20)
DAY = date(2026, 9, 22)

_AT_INGEST = Fingerprint(rows=763, digest="a" * 32)
_TOTALS = ListedTotals(
    for_pay=Decimal("175331.94"),
    retail_amount=Decimal("201113.96"),
    bank_payment=Decimal("138704.12"),
)
_REPORT_ID = 938364620260922


@dataclass
class _Run:
    """What one verification pass did, as seen from outside the process.

    Attributes:
        recorded: Every verdict written, in order — the pass's deliverable.
        fetched: Report ids a DETAIL request was spent on, so «settled without
            asking» is an assertion rather than trust.
        listed: The span of every list request that went out.
    """

    recorded: list[tuple[int, DailyReportVerdict, Fingerprint | None]] = field(default_factory=list)
    fetched: list[int] = field(default_factory=list)
    listed: list[tuple[date, date]] = field(default_factory=list)

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


def _header(totals: ListedTotals, *, report_id: int = _REPORT_ID) -> WBFinanceReportHeader:
    """A listed daily report carrying WB's own totals."""
    return WBFinanceReportHeader.model_validate(
        {
            "reportId": report_id,
            "dateFrom": DAY.isoformat(),
            "dateTo": DAY.isoformat(),
            "createDate": "2026-09-23",
            "currency": "KGS",
            "forPaySum": str(totals.for_pay),
            "retailAmountSum": str(totals.retail_amount),
            "bankPaymentSum": str(totals.bank_payment),
        }
    )


def _pending(
    *, day: date = DAY, totals: ListedTotals = _TOTALS, report_id: int = _REPORT_ID
) -> PendingVerification:
    """One queued report, as the first ingest recorded it."""
    return PendingVerification(
        report_id=report_id,
        day=day,
        rows=_AT_INGEST.rows,
        digest=_AT_INGEST.digest,
        totals=totals,
    )


def _tokens() -> WorkspaceTokenBundle:
    """A workspace with the «Финансы» token the check needs."""
    return WorkspaceTokenBundle(workspace_id=WORKSPACE, name="Демо", finance="a-finance-token")


@pytest.fixture
def verified(monkeypatch: pytest.MonkeyPatch):
    """Drive one workspace's verification over a scripted queue and list answer.

    The seams are the three things that leave the process: the list call, the
    detail walk, and the repository. Everything asserted is what was recorded and
    what was requested.
    """

    def _install(
        *,
        pending: tuple[PendingVerification, ...],
        served: tuple[WBFinanceReportHeader, ...],
        found: Fingerprint | None = None,
        walk_completes: bool = True,
        list_fails: bool = False,
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
                workspace_id: uuid.UUID,
                report_id: int,
                verdict: DailyReportVerdict,
                found: Fingerprint | None = None,
            ) -> None:
                run.recorded.append((report_id, verdict, found))

        async def _frontier(*, workspace_id: uuid.UUID) -> date:
            return SETTLED

        async def _list(*, tokens: WorkspaceTokenBundle, span: tuple[date, date]):
            run.listed.append(span)
            if list_fails:
                raise daily_tail.IntegrationError("WB did not answer")
            return list(served)

        async def _walk(*, reports: tuple[MissingReport, ...], **_kwargs: object) -> SettlementWalk:
            run.fetched.append(reports[0].report_id)
            return (
                SettlementWalk(10, 0, reports[0].date_to)
                if walk_completes
                else SettlementWalk(0, 1, None)
            )

        monkeypatch.setattr(daily_tail, "AsyncSessionLocal", _FakeSession)
        monkeypatch.setattr(daily_tail, "DailySettlementRepository", _FakeDailyRepo)
        monkeypatch.setattr(daily_tail, "settled_frontier", _frontier)
        monkeypatch.setattr(daily_tail, "list_daily", _list)
        monkeypatch.setattr(daily_tail, "walk_settlement_reports", _walk)
        return run

    return _install


async def test_totals_that_have_not_moved_settle_it_without_a_detail_request(verified) -> None:
    """The expected outcome, and the whole point of screening on the list.

    One list answer covers every queued report; before this each cost a detail
    request of its own against a bucket that serves one a minute.
    """
    run = verified(pending=(_pending(),), served=(_header(_TOTALS),))

    counts = await daily_tail._verify_one_workspace(tokens=_tokens())

    assert run.verdicts == [DailyReportVerdict.UNCHANGED]
    assert run.fetched == [], "a report whose totals stand needs no rows re-read"
    assert run.listed == [(DAY, DAY)], "and one list request covered it"
    assert counts["screened"] == 1
    assert counts["unchanged"] == 1


async def test_moved_totals_earn_a_re_read_and_a_moved_digest_is_a_finding(verified) -> None:
    """The outcome that would mean a provisional day may not be shown as final.

    Both fingerprints are kept: «763 rows» against «765 rows» is the readable
    half, and the digest is what proves a change the counts would hide.
    """
    moved = Fingerprint(rows=765, digest="b" * 32)
    run = verified(
        pending=(_pending(),),
        served=(_header(_TOTALS._replace(for_pay=Decimal("175400.00"))),),
        found=moved,
    )

    counts = await daily_tail._verify_one_workspace(tokens=_tokens())

    assert run.fetched == [_REPORT_ID]
    assert run.verdicts == [DailyReportVerdict.CHANGED]
    assert run.recorded[0][2] == moved
    assert counts["changed"] == 1
    assert counts["screened"] == 0


async def test_moved_totals_over_identical_rows_are_not_a_statement_change(verified) -> None:
    """WB restating its own header while serving the same rows.

    Worth a re-read — the screen cannot tell this from a real restatement — and
    not worth alarming about: the statement is built from the rows, and they did
    not move.
    """
    run = verified(
        pending=(_pending(),),
        served=(_header(_TOTALS._replace(bank_payment=Decimal("1.00"))),),
        found=_AT_INGEST,
    )

    counts = await daily_tail._verify_one_workspace(tokens=_tokens())

    assert run.fetched == [_REPORT_ID]
    assert run.verdicts == [DailyReportVerdict.UNCHANGED]
    assert counts["checked"] == 1


async def test_a_report_booked_before_totals_were_kept_falls_through_to_a_re_read(
    verified,
) -> None:
    """Absent totals are not agreement.

    The two reports already on file when this screen shipped have none, and
    concluding «unchanged» from nothing would have retired them unexamined.
    """
    nothing = ListedTotals(for_pay=None, retail_amount=None, bank_payment=None)
    run = verified(
        pending=(_pending(totals=nothing),), served=(_header(_TOTALS),), found=_AT_INGEST
    )

    await daily_tail._verify_one_workspace(tokens=_tokens())

    assert run.fetched == [_REPORT_ID]
    assert run.verdicts == [DailyReportVerdict.UNCHANGED]


async def test_a_report_wb_no_longer_lists_is_recorded_as_withdrawn(verified) -> None:
    """Neither unchanged nor our failure to ask: it has stopped existing there.

    Its rows are still in the statement, which is why this gets a verdict of its
    own rather than being folded into «changed».
    """
    run = verified(pending=(_pending(),), served=())

    counts = await daily_tail._verify_one_workspace(tokens=_tokens())

    assert run.verdicts == [DailyReportVerdict.WITHDRAWN]
    assert run.fetched == []
    assert counts["withdrawn"] == 1


async def test_a_day_the_weekly_report_now_covers_is_superseded_without_a_request(
    verified,
) -> None:
    """Those rows belong to a settlement document; re-reading would only harm."""
    run = verified(pending=(_pending(day=SETTLED),), served=(_header(_TOTALS),))

    counts = await daily_tail._verify_one_workspace(tokens=_tokens())

    assert run.verdicts == [DailyReportVerdict.SUPERSEDED]
    assert run.recorded[0][2] is None, "no figure is invented for a report never fetched"
    assert run.fetched == []
    assert counts["superseded"] == 1


async def test_a_re_read_wb_would_not_serve_records_no_verdict(verified) -> None:
    """An unanswered question is not a finding, and must stay on the queue."""
    run = verified(
        pending=(_pending(totals=_TOTALS._replace(for_pay=Decimal("1.00"))),),
        served=(_header(_TOTALS),),
        walk_completes=False,
    )

    counts = await daily_tail._verify_one_workspace(tokens=_tokens())

    assert run.recorded == [], (
        "recording a verdict here would retire the one report still needing a re-read"
    )
    assert counts["failed"] == 1
    assert counts["checked"] == 0


async def test_a_list_that_fails_records_nothing_at_all(verified) -> None:
    """Without WB's answer there is no screen.

    Guessing «unchanged» on a network blip would retire the whole queue, which is
    the one way this register could end up full of conclusions nobody reached.
    """
    run = verified(
        pending=(_pending(), _pending(report_id=938364620260921)),
        served=(),
        list_fails=True,
    )

    counts = await daily_tail._verify_one_workspace(tokens=_tokens())

    assert run.recorded == []
    assert run.fetched == []
    assert counts["failed"] == 2


async def test_the_re_read_budget_bounds_detail_requests_not_screening(verified) -> None:
    """A backlog of changed reports must not spend the bucket all at once.

    Screening is free and unbounded; fetching rows is one request a minute, so
    only that half is rationed — and a report left over stays queued rather than
    being recorded on a guess.
    """
    moved = _TOTALS._replace(for_pay=Decimal("999.00"))
    pending = tuple(_pending(report_id=_REPORT_ID - index, totals=moved) for index in range(5))
    served = tuple(_header(_TOTALS, report_id=_REPORT_ID - index) for index in range(5))
    run = verified(pending=pending, served=served, found=_AT_INGEST)

    await daily_tail._verify_one_workspace(tokens=_tokens())

    assert len(run.fetched) == daily_tail.DAILY_TAIL_VERIFY_LIMIT
    assert len(run.recorded) == daily_tail.DAILY_TAIL_VERIFY_LIMIT
