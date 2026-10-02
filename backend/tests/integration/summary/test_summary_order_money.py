"""«Сводка»'s ordered money is in the кабинет's currency, at either price base.

«ДРР от заказов» divides advertising — in сомы on a Kyrgyz кабинет — by what
the orders were worth. At the seller's price that is WB's own funnel sum,
already in сомы; at the customer's price WB publishes none, so the WB sum is
scaled by the card's customer/seller price ratio. A day WB served no sum for is
the count at the snapshot price, converted at the Bank of Russia rate.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from src.modules.monitoring.contract import load_order_days
from src.modules.monitoring.models import CbrRate, PriceSnapshot, ProductCard, SalesFunnelDaily
from tests.integration.finreports.conftest import WORKSPACE

pytestmark = pytest.mark.integration

VALUED, UNVALUED = 9101, 9102
MONDAY, TUESDAY = date(2026, 7, 13), date(2026, 7, 14)


async def _seed(session: AsyncSession) -> None:
    session.add_all(
        [
            ProductCard(nm_id=VALUED, workspace_id=WORKSPACE, vendor_code="valued"),
            ProductCard(nm_id=UNVALUED, workspace_id=WORKSPACE, vendor_code="unvalued"),
            # Saturday's rate stands until Tuesday's: 1 ₽ = 1.140665 с.
            CbrRate(
                currency="KGS", rate_date=date(2026, 7, 11), nominal=100, value=Decimal("87.6681")
            ),
            # 10 orders at 4 000 ₽ that WB valued at 41 480 с.
            SalesFunnelDaily(
                stat_date=MONDAY,
                nm_id=VALUED,
                order_count=10,
                buyout_count=0,
                order_sum=Decimal("41480"),
                currency="KGS",
            ),
            PriceSnapshot(
                stat_date=MONDAY,
                nm_id=VALUED,
                seller_price=Decimal("4000"),
                customer_price=Decimal("3000"),
            ),
            # 2 orders WB served no sum for.
            SalesFunnelDaily(stat_date=TUESDAY, nm_id=UNVALUED, order_count=2, buyout_count=0),
            PriceSnapshot(
                stat_date=TUESDAY,
                nm_id=UNVALUED,
                seller_price=Decimal("1000"),
                customer_price=Decimal("800"),
            ),
        ]
    )
    await session.flush()


async def test_the_sellers_price_base_is_wbs_own_som_sum(
    db_session: AsyncSession, seeded: None
) -> None:
    await _seed(db_session)

    monday, _ = await load_order_days(
        db_session, workspace_id=WORKSPACE, date_from=MONDAY, date_to=TUESDAY
    )

    assert monday.amount_seller == Decimal("41480.00")


async def test_the_customers_price_base_scales_wbs_sum_by_the_price_ratio(
    db_session: AsyncSession, seeded: None
) -> None:
    await _seed(db_session)

    monday, _ = await load_order_days(
        db_session, workspace_id=WORKSPACE, date_from=MONDAY, date_to=TUESDAY
    )

    assert monday.amount_paid == Decimal("31110.00")  # 41 480 x 3 000 / 4 000


async def test_a_day_wb_did_not_value_is_converted_at_the_bank_rate(
    db_session: AsyncSession, seeded: None
) -> None:
    await _seed(db_session)

    _, tuesday = await load_order_days(
        db_session, workspace_id=WORKSPACE, date_from=MONDAY, date_to=TUESDAY
    )

    assert tuesday.amount_seller == Decimal("2281.33")  # 2 x 1 000 ₽ x 1.140665
    assert tuesday.amount_paid == Decimal("1825.07")  # 2 x 800 ₽ x 1.140665
