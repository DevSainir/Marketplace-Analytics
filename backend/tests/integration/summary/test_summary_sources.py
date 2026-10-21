"""Where «Сводка» gets each daily figure, and what it does when a source stops.

The reconciliation tests next door ask whether the arithmetic closes. These ask
the question underneath it: which WB surface answered, whether it was allowed to
(every monitoring table is keyed by ``nm_id`` alone, so a workspace exists only as
a semijoin through ``product_card``), and what the page reports when the answer
is «we don't know» rather than a number.

Split out of ``test_summary_reconciles`` when that file reached the 500-line
ceiling; the fixtures are shared through the module it was split from.
"""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.timeutils import moscow_today
from src.modules.monitoring.contract import load_ad_days, load_order_days
from src.modules.monitoring.models import SalesFunnelDaily
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
    """«ДРР от заказов» divides by Σ(orders x price) — or by nothing at all.

    WB's funnel publishes counts, never a money volume, so a day is worth its
    orders priced at that day's own snapshot. A day with no snapshot therefore
    has no volume: reporting zero there would divide that day's advertising by
    nothing and draw DRR as infinite spend on a day that was merely unobserved.
    """
    days = await load_order_days(
        db_session, workspace_id=WORKSPACE, date_from=WINDOW_FROM, date_to=WINDOW_TO
    )

    assert days[0].amount_seller == Decimal("100000")
    assert days[1].amount_seller is None


async def test_a_window_too_fresh_to_have_a_cohort_borrows_the_standing_one(
    db_session: AsyncSession, catalogued: None
) -> None:
    """«Выкуп» for the last week comes from «21-7 дней назад», and says so.

    The page opens on a week, and a week's own deliveries have barely been
    answered — only a small fraction of them, reading several points below the
    long-run rate because refusals arrive before buyouts. So the card falls
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


async def test_a_half_answered_period_is_not_reported_as_its_own_rate(
    db_session: AsyncSession, catalogued: None
) -> None:
    """A week whose oldest days have barely answered borrows the standing rate.

    The lag alone does not save this one: for a week ending today, its oldest
    day or two DO clear the seven-day cut, and they are answered just past half.
    Such a cohort can read several points above the rate the workspace settles
    at, while a barely-answered one reads several points below it: half-answered
    is noisy in both directions, so the period answers for itself only once most of
    what it ordered has been answered.
    """
    today = moscow_today()
    db_session.add_all(
        [
            # The standing window: fully answered, 25 %.
            SalesFunnelDaily(
                stat_date=today - timedelta(days=14),
                nm_id=SKU_A,
                order_count=400,
                buyout_count=100,
                cancel_count=300,
            ),
            # The chosen week's one qualifying day: answered a third, reads 50 %.
            SalesFunnelDaily(
                stat_date=today - timedelta(days=8),
                nm_id=SKU_A,
                order_count=300,
                buyout_count=50,
                cancel_count=50,
            ),
            SalesFunnelDaily(
                stat_date=today - timedelta(days=3),
                nm_id=SKU_A,
                order_count=300,
                buyout_count=2,
                cancel_count=4,
            ),
        ]
    )
    await db_session.flush()

    summary = await _service(db_session).build(
        db_session,
        workspace_id=WORKSPACE,
        date_from=today - timedelta(days=8),
        date_to=today,
    )

    # The standing window overlaps the period's own qualifying day — it reaches
    # back 21 days and ends where the lag does — so the reported cohort is both
    # days, 150 of 500. What matters is that it is NOT the period's own 50 of
    # 100, and that the flag says where the figure came from.
    assert summary.kpi.buyout_lagged is True
    assert (summary.kpi.buyouts, summary.kpi.buyout_decided) == (150, 500)
