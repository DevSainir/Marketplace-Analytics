"""The statement must admit what it cannot verify.

Every figure on the P&L bar one comes from WB's own documents; the cost of goods
comes from the seller. This module pins the places where the statement has to say
so rather than quietly reporting a number:

* a SKU with no cost enters neither the COGS nor the coverage denominator, and a
  cost in the wrong currency is dropped rather than converted at an invented rate;
* an operation the taxonomy has no rule for is surfaced, not swallowed;
* a window still mid-backfill is flagged, because its withholdings are complete
  while its payout is not — a large, entirely plausible loss;
* a bucket covering part of a WB report is not labelled with the whole period;
* the «в т.ч. НДС» sub-line is summed over the rows the line above it is.

The closure arithmetic is in ``test_pnl_reconciles.py``; the fixture both share is
in ``conftest.py``.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from src.modules.finreports.models import ProductCostPrice
from src.modules.finreports.repos import PnlGrouping
from tests.integration.finreports.conftest import (
    _FILLER_OPER,
    COST_B,
    SKU_A,
    SKU_B,
    WINDOW_FROM,
    WINDOW_TO,
    WORKSPACE,
    _row,
    _service,
    _statement,
)

pytestmark = pytest.mark.integration


async def test_cogs_counts_only_the_skus_that_have_a_cost(
    db_session: AsyncSession, seeded: None
) -> None:
    """Cost of goods is net units × cost, per SKU, and reports its coverage.

    SKU A nets zero units (one sold, one refunded) and SKU B nets one, so COGS is
    B's cost alone — and coverage is 100 %, since both SKUs are costed.
    """
    total = (await _statement(db_session)).total

    assert total.cogs == COST_B
    assert total.cogs_units == 1
    assert total.cogs_coverage_pct == Decimal("100.00")


async def test_a_cost_in_the_wrong_currency_is_dropped_not_converted(
    db_session: AsyncSession, seeded: None
) -> None:
    """A RUB cost against a KGS settlement uncosts the SKU, with a caveat.

    Applying it anyway would produce a plausible margin off by an exchange rate —
    the single worst failure available to this page.
    """
    await db_session.execute(
        sa.update(ProductCostPrice)
        .where(ProductCostPrice.nm_id == SKU_B, ProductCostPrice.workspace_id == WORKSPACE)
        .values(currency="RUB")
    )
    await db_session.flush()

    total = (await _statement(db_session)).total

    assert total.cogs == Decimal(0)
    assert total.cogs_units == 0


async def test_the_advertising_share_of_the_deductions_is_broken_out(
    db_session: AsyncSession, seeded: None
) -> None:
    """«ВБ.Продвижение» gets its own figure inside «удержания».

    It is 95 % of everything WB has ever withheld from this seller and the only
    withheld cost they control; buried in «прочие удержания» it is invisible.
    """
    total = (await _statement(db_session)).total

    assert total.deductions.amount == Decimal("300")
    assert total.advertising == Decimal("300")


async def test_the_vat_sub_line_belongs_to_the_commission_it_sits_under(
    db_session: AsyncSession, seeded: None
) -> None:
    """«в т.ч. НДС комиссии» is summed over the rows the commission is.

    «Возмещение издержек по перевозке» reuses ``ppvz_vw`` and ``ppvz_vw_nds`` to
    express the VAT split of its OWN charge — 86 566 rows carrying −377 874.68
    and −47 746.32, which add to its 461 652.31 of ``rebill_logistic_cost``. It is
    not commission.

    Netting those in alongside the sales made the printed VAT 629 187.13 against a
    true 744 682.24 over the whole history, and gave it the WRONG SIGN on 16 of
    133 weekly reports. The sub-line must never be summed over a wider row set
    than the line it decomposes.
    """
    # A rebill row shaped like the real ones: its charge, split across the two
    # commission columns, with no sale attached.
    db_session.add(
        _row(
            97,
            _FILLER_OPER,
            quantity=2,
            rebill_logistic_cost=Decimal("110"),
            ppvz_vw=Decimal("-98"),
            ppvz_vw_nds=Decimal("-12"),
        )
    )
    await db_session.flush()

    total = (await _statement(db_session)).total

    # The sales' own VAT only — the rebill row's −12 must not reach it.
    assert total.wb_commission_vat == Decimal(0)
    assert total.rebill_logistic_cost == Decimal("115")
    # And the commission line, being a sale-side residual, is unmoved by it.
    assert total.wb_commission == _build_expected_commission(total)


def _build_expected_commission(total: object) -> Decimal:
    """The commission as the revenue block defines it, for the assertion above."""
    return (
        Decimal(total.revenue_paid)  # type: ignore[attr-defined]
        - Decimal(total.payout_from_sales)  # type: ignore[attr-defined]
        - Decimal(total.acquiring)  # type: ignore[attr-defined]
        - Decimal(total.wb_reward)  # type: ignore[attr-defined]
    )


async def test_a_partial_window_is_not_stamped_with_the_full_report_period(
    db_session: AsyncSession, seeded: None
) -> None:
    """A bucket covering part of a report is dated by what it actually holds.

    WB's stated period is the truth for the bucket only when the request covers
    the whole report. Ask for three days inside a week and the figures are three
    days' worth — labelling that «2026-07-13 — 2026-07-19» presents a partial
    total as a full week's.
    """
    inside = date(2026, 7, 14)

    partial = await _service(db_session).get_statement(
        workspace_id=WORKSPACE, date_from=inside, date_to=inside, grouping=PnlGrouping.WEEK
    )
    full = await _statement(db_session)

    assert full.buckets[0].date_from == WINDOW_FROM
    assert full.buckets[0].date_to == WINDOW_TO
    assert full.buckets[0].label == f"{WINDOW_FROM.isoformat()} — {WINDOW_TO.isoformat()}"
    assert all(b.date_to != WINDOW_TO for b in partial.buckets)


async def test_a_partly_backfilled_window_says_so(db_session: AsyncSession, seeded: None) -> None:
    """Sale rows with no revenue produce a caveat, not a silent understatement.

    The P&L columns were added zero-filled to an existing table, while logistics,
    storage and penalties always existed. A window mid-backfill therefore reports
    a full period of withholdings against a partial payout — a large, entirely
    plausible loss.
    """
    db_session.add(
        _row(
            98,
            "Продажа",
            nm_id=SKU_A,
            quantity=1,
            retail_amount=Decimal(0),
            ppvz_for_pay=Decimal(0),
        )
    )
    await db_session.flush()

    response = await _statement(db_session)

    assert any("не выгружены из WB" in note for note in response.notes)


async def test_advertising_is_reported_on_the_period_rows_too(
    db_session: AsyncSession, seeded: None
) -> None:
    """Every bucket carries its own advertising, not just the window total.

    Regression: advertising was first read off the reason drill-down, which is
    built once for the whole window. The dashboard's «Реклама» column therefore
    displayed 0 on every week while the total above it reported millions — a
    column that looks like data and is not.
    """
    for grouping in (PnlGrouping.WEEK, PnlGrouping.MONTH):
        response = await _statement(db_session, grouping)

        assert sum((b.advertising for b in response.buckets), Decimal(0)) == Decimal("300"), (
            grouping
        )


async def test_an_unrecognised_operation_is_reported_as_a_caveat(
    db_session: AsyncSession, seeded: None
) -> None:
    """A WB operation the taxonomy has no rule for is surfaced, not swallowed.

    Its money still reaches the charge lines (those sum whole columns), but its
    units and payout split do not — so the statement says so instead of quietly
    being a little bit wrong.
    """
    db_session.add(_row(99, "Совершенно новая операция WB", deduction=Decimal("1")))
    await db_session.flush()

    response = await _statement(db_session)

    assert any("Совершенно новая операция WB" in note for note in response.notes)
