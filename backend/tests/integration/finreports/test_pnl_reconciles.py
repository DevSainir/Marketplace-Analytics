"""The P&L must reconcile against WB's own settled figures, in real SQL.

The statement's arithmetic is unit-tested against a pre-summed aggregate. What
that cannot prove is the aggregation itself: thirty ``SUM(CASE …)`` expressions
over one table, whose whole job is to partition hundreds of thousands of rows into disjoint buckets.
A single mis-scoped ``CASE`` double-counts a charge and the statement still looks
like a statement.

So this module asserts the properties that only a real database can:

* the revenue block reconstructs ``Σ ppvz_for_pay`` **exactly** — Python's
  ``Decimal`` and PostgreSQL's ``numeric`` agreeing, not just Python with itself;
* the buckets sum to the total, for every grouping;
* refunds settled in a *different* week than their sale land in the week they
  were settled — a large share of refunds do, and it is the property that
  makes the statement settlement-basis rather than order-basis;
* ``quantity`` on the operations WB uses as filler never reaches the unit count.

What the statement *admits* it cannot verify — cost coverage, unrecognised
operations, a partial backfill — is in ``test_pnl_caveats.py``. The fixture both
share is in ``conftest.py``.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from src.modules.finreports.repos import PnlGrouping, PnlRepository
from tests.integration.finreports.conftest import (
    SKU_A,
    WINDOW_FROM,
    WINDOW_TO,
    WORKSPACE,
    _row,
    _statement,
)

pytestmark = pytest.mark.integration


async def test_the_revenue_block_reconstructs_the_settled_payout_in_real_sql(
    db_session: AsyncSession, seeded: None
) -> None:
    """Paid − commission − acquiring − WB's agent fee == payout for sales.

    Exactly, with the sums produced by PostgreSQL's ``numeric`` rather than by
    Python. This is the assertion that the twenty-eight aggregate expressions
    partition the rows without overlap or omission.
    """
    total = (await _statement(db_session)).total

    residual = (
        total.revenue_paid
        - total.wb_commission
        - total.acquiring
        - total.wb_reward
        - total.payout_from_sales
    )

    assert residual == Decimal(0)


async def test_the_residual_commission_matches_the_one_wb_published(
    db_session: AsyncSession, seeded: None
) -> None:
    """The derived commission equals WB's own ``ppvz_vw + ppvz_vw_nds``.

    This is the cross-check the aggregate carries those two columns FOR, and it
    has to actually run: the commission line is a residual, so nothing else
    confirms it is a commission at all rather than a bucket absorbing whatever
    fails to reconcile. On the fixture the two agree exactly; on a full history
    they agree to within a fraction of a percent (the acquiring rows PNL.md §4
    documents).

    It is also the assertion that catches a widened row set. Aggregating those
    columns over every non-refund operation instead of the sale rows put them
    far apart across the history and gave them opposite signs on several weekly
    reports.
    """
    aggregate = (
        await PnlRepository(db_session).aggregate(
            workspace_id=WORKSPACE,
            date_from=WINDOW_FROM,
            date_to=WINDOW_TO,
            grouping=PnlGrouping.TOTAL,
        )
    )[0]
    total = (await _statement(db_session)).total

    reported = aggregate.wb_commission_reported + aggregate.wb_commission_vat

    assert reported == total.wb_commission


async def test_итого_к_оплате_matches_a_hand_summed_ledger(
    db_session: AsyncSession, seeded: None
) -> None:
    """The bottom line equals the fixture's charges added up by hand.

    Sales payout 900 + 1800, refund −450, compensation +70, less logistics 200,
    storage 40, penalty 25, deduction 300 and rebill 5.
    """
    total = (await _statement(db_session)).total

    expected = (
        Decimal("900")
        + Decimal("1800")
        - Decimal("450")
        + Decimal("70")
        - Decimal("200")
        - Decimal("40")
        - Decimal("25")
        - Decimal("300")
        - Decimal("5")
    )

    assert total.payout_total == expected


async def test_the_filler_operations_quantity_never_becomes_a_unit(
    db_session: AsyncSession, seeded: None
) -> None:
    """«Возмещение издержек» carries ``quantity = 2`` that is not a unit count.

    Every one of its rows has it, with no ``nm_id`` and no barcode. A bare
    ``SUM(quantity)`` adds two phantom units per row to the history and deflates
    every per-unit figure on the statement.
    """
    total = (await _statement(db_session)).total

    assert total.sold_units == 2
    assert total.returned_units == 1
    assert total.net_units == 1


async def test_a_compensation_raises_the_payout_without_becoming_revenue(
    db_session: AsyncSession, seeded: None
) -> None:
    """WB's compensations reach «к перечислению» but are not sales.

    They populate ``ppvz_for_pay`` and no other money column, so filtering the
    payout to «Продажа» drops them — and counting their ``quantity`` as a unit
    would charge COGS against stock that never shipped.
    """
    total = (await _statement(db_session)).total

    assert total.compensations == Decimal("70")
    assert total.revenue_paid == Decimal("1000") + Decimal("2000") - Decimal("500")
    assert total.payout_for_goods == total.payout_from_sales + Decimal("70")


async def test_a_correction_takes_its_sign_from_the_document_type(
    db_session: AsyncSession, seeded: None
) -> None:
    """A row under document type «Возврат» comes off the payout; any other goes on.

    WB serves every value positive and the same operation — «Коррекция продаж»,
    «Компенсация ущерба» — under both document types. Its own ``forPaySum``
    negates the «Возврат» ones and nothing else, which matches every report on
    file to the kopeck; a rule by operation name missed some.
    Neither row is revenue or a unit.
    """
    before = (await _statement(db_session)).total
    db_session.add_all(
        [
            _row(
                98,
                "Коррекция продаж",
                nm_id=SKU_A,
                quantity=1,
                doc_type_name="Продажа",
                ppvz_for_pay=Decimal("874.69"),
            ),
            _row(
                99,
                "Коррекция продаж",
                nm_id=SKU_A,
                quantity=1,
                doc_type_name="Возврат",
                ppvz_for_pay=Decimal("64.13"),
            ),
            _row(
                100,
                "Компенсация ущерба",
                nm_id=SKU_A,
                quantity=1,
                doc_type_name="Возврат",
                ppvz_for_pay=Decimal("500"),
            ),
        ]
    )
    await db_session.flush()

    after = (await _statement(db_session)).total

    assert after.payout_for_goods == before.payout_for_goods + Decimal("874.69") - Decimal(
        "64.13"
    ) - Decimal("500")
    assert after.revenue_paid == before.revenue_paid
    assert after.net_units == before.net_units


async def test_logistics_splits_into_forward_and_return_legs(
    db_session: AsyncSession, seeded: None
) -> None:
    """``delivery_rub`` partitions by WB's own counters, with no overlap.

    Exactly one of ``delivery_amount``/``return_amount`` is set on a logistics
    row — never both, never neither. Summing the column twice under two filters
    that both match would double the largest cost on the statement.
    """
    total = (await _statement(db_session)).total

    assert total.logistics_forward == Decimal("120")
    assert total.logistics_return == Decimal("80")
    assert total.logistics.amount == Decimal("200")


async def test_a_refund_settled_after_its_sale_belongs_to_the_settling_week(
    db_session: AsyncSession, seeded: None
) -> None:
    """The statement is settlement-basis: a refund lands where WB settled it.

    A large share of refunds settle in a different weekly report than their
    sale. Attributing them back to the sale's week would make every published
    week restate itself later — the opposite of a document you reconcile against
    a bank receipt.
    """
    total = (await _statement(db_session)).total

    # The refund is here; the 9 999 KGS sale it cancels settled last week and is
    # outside the window, so revenue is the two in-window sales less the refund.
    assert total.returned_units == 1
    assert total.revenue_paid == Decimal("1000") + Decimal("2000") - Decimal("500")
    assert total.payout_from_sales == Decimal("900") + Decimal("1800") - Decimal("450")


async def test_the_buckets_sum_to_the_total_for_every_grouping(
    db_session: AsyncSession, seeded: None
) -> None:
    """Whatever the cut, the parts add up to the whole.

    The total and the buckets run as separate queries over the same expressions;
    a mistake in the grouping key shows up here and nowhere else.
    """
    for grouping in (PnlGrouping.WEEK, PnlGrouping.MONTH, PnlGrouping.SKU):
        response = await _statement(db_session, grouping)

        assert sum((b.payout_total for b in response.buckets), Decimal(0)) == (
            response.total.payout_total
        ), grouping
        assert sum((b.revenue_paid for b in response.buckets), Decimal(0)) == (
            response.total.revenue_paid
        ), grouping
        assert sum(b.net_units for b in response.buckets) == response.total.net_units, grouping


async def test_another_tenants_settlements_are_invisible(
    db_session: AsyncSession, seeded: None
) -> None:
    """A foreign workspace's sale in the same week never enters the statement.

    Seeded as 777 777 KGS so a tenancy leak cannot hide inside a plausible total.
    """
    total = (await _statement(db_session)).total

    assert total.revenue_paid == Decimal("2500")
    assert total.sold_units == 2


async def test_the_neighbouring_week_is_outside_the_window(
    db_session: AsyncSession, seeded: None
) -> None:
    """Only settlements dated inside the window are counted."""
    total = (await _statement(db_session)).total

    assert total.settlement_rows == 10
