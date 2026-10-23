"""An article's sizes add up to the article's own row — in real SQL.

The size cut (``repos/pnl/sizes.py``) is a second copy of the article
aggregate's expressions, grouped by ``ts_name`` instead of ``nm_id``, because
the rollup carries no size. The unit test of the size report sums the size rows
it was handed and compares them with themselves, so a change to one copy of the
SQL and not the other would leave it green and the drill-down disagreeing with
the row it opens under.

So this compares the two SQL paths on the same seeded rows: Σ sizes against the
per-article aggregate, column by column, for every column the two share.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from src.modules.finreports.models import LogisticsTransaction
from src.modules.finreports.repos import PnlGrouping, PnlRepository
from tests.integration.finreports.conftest import (
    SKU_A,
    THIS_WEEK,
    WINDOW_FROM,
    WINDOW_TO,
    WORKSPACE,
)
from tests.support import wb_labels as wb

pytestmark = pytest.mark.integration

#: Every figure the size cut and the article aggregate both carry.
SHARED = (
    "sold_units",
    "returned_units",
    # The size cut's buyout denominator (sold / delivered); the article row
    # takes WB's own funnel percentage instead, but its aggregate still carries it.
    "delivered_units",
    "sales_gross",
    "returns_gross",
    "sales_before_spp",
    "returns_before_spp",
    "payout_sales",
    "payout_returns",
    "payout_other",
    "logistics_forward",
    "logistics_return",
    "logistics_unlegged",
    "penalties",
    "storage",
    "acceptance",
    "deductions",
    "additional_payments",
    "rebill_logistic_cost",
)


def _row(rrd_id: int, oper: str, size: str, **fields: object) -> LogisticsTransaction:
    """One settlement row of SKU_A in size ``size``, every other money column zero."""
    return LogisticsTransaction(
        rrd_id=rrd_id,
        report_id=THIS_WEEK,
        workspace_id=WORKSPACE,
        nm_id=SKU_A,
        ts_name=size,
        supplier_oper_name=oper,
        rr_dt=WINDOW_FROM,
        currency_name="KGS",
        **fields,
    )


async def test_the_sizes_sum_to_the_article_in_every_shared_column(
    db_session: AsyncSession, seeded: None
) -> None:
    """Σ size rows == the article's aggregate, for sales, returns, payout and every charge.

    Seeded with each kind of row the two copies treat differently — a return,
    a sale correction under both document types, logistics in both legs, a
    penalty — across two sizes and one sizeless row.
    """
    db_session.add_all(
        [
            _row(
                8001,
                wb.SALE,
                "48",
                doc_type_name=wb.SALE,
                quantity=1,
                retail_amount=Decimal("900"),
                retail_price_withdisc_rub=Decimal("1000"),
                ppvz_for_pay=Decimal("800"),
            ),
            _row(
                8002,
                wb.REFUND,
                "50",
                doc_type_name=wb.REFUND,
                quantity=1,
                retail_amount=Decimal("450"),
                retail_price_withdisc_rub=Decimal("500"),
                ppvz_for_pay=Decimal("400"),
            ),
            _row(
                8003,
                wb.SALES_CORRECTION,
                "48",
                doc_type_name=wb.SALE,
                quantity=1,
                ppvz_for_pay=Decimal("874.69"),
            ),
            _row(
                8004,
                wb.SALES_CORRECTION,
                "50",
                doc_type_name=wb.REFUND,
                quantity=1,
                ppvz_for_pay=Decimal("64.13"),
            ),
            _row(8005, wb.LOGISTICS, "48", delivery_amount=1, delivery_rub=Decimal("120")),
            _row(8006, wb.LOGISTICS, "50", return_amount=1, delivery_rub=Decimal("55")),
            _row(8007, wb.PENALTY, "", penalty=Decimal("25")),
        ]
    )
    await db_session.flush()
    repo = PnlRepository(db_session)

    sizes = await repo.sizes(
        workspace_id=WORKSPACE, nm_id=SKU_A, date_from=WINDOW_FROM, date_to=WINDOW_TO
    )
    articles = await repo.aggregate_from_detail(
        workspace_id=WORKSPACE, date_from=WINDOW_FROM, date_to=WINDOW_TO, grouping=PnlGrouping.SKU
    )
    article = next(a for a in articles if a.key == SKU_A)

    summed = {name: sum((getattr(s, name) for s in sizes), Decimal(0)) for name in SHARED}
    expected = {name: Decimal(getattr(article, name)) for name in SHARED}
    assert summed == expected


async def test_the_label_and_currency_come_from_the_article_s_own_rows(
    db_session: AsyncSession, seeded: None
) -> None:
    """The drill-down names its article and currency without reading the window's rollup."""
    repo = PnlRepository(db_session)

    label = await repo.sku_label(
        workspace_id=WORKSPACE, nm_id=SKU_A, date_from=WINDOW_FROM, date_to=WINDOW_TO
    )
    absent = await repo.sku_label(
        workspace_id=WORKSPACE, nm_id=1, date_from=WINDOW_FROM, date_to=WINDOW_TO
    )

    assert label[1] == "KGS"
    assert absent == ("", "")
