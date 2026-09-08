"""What the settlement walk is allowed to certify as settled.

The harvest's watermark decides which days are ever asked for again: the
freshness gate probes only the days *after* it, and `_walk_span` starts there.
So a watermark that runs ahead of the rows actually fetched does not merely
mislead a dashboard — it closes the door on the missing days permanently.

That is not hypothetical. On 2026-09-07 the mark was read from
`max(financial_report.date_to)`, the period WB *states* on the header, which is
written from the first page that lands. Four of five workspaces held one day of
the 01.09-06.09 week while the header claimed all six; the gate then probed
07.09, found nothing, and skipped. «К перечислению» read 12 954 against WB's own
385 925.6 and nothing raised.

So these pin the rule that makes it unrepresentable: a walk certifies the
**unbroken prefix** of windows it completed, and nothing beyond the first one
that stopped early. A single high-water date cannot describe a gap, so it must
never be handed one that has a gap behind it.
"""

from __future__ import annotations

import uuid
from datetime import date

import pytest

from src.modules.finreports.tasks import settlement as settlement_module
from src.modules.finreports.tasks.settlement import settlement_windows, walk_settlement_windows
from src.modules.workspaces.contract import WorkspaceTokenBundle

pytestmark = pytest.mark.unit

#: Two whole windows, so a prefix and a gap are both expressible.
SPAN_FROM, SPAN_TO = date(2026, 9, 1), date(2026, 9, 14)
FIRST_WINDOW_END = date(2026, 9, 7)
SECOND_WINDOW_END = date(2026, 9, 14)


def _bundle() -> WorkspaceTokenBundle:
    """A workspace with the settlement token the walk requires."""
    return WorkspaceTokenBundle(
        workspace_id=uuid.uuid4(),
        name="Демо",
        statistics="a-statistics-token",
        internal_features=False,
    )


@pytest.fixture
def windows_that(monkeypatch: pytest.MonkeyPatch):
    """Script each window's outcome, in order, replacing the WB round trip.

    `_harvest_window` is the seam because it is the part that talks to WB and to
    PostgreSQL; what is under test is the rule `walk_settlement_windows` applies
    to its answers. The assertions are all on the returned value.
    """

    def _install(*outcomes: bool) -> None:
        remaining = list(outcomes)

        async def _fake_window(*, window_from, window_to, **_: object) -> tuple[int, bool]:
            complete = remaining.pop(0)
            return (10 if complete else 0), complete

        monkeypatch.setattr(settlement_module, "_harvest_window", _fake_window)

    return _install


async def test_the_span_splits_into_the_two_windows_these_tests_assume() -> None:
    """Guards the fixture's premise, so a changed window size fails here first."""
    windows = settlement_windows(date_from=SPAN_FROM, date_to=SPAN_TO)

    assert [end for _start, end in windows] == [FIRST_WINDOW_END, SECOND_WINDOW_END]


async def test_a_fully_walked_span_certifies_its_last_day(windows_that) -> None:
    """Every window finished, so the mark reaches the end of the span."""
    windows_that(True, True)

    walk = await walk_settlement_windows(
        tokens=_bundle(), date_from=SPAN_FROM, date_to=SPAN_TO, build_ingestion=object()
    )

    assert walk.windows_failed == 0
    assert walk.completed_through == SECOND_WINDOW_END


async def test_a_window_that_stopped_early_holds_the_mark_at_the_one_before_it(
    windows_that,
) -> None:
    """The prefix is certified; the window that stopped early is not.

    The next tick's span then starts at the first window's end and asks for the
    second week again — which is the whole recovery mechanism.
    """
    windows_that(True, False)

    walk = await walk_settlement_windows(
        tokens=_bundle(), date_from=SPAN_FROM, date_to=SPAN_TO, build_ingestion=object()
    )

    assert walk.windows_failed == 1
    assert walk.completed_through == FIRST_WINDOW_END


async def test_a_later_window_cannot_certify_the_gap_before_it(windows_that) -> None:
    """The incident, inverted: window two succeeding must not close window one.

    This is the case a naive `max(day I fetched something for)` gets wrong, and
    it is the one that actually happened — the day that landed was the LAST day
    of the week, while the days before it were never fetched. Certifying it
    would put the mark past a gap that nothing would ever ask for again.
    """
    windows_that(False, True)

    walk = await walk_settlement_windows(
        tokens=_bundle(), date_from=SPAN_FROM, date_to=SPAN_TO, build_ingestion=object()
    )

    assert walk.rows > 0
    assert walk.windows_failed == 1
    assert walk.completed_through is None


async def test_a_workspace_without_a_settlement_token_certifies_nothing(
    windows_that,
) -> None:
    """No token is not the same as a covered span, and must not read as one."""
    windows_that()
    tokenless = WorkspaceTokenBundle(workspace_id=uuid.uuid4(), name="NEVA", internal_features=False)

    walk = await walk_settlement_windows(
        tokens=tokenless, date_from=SPAN_FROM, date_to=SPAN_TO, build_ingestion=object()
    )

    assert walk == (0, 0, None)
