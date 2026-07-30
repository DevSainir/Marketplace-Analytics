"""The per-SKU report must reconcile against the same week, in real SQL.

The row arithmetic is unit-tested; what only a real database can prove is that
the per-SKU aggregation partitions the settlement rows the same way the window
total does — Σ rows + unallocated = totals with **no tolerance** — and that the
monitoring loaders, which query another module's tables through the contract,
actually deliver per-SKU orders and ad spend for the window.

Shares the miniature week in ``conftest.py``. The account-level rows there
(storage, the advertising invoice, the filler operation) are what make the
unallocated bucket non-trivial: a report that smeared them over SKUs would still
sum correctly and would be wrong row by row.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from src.modules.finreports.repos import CostPriceRepository, PnlRepository
from src.modules.finreports.services.pnl import SkuReportService
from src.modules.finreports.services.pnl.sku_report import UNALLOCATED_NAME
from src.modules.monitoring.contract import (
    ad_coverage,
    funnel_coverage,
    load_ad_spend_by_nm,
    load_orders_by_nm,
)
from src.modules.monitoring.models import AdvertisingStatDaily, SalesFunnelDaily
from tests.integration.finreports.conftest import (
    COST_A,
    OTHER_WORKSPACE,
    SKU_A,
    SKU_B,
    WINDOW_FROM,
    WINDOW_TO,
    WORKSPACE,
)

pytestmark = pytest.mark.integration


async def _report(session: AsyncSession):
    """Build the per-SKU report for the seeded window, loaders included."""
    service = SkuReportService(
        pnl_repo=PnlRepository(session), cost_repo=CostPriceRepository(session)
    )
    return await service.get_report(
        workspace_id=WORKSPACE,
        date_from=WINDOW_FROM,
        date_to=WINDOW_TO,
        orders=await load_orders_by_nm(session, date_from=WINDOW_FROM, date_to=WINDOW_TO),
        ad_spend=await load_ad_spend_by_nm(session, date_from=WINDOW_FROM, date_to=WINDOW_TO),
        funnel_span=await funnel_coverage(session, date_from=WINDOW_FROM, date_to=WINDOW_TO),
        ad_span=await ad_coverage(session, date_from=WINDOW_FROM, date_to=WINDOW_TO),
    )


@pytest.fixture
async def monitoring_seeded(db_session: AsyncSession) -> None:
    """Funnel and advertising history overlapping the seeded week."""
    db_session.add_all(
        [
            SalesFunnelDaily(
                stat_date=WINDOW_FROM,
                nm_id=SKU_A,
                open_count=100,
                cart_count=50,
                order_count=7,
                buyout_count=5,
                add_to_wishlist=0,
                cart_conversion=Decimal("50"),
                order_conversion=Decimal("14"),
                buyout_conversion=Decimal("71"),
            ),
            SalesFunnelDaily(
                stat_date=date(2026, 7, 15),
                nm_id=SKU_A,
                open_count=80,
                cart_count=40,
                order_count=4,
                buyout_count=3,
                add_to_wishlist=0,
                cart_conversion=Decimal("50"),
                order_conversion=Decimal("10"),
                buyout_conversion=Decimal("75"),
            ),
            AdvertisingStatDaily(
                stat_date=WINDOW_FROM,
                campaign_id=1,
                app_type=1,
                nm_id=SKU_A,
                views=1000,
                clicks=50,
                add_to_cart=10,
                spend=Decimal("1234.56"),
                orders=3,
                order_sum=Decimal("9000"),
            ),
        ]
    )
    await db_session.flush()


async def test_rows_plus_unallocated_reconcile_to_the_totals_in_real_sql(
    db_session: AsyncSession, seeded: None
) -> None:
    """Σ per-SKU + account bucket == the window total, to the kopeck.

    Two GROUP BYs over the same expressions; a mis-scoped ``CASE`` in either
    shows up here and nowhere else.
    """
    report = await _report(db_session)

    assert report.unallocated is not None
    for field in ("payout_net", "sales_amount", "logistics_total", "penalties_total"):
        summed = sum((getattr(r, field) for r in report.rows), Decimal(0)) + getattr(
            report.unallocated, field
        )
        assert summed == getattr(report.totals, field), field


async def test_account_level_charges_stay_out_of_the_sku_rows(
    db_session: AsyncSession, seeded: None
) -> None:
    """Storage, the ad invoice and the filler land in the unallocated bucket."""
    report = await _report(db_session)

    assert report.unallocated is not None
    assert report.unallocated.sa_name == UNALLOCATED_NAME
    # fixture books on nm_id 0 exactly as WB books most fines.
    assert report.unallocated.payout_net == Decimal("-370")
    # bucket's, and its category label survives to the row.
    assert [p.reason for p in report.unallocated.penalties] == [
    ]


async def test_the_monitoring_loaders_deliver_per_sku_figures(
    db_session: AsyncSession, seeded: None, monitoring_seeded: None
) -> None:
    """Orders sum across the window's days; ad spend arrives per SKU."""
    report = await _report(db_session)

    row_a = next(r for r in report.rows if r.nm_id == SKU_A)
    row_b = next(r for r in report.rows if r.nm_id == SKU_B)

    assert row_a.orders_units == 11  # 7 + 4 across two funnel days
    assert row_a.advertising == Decimal("1234.56")
    # Coverage exists, so a SKU that ran no ads is a true zero, not unknown.
    assert row_b.orders_units == 0
    assert row_b.advertising == Decimal(0)


async def test_without_monitoring_history_the_columns_are_unknown_not_zero(
    db_session: AsyncSession, seeded: None
) -> None:
    """No funnel/ad rows in the window → ``None`` + a caveat, never zeroes."""
    report = await _report(db_session)

    row_a = next(r for r in report.rows if r.nm_id == SKU_A)

    assert row_a.orders_units is None
    assert row_a.advertising is None
    assert any("Заказы" in note for note in report.notes)
    assert any("Реклама" in note for note in report.notes)


async def test_the_profit_uses_the_sellers_cost_and_the_promo_spend(
    db_session: AsyncSession, seeded: None, monitoring_seeded: None
) -> None:
    """Чистая прибыль = к перечислению − себестоимость − реклама, per SKU."""
    report = await _report(db_session)

    row_a = next(r for r in report.rows if r.nm_id == SKU_A)

    # SKU A: sale 900 payout − refund 450 payout, less its 120+80 logistics.
    assert row_a.payout_net == Decimal("250")
    assert row_a.cogs == COST_A * 0  # one sale, one refund → 0 net units
    assert row_a.net_profit == Decimal("250") - Decimal("1234.56")


async def test_a_foreign_workspace_stays_invisible(db_session: AsyncSession, seeded: None) -> None:
    """The 777 777 KGS row of the other tenant must not reach any figure."""
    report = await _report(db_session)

    assert all(r.sales_amount < Decimal("777777") for r in report.rows)
    assert report.totals.sales_amount < Decimal("777777")
    _ = OTHER_WORKSPACE  # documents what the assertion is about
