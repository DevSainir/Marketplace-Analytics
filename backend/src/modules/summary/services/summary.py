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
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from src.core.timeutils import moscow_today
from src.modules.finreports.contract import PnlGrouping, PnlService, SkuReportService
from src.modules.monitoring.contract import (
    BUYOUT_LAG_END_DAYS,
    BUYOUT_LAG_START_DAYS,
    OrderDay,
    ad_bonus_coverage,
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
    buyout_cohort,
    uncosted_skus,
    window_ad_cash,
)

#: How much of a period's ordering must have been ANSWERED before the period's
#: own buyout rate is reported. Half, because the ratio is noisy below that and
#: settles above it: measured on «Демо», a cohort 8 % answered read 22 %,
#: one 60 % answered read 30 %, and the кабинет's own rate is 26-28 %.
_ANSWERED_ENOUGH = 0.5


class SummaryService:
    """Builds the «Сводка» for a workspace and window."""

    def __init__(self, *, pnl: PnlService, skus: SkuReportService) -> None:
        """Wire the read service from the finreports services it composes."""
        self._pnl = pnl
        self._skus = skus

    async def span(self, session: AsyncSession, *, workspace_id: uuid.UUID) -> SummarySpan:
        """Return the days the кабинет has any data for, for the period picker.

        Not the settled days alone. WB calculates settlements weekly and serves
        them days late, but the funnel and the advertising statistics land every
        day — so a preset ending on the last settled day hid the three or four
        freshest days of exactly the two figures that are current. The window
        now ends on the newest day ANY feed covers, and the settlement's own end
        travels beside it so the revenue line can stop where the money does.
        """
        settled = await self._pnl.get_settled_span(workspace_id=workspace_id)
        # A window wide enough to be «all of it»: the oldest settlement on this
        # service is from 2024, and both reads are a min/max over an indexed
        # day column rather than a scan.
        horizon = {"date_from": date(2000, 1, 1), "date_to": moscow_today()}
        funnel = await funnel_coverage(session, workspace_id=workspace_id, **horizon)
        ads = await ad_coverage(session, workspace_id=workspace_id, **horizon)

        starts = [day for day in (settled[0] if settled else None, funnel[0], ads[0]) if day]
        ends = [day for day in (settled[1] if settled else None, funnel[1], ads[1]) if day]
        return SummarySpan(
            date_from=min(starts) if starts else None,
            date_to=max(ends) if ends else None,
            settled_to=settled[1] if settled else None,
        )

    async def _buyout(
        self, session: AsyncSession, *, workspace_id: uuid.UUID, days: list[OrderDay]
    ) -> tuple[int | None, int | None, bool]:
        """Return the window's buyout cohort, or the standing one if it has none.

        The cohort is lagged by :data:`BUYOUT_LAG_END_DAYS`, the same lag the
        «Мониторинг SKU» matrix applies, and for the same measured reason: inside
        a fresh cohort the refusals arrive before the buyouts do. On the live
        кабинет the current week reads 22.2 % against a long-run 26-30 %, on
        8 % of its deliveries having answered at all.

        The lag alone is not enough, which a week-long period shows: only its
        oldest day or two clear it, and they are answered barely past half.
        Measured on «Демо» for 10-16.09, that cohort read 29.6 % — 89
        buyouts out of 301 answered deliveries, against 1 151 orders — while
        the кабинет's settled rate is 26.4 %. A half-answered cohort is noisy in
        BOTH directions: at 8 % answered the same кабинет read 22 %, at 60 % it
        read 30 %.

        So the period answers for itself only when most of what it ordered has
        been answered. Otherwise the standing «21-7 дней назад» window answers
        instead, and the page says that is what it did rather than passing one
        period's rate off as another's.

        Returns:
            ``(bought out, answered, taken from the standing window)``.
        """
        cutoff = moscow_today() - timedelta(days=BUYOUT_LAG_END_DAYS)
        bought, answered = buyout_cohort(days, until=cutoff)
        ordered = sum(day.orders for day in days)
        if answered and ordered and answered >= ordered * _ANSWERED_ENOUGH:
            return bought, answered, False

        standing = await load_order_days(
            session,
            workspace_id=workspace_id,
            date_from=moscow_today() - timedelta(days=BUYOUT_LAG_START_DAYS),
            date_to=cutoff,
        )
        bought, answered = buyout_cohort(standing, until=cutoff)
        return bought, answered, answered is not None

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
            # Both feed the report's caveat lines and nothing else, and this
            # page draws no caveats (`annotated=False` below). Asking anyway is
            # two more passes over the кабинет's whole advertising ledger for
            # text that is discarded — ~0.3 s of a «Вся история» window.
            ad_currencies=[],
            unknown_funding=[],
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
        buyouts, decided, lagged = await self._buyout(
            session, workspace_id=workspace_id, days=order_days
        )

        # Composed before the cards, because two of them are built from it: the
        # advertising a card may count is the advertising of the days the
        # settlement covers, and those days are exactly what this produces.
        days = build_days(
            buckets=buckets,
            order_days=order_days,
            ad_days=ad_days,
            costed=uncosted_skus(report) == 0,
        )
        ad_cash = window_ad_cash(days, covered=bool(ad_days))

        return SummaryResponse(
            date_from=date_from,
            date_to=date_to,
            currency=report.currency,
            kpi=build_kpi(
                report=report,
                orders=orders,
                buyouts=buyouts,
                buyout_decided=decided,
                buyout_lagged=lagged,
                ad_cash=ad_cash,
                # The invoices the window settled, summed off the day buckets:
                # the statement's own total would be a second pass for a figure
                # the buckets already partition.
                settled_advertising=sum((bucket.advertising for bucket in buckets), Decimal(0)),
            ),
            days=days,
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
