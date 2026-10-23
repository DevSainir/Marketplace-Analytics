"""Builders for the "Summary" unit tests.

Shared because the two test files exercise the same window from different
angles, and because a hand-written P&L row carries thirty fields: duplicating
that per file is how the two halves start testing different reports.

Every field the summary does NOT read is filled with a zero rather than left
out. The alternative — a builder that tracks the report's full shape — turns
adding one column to the P&L's per-SKU report into an edit across every test here.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from src.modules.finreports.contract import PnlSkuReportResponse, PnlSkuRow, PnlStatement
from src.modules.finreports.schemas.pnl import PnlSection
from src.modules.finreports.schemas.sku_report import PnlDashboard

ZERO = Decimal(0)


def make_row(
    *,
    nm_id: int,
    revenue: str,
    payout_net: str,
    cost_price: str | None,
    net_profit: str | None,
    sold_units: int = 10,
    returned_units: int = 0,
    subject: str = "Trousers",
    brand: str = "NEVA",
    penalties_total: str = "0",
) -> PnlSkuRow:
    """One SKU row, carrying only the fields "Summary" reads.

    The rest are filled with zeroes rather than omitted: the summary must keep
    working when the report grows a column, and a builder that tracks every
    field would make that a test-wide edit.
    """
    return PnlSkuRow(
        nm_id=nm_id,
        sa_name=f"SKU-{nm_id}",
        subject_name=subject,
        brand_name=brand,
        is_excluded=False,
        orders_units=None,
        sold_units=sold_units,
        returned_units=returned_units,
        return_rate_pct=None,
        buyout_units=None,
        decided_units=None,
        buyout_pct=None,
        sales_amount=Decimal(revenue),
        returns_amount=ZERO,
        revenue_paid=Decimal(revenue),
        revenue_seller_price=Decimal(revenue) * 2,
        spp_amount=ZERO,
        spp_pct=None,
        average_cheque=None,
        logistics_forward=ZERO,
        logistics_return=ZERO,
        logistics_total=ZERO,
        logistics_pct=None,
        penalties_total=Decimal(penalties_total),
        penalties=[],
        cost_price=None if cost_price is None else Decimal(cost_price),
        cogs=None if cost_price is None else Decimal(cost_price) * sold_units,
        advertising=ZERO,
        advertising_pct=None,
        ad_bonus=ZERO,
        advertising_cash=ZERO,
        payout_for_goods=Decimal(payout_net),
        payout_net=Decimal(payout_net),
        net_profit=None if net_profit is None else Decimal(net_profit),
        net_profit_pct=None,
        roi_pct=None,
    )


def make_report(
    rows: list[PnlSkuRow],
    *,
    totals: PnlSkuRow,
    other_deductions: str = "0",
    dashboard_advertising: str = "0",
) -> PnlSkuReportResponse:
    """A report around the given rows.

    Two dashboard figures are settable because "Summary" reads them: the
    account-level withholdings and the advertising invoices inside them, which
    the "Penalties and deductions" card has to take back out.
    """
    return PnlSkuReportResponse(
        date_from=date(2026, 7, 15),
        date_to=date(2026, 9, 6),
        currency="KGS",
        rows=rows,
        unallocated=None,
        totals=totals,
        dashboard=PnlDashboard(
            sales=ZERO,
            paid=ZERO,
            sold_units=0,
            returned_units=0,
            return_rate_pct=None,
            logistics=ZERO,
            logistics_pct=None,
            cogs=ZERO,
            uncosted_count=0,
            payout_net=ZERO,
            other_deductions=Decimal(other_deductions),
            advertising=Decimal(dashboard_advertising),
            excluded_count=0,
        ),
        notes=[],
    )


def make_day(
    *, day: date, revenue: str, margin_profit: str, advertising: str = "0"
) -> PnlStatement:
    """One settlement-date bucket, carrying only the fields "Summary" reads."""
    empty = PnlSection(label="", amount=ZERO, share_pct=None, breakdown=[])
    return PnlStatement(
        key=day.isoformat(),
        label=day.isoformat(),
        date_from=day,
        date_to=day,
        currency="KGS",
        sold_units=0,
        returned_units=0,
        net_units=0,
        return_rate_pct=None,
        revenue_seller_price=Decimal(revenue) * 2,
        wb_discount=ZERO,
        revenue_paid=Decimal(revenue),
        average_cheque=None,
        wb_commission=ZERO,
        wb_commission_vat=ZERO,
        wb_reward=ZERO,
        acquiring=ZERO,
        acquiring_billed_apart=ZERO,
        payout_from_sales=ZERO,
        compensations=ZERO,
        payout_for_goods=ZERO,
        logistics=empty,
        logistics_forward=ZERO,
        logistics_return=ZERO,
        logistics_unlegged=ZERO,
        storage=empty,
        acceptance=ZERO,
        penalties=empty,
        deductions=empty,
        advertising=Decimal(advertising),
        additional_payments=ZERO,
        rebill_logistic_cost=ZERO,
        total_withheld=ZERO,
        payout_total=ZERO,
        cogs=ZERO,
        cogs_units=0,
        cogs_coverage_pct=None,
        gross_profit=ZERO,
        margin_profit=Decimal(margin_profit),
        margin_pct=None,
        agency_vat=ZERO,
        settlement_rows=1,
    )
