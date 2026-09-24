"""«Выручка заполнена только для N из M строк» — the caveat's own counts.

The P&L columns were added to an already-populated table zero-filled, so a
window whose rows were never refetched showed a full period of withholdings
against a partial payout — a large, plausible loss. A report that arrives short
has the same shape. This
counts the shortfall so the statement can say so.

Pinned here because the query was rewritten for speed: the operation moved from
a ``FILTER`` on the counts into the ``WHERE``, which is what lets the partial
sale index answer it (3.7 s → milliseconds on the largest кабинет) and is
exactly the kind of rewrite that can quietly change what is counted.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from src.modules.finreports.models import LogisticsTransaction
from src.modules.finreports.repos import PnlRepository
from tests.integration.finreports.conftest import (
    SKU_A,
    THIS_WEEK,
    WINDOW_FROM,
    WINDOW_TO,
    WORKSPACE,
)

pytestmark = pytest.mark.integration


async def test_a_fully_backfilled_window_reports_no_shortfall(
    db_session: AsyncSession, seeded: None
) -> None:
    """Every sale row carries revenue, so the two counts agree and no note fires."""
    sale_rows, with_revenue = await PnlRepository(db_session).revenue_coverage(
        workspace_id=WORKSPACE, date_from=WINDOW_FROM, date_to=WINDOW_TO
    )

    assert sale_rows == with_revenue
    assert sale_rows > 0


async def test_a_sale_row_left_zero_filled_is_counted_as_uncovered(
    db_session: AsyncSession, seeded: None
) -> None:
    """A sale with no ``retail_amount`` is the shortfall this exists to report.

    Counted as a SALE and not as a covered one — the distinction the caveat is
    built on, and the one a rewrite of this query would be likeliest to lose.
    """
    db_session.add(
        LogisticsTransaction(
            rrd_id=9_100,
            report_id=THIS_WEEK,
            workspace_id=WORKSPACE,
            nm_id=SKU_A,
            supplier_oper_name="Продажа",
            rr_dt=WINDOW_FROM,
            currency_name="KGS",
            quantity=1,
            retail_amount=Decimal("0"),
        )
    )
    await db_session.flush()
    repo = PnlRepository(db_session)

    sale_rows, with_revenue = await repo.revenue_coverage(
        workspace_id=WORKSPACE, date_from=WINDOW_FROM, date_to=WINDOW_TO
    )

    assert sale_rows == with_revenue + 1


async def test_a_refund_is_not_a_sale_row(db_session: AsyncSession, seeded: None) -> None:
    """Only sales are counted: refunds carry the same columns and are not the point."""
    repo = PnlRepository(db_session)

    sale_rows, _with_revenue = await repo.revenue_coverage(
        workspace_id=WORKSPACE, date_from=WINDOW_FROM, date_to=WINDOW_TO
    )

    # The fixture's week holds two «Продажа» rows and one «Возврат».
    assert sale_rows == 2
