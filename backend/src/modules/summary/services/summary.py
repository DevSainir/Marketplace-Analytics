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
from decimal import Decimal

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
from src.modules.summary.schemas import SummaryCoverage, SummaryResponse, SummarySpan
from src.modules.summary.services.compose import (
    build_days,
    build_kpi,
    build_rows,
    uncosted_skus,
    window_ad_cash,
)


class SummaryService:
    """Builds the «Сводка» for a workspace and window."""

    def __init__(self, *, pnl: PnlService, skus: SkuReportService) -> None:
        """Wire the read service from the finreports services it composes."""
        self._pnl = pnl
        self._skus = skus

    async def span(self, *, workspace_id: uuid.UUID) -> SummarySpan:
        """Return the settled days the кабинет has, for the period picker."""
        settled = await self._pnl.get_settled_span(workspace_id=workspace_id)
        return SummarySpan(
            date_from=settled[0] if settled else None,
            date_to=settled[1] if settled else None,
        )

    async def build(
        self,
        session: AsyncSession,
        *,
        workspace_id: uuid.UUID,
        date_from: date,
        date_to: date,
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

        Returns:
            The cards, the daily series, the per-article rows and what each
            rests on. Both price bases travel in every figure and the rows are
            ungrouped, so the page switches base, grouping and sort order
            without coming back here.
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
            # No penalty categories and no caveat lines: this page draws
            # neither, and each is its own pass over the settlement detail —
            # ~7 s apiece on a multi-year window, for figures that are then
            # thrown away.
            annotated=False,
        )
        # `get_buckets`, not `get_statement`: the statement also computes a
        # whole-window total, four drill-downs by WB's own reason strings and the
        # caveat queries, each its own pass over the same settlement rows. This
        # page draws none of them, and on a multi-year window those passes were
        # the difference between a chart and a timeout.
        buckets = await self._pnl.get_buckets(
            workspace_id=workspace_id,
            date_from=date_from,
            date_to=date_to,
            grouping=PnlGrouping.DAY,
            # Already resolved by the report above; asking again is one more
            # pass over the window for a three-letter answer.
            currency=report.currency,
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
            kpi=build_kpi(
                report=report,
                orders=orders,
                buyouts=buyouts,
                ad_cash=window_ad_cash(ad_days),
                # The invoices the window settled, summed off the day buckets:
                # the statement's own total would be a second pass for a figure
                # the buckets already partition.
                settled_advertising=sum((bucket.advertising for bucket in buckets), Decimal(0)),
            ),
            days=build_days(
                buckets=buckets,
                order_days=order_days,
                ad_days=ad_days,
                costed=uncosted_skus(report) == 0,
            ),
            rows=build_rows(report),
            coverage=SummaryCoverage(
                # min/max rather than the ends of the list: the repository
                # orders buckets newest-first, and reading position 0 as «the
                # start» is the kind of mistake that reports a window backwards.
                settlement_from=min((b.date_from for b in buckets if b.date_from), default=None),
                settlement_to=max((b.date_to for b in buckets if b.date_to), default=None),
                funnel_from=funnel_span[0],
                funnel_to=funnel_span[1],
                advertising_from=ad_span[0],
                advertising_to=ad_span[1],
            ),
        )
