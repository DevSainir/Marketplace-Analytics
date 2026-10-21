"""The settlement rollup, against the detail it is derived from.

The rollup exists because the detail is 870 MB against a 128 MB
``shared_buffers``: any window covering most of it is a parallel seq scan, ~7 s a
pass, and «Вся история» was a timeout rather than a page. The same rows collapse
to tens of thousands of groups on (workspace, report, day, article).

A derived copy of a seller's money is only defensible if it cannot be wrong, so
what is pinned here is not the speed — it is the safety property that buys the
speed: **every read verifies the rollup against the detail's own row counts and
rebuilds whatever disagrees.** Stale, partial and empty all have to cost time and
nothing else.

Real Postgres because all of it is SQL: the aggregation, the row-count
comparison, the delete-and-upsert, and the group key that has to reproduce five
different cuts from one stored grain.
"""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.modules.finreports.models import LogisticsTransaction, SettlementDailyRollup
from src.modules.finreports.repos import (
    LogisticsTransactionRepository,
    PnlGrouping,
    PnlRepository,
    SkuUnits,
)
from src.modules.finreports.repos.pnl.rollup import SettlementRollup
from src.modules.finreports.services.ingestion.columns import TXN_UPDATE
from tests.integration.finreports.conftest import (
    LAST_WEEK,
    OTHER_WORKSPACE,
    SKU_A,
    SKU_B,
    THIS_WEEK,
    WINDOW_FROM,
    WINDOW_TO,
    WORKSPACE,
)

pytestmark = pytest.mark.integration

#: Every cut the statement offers. All five come out of the one stored grain, so
#: all five are worth comparing.
#: A report id for rows seeded outside the fixture's own two weeks.
LONG_REPORT = 784_000_000

CUTS = [
    PnlGrouping.TOTAL,
    PnlGrouping.DAY,
    PnlGrouping.WEEK,
    PnlGrouping.MONTH,
    PnlGrouping.SKU,
]


async def _rollup_rows(session: AsyncSession) -> int:
    """How many rows the rollup currently holds."""
    return int(await session.scalar(select(func.count()).select_from(SettlementDailyRollup)) or 0)


@pytest.mark.parametrize("grouping", CUTS, ids=lambda cut: str(cut))
async def test_the_rollup_reports_what_the_detail_reports(
    db_session: AsyncSession, seeded: None, grouping: PnlGrouping
) -> None:
    """Every figure of every cut matches a direct pass over the settlement rows.

    The stored columns ARE the direct pass's own expressions, summed at a finer
    grain, so this is the assertion that the slicing which derives them has not
    drifted — add a column to the aggregate and forget the rollup, and this
    fails for all five cuts at once.
    """
    repo = PnlRepository(db_session)

    through_rollup = await repo.aggregate(
        workspace_id=WORKSPACE, date_from=WINDOW_FROM, date_to=WINDOW_TO, grouping=grouping
    )
    from_detail = await repo.aggregate_from_detail(
        workspace_id=WORKSPACE, date_from=WINDOW_FROM, date_to=WINDOW_TO, grouping=grouping
    )

    assert through_rollup == from_detail


async def test_an_empty_rollup_is_a_slow_read_and_not_a_wrong_one(
    db_session: AsyncSession, seeded: None
) -> None:
    """A workspace nobody has ever summarised still gets the right figures.

    This is what makes the migration safe to deploy empty: a rollup that has
    never been built is simply a cache that misses everywhere, and the first
    read fills it.
    """
    assert await _rollup_rows(db_session) == 0

    aggregates = await PnlRepository(db_session).aggregate(
        workspace_id=WORKSPACE,
        date_from=WINDOW_FROM,
        date_to=WINDOW_TO,
        grouping=PnlGrouping.TOTAL,
    )

    assert aggregates[0].sales_gross > Decimal(0)
    assert await _rollup_rows(db_session) > 0


async def test_a_day_that_grew_after_it_was_summarised_is_rebuilt(
    db_session: AsyncSession, seeded: None
) -> None:
    """A back-filled settlement day must not be served from the old summary.

    WB serves back-dated rows days later (a day probed empty fills in after the
    walk has moved past it), so «this day was summarised once» is never a reason
    to trust the summary. The row COUNT is what catches it: the day now holds
    more rows than the rollup says it summed.
    """
    repo = PnlRepository(db_session)
    window = {"workspace_id": WORKSPACE, "date_from": WINDOW_FROM, "date_to": WINDOW_TO}
    before = (await repo.aggregate(**window, grouping=PnlGrouping.TOTAL))[0]

    db_session.add(
        LogisticsTransaction(
            rrd_id=9_001,
            report_id=THIS_WEEK,
            workspace_id=WORKSPACE,
            nm_id=SKU_A,
            supplier_oper_name="Продажа",
            rr_dt=WINDOW_FROM,
            currency_name="KGS",
            quantity=1,
            retail_amount=Decimal("5000"),
            ppvz_for_pay=Decimal("4500"),
        )
    )
    await db_session.flush()

    after = (await PnlRepository(db_session).aggregate(**window, grouping=PnlGrouping.TOTAL))[0]

    assert after.sales_gross == before.sales_gross + Decimal("5000")
    assert after.rows == before.rows + 1


