"""Where «Сводка» gets each daily figure, and what it does when a source stops.

The reconciliation tests next door ask whether the arithmetic closes. These ask
the question underneath it: which WB surface answered, whether it was allowed to
(every monitoring table is keyed by ``nm_id`` alone, so a кабинет exists only as
a semijoin through ``product_card``), and what the page reports when the answer
is «мы не знаем» rather than a number.

Split out of ``test_summary_reconciles`` when that file reached the 500-line
ceiling; the fixtures are shared through the module it was split from.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.timeutils import moscow_today
from src.modules.monitoring.contract import load_ad_days, load_order_days
from src.modules.monitoring.models import OrderRecord, SalesFunnelDaily
from tests.integration.finreports.conftest import (
    OTHER_WORKSPACE,
    SKU_A,
    WINDOW_FROM,
    WINDOW_TO,
    WORKSPACE,
)
from tests.integration.summary.conftest import _service

pytestmark = pytest.mark.integration


async def test_the_daily_loaders_are_scoped_by_the_card_semijoin(
    db_session: AsyncSession, catalogued: None
) -> None:
    """Funnel and advertising days follow ``product_card``, not the bare nm_id.

    Neither table carries a workspace, so without the semijoin one tenant's
    orders would be summed into another's chart — WB ids are global.
    """
    mine = await load_order_days(
        db_session, workspace_id=WORKSPACE, date_from=WINDOW_FROM, date_to=WINDOW_TO
    )
    theirs = await load_order_days(
        db_session, workspace_id=OTHER_WORKSPACE, date_from=WINDOW_FROM, date_to=WINDOW_TO
    )

    assert [day.orders for day in mine] == [40, 60]
    assert theirs == []


async def test_a_day_outside_the_window_is_not_loaded(
    db_session: AsyncSession, catalogued: None
) -> None:
    """The window bounds the daily series, not just the settlement query."""
    ads = await load_ad_days(
        db_session,
        workspace_id=WORKSPACE,
        date_from=WINDOW_TO + timedelta(days=1),
        date_to=WINDOW_TO + timedelta(days=7),
    )

    assert ads == []


async def test_the_ordered_money_needs_a_price_and_says_so_when_it_has_none(
    db_session: AsyncSession, catalogued: None
) -> None:
    """«ДРР от заказов» divides by Σ(заказы x цена) — or by nothing at all.

    WB's funnel publishes counts, never a money volume, so a day reached only by
    the funnel is worth its orders priced at the seller's own snapshotted price.
    A day with no snapshot therefore has no volume: reporting zero there would
    divide that day's advertising by nothing and draw ДРР as infinite spend on a
    day that was merely unobserved. (Where the ORDERS feed reaches, each line
    carries its own price and no snapshot is needed — see
    `test_order_days_prefer_the_lines_wb_serves`.)
    """
    days = await load_order_days(
        db_session, workspace_id=WORKSPACE, date_from=WINDOW_FROM, date_to=WINDOW_TO
    )

    assert days[0].amount_seller == Decimal("100000")
    assert days[1].amount_seller is None


async def test_order_days_prefer_the_lines_wb_serves(
    db_session: AsyncSession, catalogued: None
) -> None:
    """The orders feed fills the days the funnel never reached, and prices them.

    «Воронка продаж» is what a кабинет has from the day we started harvesting
    it; the statistics orders feed answers from any date, which is the only way
    «Заказы» can cover the same period as the settlement. Two properties make
    that usable rather than merely present: a day the funnel does cover keeps
    the funnel's own count (it is what every other screen shows), and a day only
    the orders feed reaches carries its money from the lines themselves — each
    one has its price, so «ДРР от заказов» there needs no price snapshot at all.

    The buyout counter stays ``None`` on such a day on purpose: the funnel's
    cohort is its only source, and zero would read as «ничего не выкупили» on
    months that simply predate the harvest.

    A cancelled line is COUNTED as an order and priced with the rest. WB's
    ``isCancel`` covers the customer refusing at the pickup point, which happens
    for a fortnight afterwards — measured on the live кабинет, 4 % of yesterday
    and 56 % of ten days back — so excluding them would draw «Заказы в день» as
    a line that shrinks with age rather than one a seller can read.
    """
    older = WINDOW_FROM - timedelta(days=200)
    db_session.add_all(
        [
            OrderRecord(
                srid="srid-old",
                nm_id=SKU_A,
                order_date=older,
                price_with_disc=Decimal("3000"),
                finished_price=Decimal("2400"),
                last_change_date=datetime(2026, 1, 2, 3, 4),
            ),
            OrderRecord(
                srid="srid-cancelled",
                nm_id=SKU_A,
                order_date=older,
                is_cancel=True,
                price_with_disc=Decimal("9999"),
                finished_price=Decimal("9999"),
                last_change_date=datetime(2026, 1, 2, 3, 5),
            ),
        ]
    )
    await db_session.flush()

    days = {
        day.stat_date: day
        for day in await load_order_days(
            db_session, workspace_id=WORKSPACE, date_from=older, date_to=WINDOW_TO
        )
    }

    # The pre-funnel day: counted and priced from the lines, cancelled included.
    assert days[older].orders == 2
    assert days[older].amount_seller == Decimal("12999")
    assert days[older].amount_paid == Decimal("12399")
    assert days[older].buyouts is None
    # The funnel's own day is unchanged by any of this.
    assert days[WINDOW_FROM].orders == 40
    assert days[WINDOW_FROM].buyouts == 12


async def test_a_window_too_fresh_to_have_a_cohort_borrows_the_standing_one(
    db_session: AsyncSession, catalogued: None
) -> None:
    """«Выкуп» for the last week comes from «21-7 дней назад», and says so.

    The page opens on a week, and a week's own deliveries have barely been
    answered — measured on the live кабинет, 8 % of them, reading 22.2 % against
    a long-run 26-30 % because refusals arrive before buyouts. So the card falls
    back to the standing window rather than reporting a cohort that is merely
    early, and carries a flag the page turns into «за 21-7 дней до сегодня».
    """
    settled_day = moscow_today() - timedelta(days=14)
    db_session.add_all(
        [
            # Answered deliveries inside the standing window.
            SalesFunnelDaily(
                stat_date=settled_day,
                nm_id=SKU_A,
                order_count=100,
                buyout_count=27,
                cancel_count=73,
            ),
            # The fresh week: ordered, hardly answered.
            SalesFunnelDaily(
                stat_date=moscow_today() - timedelta(days=1),
                nm_id=SKU_A,
                order_count=100,
                buyout_count=2,
                cancel_count=6,
            ),
        ]
    )
    await db_session.flush()

    summary = await _service(db_session).build(
        db_session,
        workspace_id=WORKSPACE,
        date_from=moscow_today() - timedelta(days=6),
        date_to=moscow_today(),
    )

    assert summary.kpi.buyout_lagged is True
    assert (summary.kpi.buyouts, summary.kpi.buyout_decided) == (27, 100)
