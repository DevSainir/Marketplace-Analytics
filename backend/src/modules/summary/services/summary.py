"""Read-side service for «Сводка».

This module owns no data. It composes two finreports cuts of the settlement —
the per-SKU report and the same window cut by settlement date — with the three
monitoring feeds that the settlement does not carry (orders, advertising burn,
WB's bonus funding), and hands the arithmetic to :mod:`.compose`.

Everything crosses a module boundary through ``contract.py``, never through
another module's internals, which is why the finreports services arrive as
constructor arguments rather than being wired here from their repositories.
"""

from __future__ import annotations

import uuid
from datetime import date

from sqlalchemy.ext.asyncio import AsyncSession

from src.modules.finreports.contract import PnlGrouping, PnlService, SkuReportService
from src.modules.monitoring.contract import (
    ad_bonus_coverage,
    ad_bonus_currencies,
    ad_bonus_unknown_types,
    ad_coverage,
    funnel_coverage,
    load_ad_bonus_by_nm,
    load_ad_days,
    load_ad_spend_by_nm,
    load_order_days,
    load_orders_by_nm,
)
from src.modules.summary.schemas import (
    CategoryGrouping,
    RevenueBase,
    SummaryCoverage,
    SummaryResponse,
)
from src.modules.summary.services.compose import (
    build_categories,
    build_days,
    build_kpi,
    uncosted_skus,
    window_ad_cash,
)


class SummaryService:
    """Builds the «Сводка» for a workspace and window."""

    def __init__(self, *, pnl: PnlService, skus: SkuReportService) -> None:
        """Wire the read service from the finreports services it composes."""
        self._pnl = pnl
        self._skus = skus

    async def build(
        self,
        session: AsyncSession,
        *,
        workspace_id: uuid.UUID,
        date_from: date,
        date_to: date,
        revenue_base: RevenueBase,
        grouping: CategoryGrouping,
    ) -> SummaryResponse:
        """Assemble the whole surface for one window.

        The per-SKU report is requested even though the page draws no table:
        it is the reconciled shape of the window (Σ rows + account-level money
        = totals, to the kopeck, a tested invariant), and rebuilding the same
        totals here from a second query is exactly how two screens start
        disagreeing about one seller's revenue.

        Args:
            session: An open async session, for the monitoring loaders.
            workspace_id: The tenant, already validated by the route.
            date_from: Inclusive settlement-date start.
            date_to: Inclusive settlement-date end.
            revenue_base: Which price revenue is taken at.
            grouping: How the category block is cut.

        Returns:
            The cards, the daily series, the category ranking and what each
            rests on.
        """
        # Resolved once and reused: both the report's caveats and this
        # response's coverage block ask the same two questions, and asking twice
        # is two more round trips for one answer.
        funnel_span = await funnel_coverage(
            session, workspace_id=workspace_id, date_from=date_from, date_to=date_to
        )
        ad_span = await ad_coverage(
            session, workspace_id=workspace_id, date_from=date_from, date_to=date_to
        )
        report = await self._skus.get_report(
            workspace_id=workspace_id,
            date_from=date_from,
            date_to=date_to,
            orders=await load_orders_by_nm(
                session, workspace_id=workspace_id, date_from=date_from, date_to=date_to
            ),
            ad_spend=await load_ad_spend_by_nm(
                session, workspace_id=workspace_id, date_from=date_from, date_to=date_to
            ),
            ad_bonus=await load_ad_bonus_by_nm(
                session, workspace_id=workspace_id, date_from=date_from, date_to=date_to
            ),
            bonus_span=await ad_bonus_coverage(
                session, workspace_id=workspace_id, date_from=date_from, date_to=date_to
            ),
            bonus_currencies=await ad_bonus_currencies(
                session, workspace_id=workspace_id, date_from=date_from, date_to=date_to
            ),
            unknown_funding=await ad_bonus_unknown_types(
                session, workspace_id=workspace_id, date_from=date_from, date_to=date_to
            ),
            funnel_span=funnel_span,
            ad_span=ad_span,
            photos={},
        )
        statement = await self._pnl.get_statement(
            workspace_id=workspace_id,
            date_from=date_from,
            date_to=date_to,
            grouping=PnlGrouping.DAY,
        )
        order_days = await load_order_days(
            session, workspace_id=workspace_id, date_from=date_from, date_to=date_to
        )
        ad_days = await load_ad_days(
            session, workspace_id=workspace_id, date_from=date_from, date_to=date_to
        )

        orders = sum(day.orders for day in order_days) if order_days else None
        buyouts = sum(day.buyouts for day in order_days) if order_days else None

        return SummaryResponse(
            date_from=date_from,
            date_to=date_to,
            currency=report.currency,
            revenue_base=revenue_base,
            grouping=grouping,
            kpi=build_kpi(
                report=report,
                base=revenue_base,
                orders=orders,
                buyouts=buyouts,
                ad_cash=window_ad_cash(ad_days),
            ),
            days=build_days(
                buckets=statement.buckets,
                order_days=order_days,
                ad_days=ad_days,
                base=revenue_base,
                costed=uncosted_skus(report) == 0,
            ),
            categories=build_categories(report=report, base=revenue_base, grouping=grouping),
            coverage=SummaryCoverage(
                settlement_from=statement.total.date_from,
                settlement_to=statement.total.date_to,
                funnel_from=funnel_span[0],
                funnel_to=funnel_span[1],
                advertising_from=ad_span[0],
                advertising_to=ad_span[1],
            ),
        )