async def test_a_row_rewritten_in_place_is_not_served_from_the_old_summary(
    db_session: AsyncSession, seeded: None
) -> None:
    """A settled row re-harvested with new figures reaches the next read.

    The row count cannot see this: the day holds as many rows as before. And it
    is the ordinary case, not an edge — the weekly report rewrites every row the
    provisional daily lane wrote under a new ``report_id``, and a daily report
    WB restates is re-upserted with its new amounts. So the write path forgets
    the days it touched, and the next read rebuilds them.
    """
    repo = PnlRepository(db_session)
    window = {"workspace_id": WORKSPACE, "date_from": WINDOW_FROM, "date_to": WINDOW_TO}
    before = (await repo.aggregate(**window, grouping=PnlGrouping.TOTAL))[0]
    row = (
        (
            await db_session.execute(
                select(LogisticsTransaction.__table__).where(LogisticsTransaction.rrd_id == 1)
            )
        )
        .mappings()
        .one()
    )

    await LogisticsTransactionRepository(db_session).bulk_upsert(
        [{**row, "report_id": LAST_WEEK, "retail_amount": row["retail_amount"] + 700}],
        conflict_columns=["rrd_id"],
        update_columns=TXN_UPDATE,
    )

    after = (await PnlRepository(db_session).aggregate(**window, grouping=PnlGrouping.TOTAL))[0]
    assert after.rows == before.rows
    assert after.sales_gross == before.sales_gross + Decimal("700")


async def test_a_row_that_left_the_detail_leaves_the_rollup_too(
    db_session: AsyncSession, seeded: None
) -> None:
    """A correction that removes a row must not survive as a phantom.

    The rebuild deletes the day before writing it, rather than upserting alone:
    an article whose LAST row moved elsewhere would otherwise keep a stale group
    that every total still counts. Row 2 is exactly that — SKU_B's only row on
    the window's closing day — and a row with surviving siblings would not
    exercise this at all, because an upsert overwrites those.
    """
    window = {"workspace_id": WORKSPACE, "date_from": WINDOW_FROM, "date_to": WINDOW_TO}
    await PnlRepository(db_session).aggregate(**window, grouping=PnlGrouping.TOTAL)

    await db_session.execute(
        LogisticsTransaction.__table__.delete().where(LogisticsTransaction.rrd_id == 2)
    )
    await db_session.flush()

    fresh = PnlRepository(db_session)
    after = (await fresh.aggregate(**window, grouping=PnlGrouping.TOTAL))[0]
    from_detail = (await fresh.aggregate_from_detail(**window, grouping=PnlGrouping.TOTAL))[0]

    assert after == from_detail
    assert after.sales_gross < Decimal("2960327.27")


async def test_a_rollup_corrupted_by_hand_is_not_believed(
    db_session: AsyncSession, seeded: None
) -> None:
    """Editing the cache directly changes nothing a reader sees.

    The blunt version of the safety property: whatever ends up in this table,
    the row counts have to agree with the detail before anything is served from
    it, and they cannot be made to agree by editing a figure.
    """
    repo = PnlRepository(db_session)
    window = {"workspace_id": WORKSPACE, "date_from": WINDOW_FROM, "date_to": WINDOW_TO}
    honest = (await repo.aggregate(**window, grouping=PnlGrouping.TOTAL))[0]

    await db_session.execute(
        SettlementDailyRollup.__table__.update().values(
            sales_gross=Decimal("999999"), rows=SettlementDailyRollup.rows + 1
        )
    )
    await db_session.flush()

    fresh = PnlRepository(db_session)
    assert (await fresh.aggregate(**window, grouping=PnlGrouping.TOTAL))[0] == honest


async def test_the_rollup_is_scoped_to_its_own_кабинет(
    db_session: AsyncSession, seeded: None
) -> None:
    """One tenant's summary never answers for another's window.

    Both tenants' rows sit in the same week of the same table, and the rollup
    keys on the workspace exactly as the detail does.
    """
    repo = PnlRepository(db_session)
    window = {"date_from": WINDOW_FROM, "date_to": WINDOW_TO, "grouping": PnlGrouping.TOTAL}

    mine = (await repo.aggregate(workspace_id=WORKSPACE, **window))[0]
    theirs = (await repo.aggregate(workspace_id=OTHER_WORKSPACE, **window))[0]

    assert theirs.sales_gross == Decimal("777777")
    assert mine.sales_gross != theirs.sales_gross


async def test_a_window_outside_the_data_costs_nothing_and_says_nothing(
    db_session: AsyncSession, seeded: None
) -> None:
    """A window WB has settled nothing in builds no rollup rows."""
    rollup = SettlementRollup(db_session)
    future = WINDOW_TO + timedelta(days=400)

    rebuilt = await rollup.ensure_fresh(
        workspace_id=WORKSPACE, date_from=future, date_to=future + timedelta(days=30)
    )

    assert rebuilt == 0
    assert await _rollup_rows(db_session) == 0


