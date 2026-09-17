"""«Выкуп» — WB's own definition, and the lag that makes it readable.

The card divides bought-out deliveries by ANSWERED ones (bought out plus
refused), not by orders. That is WB's definition, the one «Сравнение SKU» has
used since it was written, and the difference is not cosmetic: an order still in
transit belongs to neither half, so the figure does not start near zero and
climb for three weeks after every cohort.

Measured on «Демо» 2026-09-17, by the age of the ordering week:

===========  =====================  ====================
week age     answered / orders      buyout %, answered
===========  =====================  ====================
current       8 %                   22.2 %
1            58 %                   27.8 %
2            87 %                   26.2 %
3            95 %                   27.4 %
4-20         94-98 %                26.2-30.6 %
===========  =====================  ====================

The answered-based figure is inside its long-run band from the first full week;
the orders-based one reads 16 % there and needs a month. Only the CURRENT week
misleads, and it misleads downward — refusals arrive before buyouts — which is
what the lag excludes.
"""

from __future__ import annotations

from datetime import date

import pytest

from src.modules.monitoring.contract import OrderDay
from src.modules.summary.services.compose import buyout_cohort

pytestmark = pytest.mark.unit


def _day(day: date, *, buyouts: int | None, decided: int | None, orders: int = 100) -> OrderDay:
    """One ordered day carrying only what the cohort reads."""
    return OrderDay(
        stat_date=day,
        orders=orders,
        buyouts=buyouts,
        decided=decided,
        amount_seller=None,
        amount_paid=None,
    )


def test_a_cohort_nobody_has_answered_yet_is_not_counted() -> None:
    """A day the cohort pass has not refreshed adds nothing to either half.

    Its refusals are unknown, so counting its buyouts against a denominator
    without them would invent a cohort that answered perfectly. The matrix
    excludes such a day for the same reason, and that exclusion is what made
    «Процент выкупа» there agree with WB's own figure.
    """
    days = [
        _day(date(2026, 8, 10), buyouts=27, decided=100),
        _day(date(2026, 8, 11), buyouts=40, decided=None),
    ]

    assert buyout_cohort(days, until=date(2026, 9, 1)) == (27, 100)


def test_the_freshest_cohorts_are_left_out_of_the_ratio() -> None:
    """Days past the lag are excluded even when they have answered deliveries.

    Inside a fresh cohort the refusals land BEFORE the buyouts: on the live
    кабинет the current week showed 14 buyouts against 49 refusals — 22.2 % —
    while the same кабинет settles at 26-30 %. The lag is what keeps a
    half-answered week from being reported as a collapse in buyouts.
    """
    days = [
        _day(date(2026, 9, 1), buyouts=27, decided=100),
        _day(date(2026, 9, 15), buyouts=14, decided=63),
    ]

    assert buyout_cohort(days, until=date(2026, 9, 10)) == (27, 100)


def test_a_window_with_no_answered_day_reports_nothing_rather_than_zero() -> None:
    """Nothing to divide is «—», never 0 %.

    This is the page's own default period — the last week — and the service
    answers it from the standing window instead; what must never happen is a
    zero, which reads as «ничего не выкупают».
    """
    days = [_day(date(2026, 9, 15), buyouts=0, decided=None)]

    assert buyout_cohort(days, until=date(2026, 9, 16)) == (None, None)
