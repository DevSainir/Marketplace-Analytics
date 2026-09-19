"""WB's settlement periods are derivable, and the derivation must not drift.

The hourly probe existed because nobody had measured this. Over all 142
reports «Демо» holds, ``create_dt`` is ``date_to + 1`` and a period ends on
a Sunday or a month end — so «is there a new report» is arithmetic plus one
indexed read, not 147 WB requests per week per seller.

The cases below are transcribed from the production history rather than
invented, because a rule this cheap to state is also cheap to get subtly wrong,
and the only evidence it is right is that it reproduces what WB actually did.
"""

from __future__ import annotations

from datetime import date

import pytest

from src.modules.finreports.services.publication import (
    missing_periods,
    period_from,
    periods_from,
)

pytestmark = pytest.mark.unit

#: Every settlement period «Демо» was served between 2026-03-30 — when WB
#: started splitting at month ends — and 2026-09-13, as ``(date_from, date_to)``.
#: Seven of them are shorter than a week and every one of those is a month
#: split, which is the fact the old code read as "WB publishes irregularly".
OBSERVED = [
    ("2026-03-30", "2026-03-31"),
    ("2026-04-01", "2026-04-05"),
    ("2026-04-06", "2026-04-12"),
    ("2026-04-13", "2026-04-19"),
    ("2026-04-20", "2026-04-26"),
    ("2026-04-27", "2026-04-30"),
    ("2026-05-01", "2026-05-03"),
    ("2026-05-04", "2026-05-10"),
    ("2026-05-11", "2026-05-17"),
    ("2026-05-18", "2026-05-24"),
    ("2026-05-25", "2026-05-31"),
    ("2026-06-01", "2026-06-07"),
    ("2026-06-08", "2026-06-14"),
    ("2026-06-15", "2026-06-21"),
    ("2026-06-22", "2026-06-28"),
    ("2026-06-29", "2026-06-30"),
    ("2026-07-01", "2026-07-05"),
    ("2026-07-06", "2026-07-12"),
    ("2026-07-13", "2026-07-19"),
    ("2026-07-20", "2026-07-26"),
    ("2026-07-27", "2026-07-31"),
    ("2026-08-01", "2026-08-02"),
    ("2026-08-03", "2026-08-09"),
    ("2026-08-10", "2026-08-16"),
    ("2026-08-17", "2026-08-23"),
    ("2026-08-24", "2026-08-30"),
    ("2026-08-31", "2026-08-31"),
    ("2026-09-01", "2026-09-06"),
    ("2026-09-07", "2026-09-13"),
]


@pytest.mark.parametrize(("start", "end"), OBSERVED)
def test_the_rule_reproduces_every_period_wb_actually_served(start: str, end: str) -> None:
    """Sunday-or-month-end, checked against WB rather than against itself."""
    period = period_from(date.fromisoformat(start))

    assert period.date_to == date.fromisoformat(end)


@pytest.mark.parametrize(("start", "end"), OBSERVED)
def test_the_report_is_stamped_the_day_after_the_period(start: str, end: str) -> None:
    """``create_dt = date_to + 1``, the invariant the whole schedule rests on.

    142 out of 142 on prod, over two and a half years. It is stated separately
    from the period rule because the two can fail apart: WB could keep its
    boundaries and change when it stamps, and the schedule would then probe a
    day early for ever.
    """
    period = period_from(date.fromisoformat(start))

    assert (period.created_on - period.date_to).days == 1


def test_periods_chain_with_no_gap_and_no_overlap() -> None:
    """Each period starts the day after the last, which is what lets the walk
    treat a settled-through date as a cursor at all."""
    chain = list(periods_from(date(2026, 3, 30), through=date(2026, 9, 14)))

    assert [(p.date_from.isoformat(), p.date_to.isoformat()) for p in chain] == OBSERVED


def test_a_period_wb_cannot_have_stamped_yet_is_not_offered() -> None:
    """The saving, stated as a property: on the six days a week when no report
    can exist, the gate has nothing to ask about.

    13.09 is a Sunday, so its report is stamped 14.09. Asked on the 14th the
    period is there; asked on the 13th — the day the old gate would still have
    spent a request on — there is nothing to ask about.
    """
    settled_through = date(2026, 9, 6)

    on_the_sunday = missing_periods(
        settled_through=settled_through, held_ends=[], today=date(2026, 9, 13)
    )
    on_the_monday = missing_periods(
        settled_through=settled_through, held_ends=[], today=date(2026, 9, 14)
    )

    assert on_the_sunday == []
    assert [p.date_to for p in on_the_monday] == [date(2026, 9, 13)]


def test_a_period_served_out_of_order_does_not_hide_the_one_behind_it() -> None:
    """The 31.08.2026 hole, as the regression it is.

    Report 983241109 covered 31.08 alone, was formed 01.09 and was not served
    until 09.09. Meanwhile the 01.09-06.09 report landed on 07.09 and pushed
    every forward-looking cursor past it, so nothing asked about 31.08 again
    and every workspace silently lost a settlement day.

    Here the question is not «what is newer than the newest thing I hold» but
    «which formed periods have no report», and 31.08 answers it whatever else
    has arrived since.
    """
    missing = missing_periods(
        settled_through=date(2026, 8, 30),
        held_ends=[date(2026, 9, 6), date(2026, 9, 13)],
        today=date(2026, 9, 19),
    )

    assert [p.date_to for p in missing] == [date(2026, 8, 31)]


def test_a_complete_history_asks_for_nothing() -> None:
    """The common case, and the one that has to cost zero WB requests."""
    missing = missing_periods(
        settled_through=date(2026, 9, 13),
        held_ends=[date(2026, 9, 13)],
        today=date(2026, 9, 19),
    )

    assert missing == []