async def test_the_second_read_of_a_window_rebuilds_nothing(
    db_session: AsyncSession, seeded: None
) -> None:
    """The point of the cache: pay once, then stop paying.

    Asserted on the repair counter rather than on a clock, so it says what it
    means on any machine.
    """
    rollup = SettlementRollup(db_session)
    window = {"workspace_id": WORKSPACE, "date_from": WINDOW_FROM, "date_to": WINDOW_TO}

    first = await rollup.ensure_fresh(**window)
    second = await SettlementRollup(db_session).ensure_fresh(**window)

    assert first > 0
    assert second == 0


async def test_rows_with_no_settlement_date_are_outside_every_window(
    db_session: AsyncSession, seeded: None
) -> None:
    """WB leaves ``rr_dt`` blank occasionally; such a row belongs to no window.

    It is excluded from the rollup for the same reason it is excluded from every
    windowed query — and, crucially, from the row-count comparison too, or its
    presence would make every day of the workspace look permanently stale and
    rebuild the whole history on every single read.
    """
    db_session.add(
        LogisticsTransaction(
            rrd_id=9_002,
            report_id=THIS_WEEK,
            workspace_id=WORKSPACE,
            nm_id=SKU_A,
            supplier_oper_name="Продажа",
            rr_dt=None,
            currency_name="KGS",
            quantity=1,
            retail_amount=Decimal("1234"),
        )
    )
    await db_session.flush()
    rollup = SettlementRollup(db_session)
    window = {"workspace_id": WORKSPACE, "date_from": WINDOW_FROM, "date_to": WINDOW_TO}

    await rollup.ensure_fresh(**window)

    assert await SettlementRollup(db_session).ensure_fresh(**window) == 0


async def test_a_month_cut_matches_the_detail_across_a_month_boundary(
    db_session: AsyncSession, seeded: None
) -> None:
    """The monthly cut is derived from the day, so its boundary must hold.

    The rollup stores days and truncates them to months on read; a fixture that
    lives inside one month would never exercise that, so this one reaches into
    the neighbouring week the fixture also seeds.
    """
    repo = PnlRepository(db_session)
    window = {"workspace_id": WORKSPACE, "date_from": date(2026, 7, 1), "date_to": WINDOW_TO}

    assert await repo.aggregate(**window, grouping=PnlGrouping.MONTH) == (
        await repo.aggregate_from_detail(**window, grouping=PnlGrouping.MONTH)
    )


async def test_a_history_of_months_is_built_in_one_pass(
    db_session: AsyncSession, seeded: None
) -> None:
    """A first read reaching back months rebuilds every day, not the last batch.

    The rebuild is an ``INSERT … SELECT``: the groups are written by Postgres
    and never travel through Python, which is what keeps a 400-day first read at
    the same memory as a one-day one. Reading them out and sending them back was
    the previous shape, and on production it was killed by the worker's memory
    cap rather than returning a page.

    A window this wide is what separates the two: the fixture's own week fits in
    any implementation, and only a window of months exercises the day list, the
    grouping and the conflict clause at the size the workspace actually has.
    """
    span = 90
    start = WINDOW_FROM - timedelta(days=span)
    db_session.add_all(
        [
            LogisticsTransaction(
                rrd_id=20_000 + offset,
                report_id=LONG_REPORT,
                workspace_id=WORKSPACE,
                nm_id=SKU_A,
                supplier_oper_name="Продажа",
                rr_dt=start + timedelta(days=offset),
                currency_name="KGS",
                quantity=1,
                retail_amount=Decimal("100"),
                ppvz_for_pay=Decimal("90"),
            )
            for offset in range(span)
        ]
    )
    await db_session.flush()
    repo = PnlRepository(db_session)
    window = {"workspace_id": WORKSPACE, "date_from": start, "date_to": WINDOW_TO}

    through_rollup = await repo.aggregate(**window, grouping=PnlGrouping.TOTAL)

    assert through_rollup == await repo.aggregate_from_detail(**window, grouping=PnlGrouping.TOTAL)
    # The 90 seeded days plus the three sales the fixture's own two weeks hold.
    assert through_rollup[0].sold_units == span + 3


async def test_the_cost_price_coverage_list_counts_what_the_detail_counts(
    db_session: AsyncSession, seeded: None
) -> None:
    """Sold and returned units per SKU, by operation, in the window only.

    The cost-price page's list of SKUs that still need a cost. Read off the
    detail it was the page's entire 8.4 s (30-35 s under load); the rollup's
    units are the same expressions. The compensation row on SKU_B carries a
    quantity and is neither a sale nor a refund, and last week's sale of SKU_A
    lies outside the window — either leaking in would inflate the counts.
    """
    repo = PnlRepository(db_session)

    units = await repo.sku_units(workspace_id=WORKSPACE, date_from=WINDOW_FROM, date_to=WINDOW_TO)

    assert sorted(units, key=lambda u: u.nm_id) == [
        SkuUnits(nm_id=SKU_A, vendor_code=f"sku-{SKU_A}", sold_units=1, returned_units=1),
        SkuUnits(nm_id=SKU_B, vendor_code=f"sku-{SKU_B}", sold_units=1, returned_units=0),
    ]
