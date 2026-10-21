"""The per-SKU, per-day settlement cut, against the per-SKU window it must add up to.

The heatmap paints revenue, units and profit one day at a time from this cut,
and «По артикулам» shows the same article over the whole window. If a SKU's days
did not sum to its row, the two screens would disagree about one seller's money
with nothing on either to say which is right — so the reconciliation is exact,
no tolerance. Real Postgres because the cut is SQL over the rollup.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from src.modules.finreports.repos import (
    CostPriceRepository,
    PnlGrouping,
    PnlRepository,
    SkuExclusionRepository,
)
from src.modules.finreports.services.pnl.sku_report import sku_payout_net
from src.modules.finreports.services.pnl.sku_service import SkuReportService
from tests.integration.finreports.conftest import (
    COST_A,
    SKU_A,
    SKU_B,
    WINDOW_FROM,
    WINDOW_TO,
    WORKSPACE,
)

pytestmark = pytest.mark.integration


def _service(session: AsyncSession) -> SkuReportService:
    """Wire the per-SKU service on the test session."""
    return SkuReportService(
        pnl_repo=PnlRepository(session),
        cost_repo=CostPriceRepository(session),
        exclusion_repo=SkuExclusionRepository(session),
    )


async def test_a_skus_days_add_up_to_its_window_row(db_session: AsyncSession, seeded: None) -> None:
    """Revenue, units and payout summed over the days equal the SKU's own aggregate."""
    window = {"workspace_id": WORKSPACE, "date_from": WINDOW_FROM, "date_to": WINDOW_TO}
    by_sku = {
        aggregate.key: aggregate
        for aggregate in await PnlRepository(db_session).aggregate(
            **window, grouping=PnlGrouping.SKU
        )
    }

    days = await _service(db_session).get_sku_days(**window)

    for nm_id in (SKU_A, SKU_B):
        cells = [cell for cell in days.cells if cell.nm_id == nm_id]
        row = by_sku[nm_id]
        assert sum(c.revenue_seller for c in cells) == (
            row.sales_before_spp - row.returns_before_spp
        )
        assert sum(c.sold_units for c in cells) == row.sold_units
        assert sum(c.returned_units for c in cells) == row.returned_units
        assert sum(c.payout_net for c in cells) == sku_payout_net(row)


async def test_the_cut_holds_articles_only(db_session: AsyncSession, seeded: None) -> None:
    """Storage, fines and deductions billed to the workspace never land on an article."""
    days = await _service(db_session).get_sku_days(
        workspace_id=WORKSPACE, date_from=WINDOW_FROM, date_to=WINDOW_TO
    )

    assert {cell.nm_id for cell in days.cells} == {SKU_A, SKU_B}


async def test_another_tenants_sale_is_not_in_the_cut(
    db_session: AsyncSession, seeded: None
) -> None:
    """The seed carries a foreign 777 777 sale on the same day and article."""
    days = await _service(db_session).get_sku_days(
        workspace_id=WORKSPACE, date_from=WINDOW_FROM, date_to=WINDOW_TO
    )

    assert all(cell.payout_net < Decimal("777777") for cell in days.cells)
    assert days.currency == "KGS"


async def test_cost_of_goods_is_the_cost_price_times_net_units(
    db_session: AsyncSession, seeded: None
) -> None:
    """A day that sold one unit of A costs A's price; a refund-only day costs it back."""
    days = await _service(db_session).get_sku_days(
        workspace_id=WORKSPACE, date_from=WINDOW_FROM, date_to=WINDOW_TO
    )

    by_day = {cell.day: cell for cell in days.cells if cell.nm_id == SKU_A}
    assert by_day[WINDOW_FROM].cogs == COST_A
    assert by_day[WINDOW_TO].cogs == -COST_A


async def test_the_lean_sales_cut_matches_the_full_cut_cell_for_cell(
    db_session: AsyncSession, seeded: None
) -> None:
    """«ДРР от продаж» divides by the lean cut; it must be the full cut's revenue exactly.

    The lean cut exists because building the full one over a long window was
    most of the advertising page's load time. Two reads of one figure are only
    safe while they agree, so they are compared cell for cell, no tolerance.
    """
    window = {"workspace_id": WORKSPACE, "date_from": WINDOW_FROM, "date_to": WINDOW_TO}
    full = await _service(db_session).get_sku_days(**window)

    lean = await _service(db_session).get_sku_day_sales(**window)

    assert {(c.nm_id, c.day): c.revenue_seller for c in lean} == {
        (c.nm_id, c.day): c.revenue_seller for c in full.cells
    }
