"""Read-side service for the per-SKU P&L report.

Orchestrates :func:`~.sku_report.build_sku_report` over the repositories, and
owns the report's caveats. The cross-module figures (orders from the funnel, ad
spend from the Promotion API) are handed in by the router, which resolves them
through the monitoring contract — this service never reaches into another
module.
"""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

from src.modules.finreports.repos import (
    CostPriceRepository,
    PnlGrouping,
    PnlRepository,
    SkuExclusionRepository,
)
from src.modules.finreports.schemas.size_report import PnlSizesResponse
from src.modules.finreports.schemas.sku_report import PnlSkuReportResponse, PnlSkuRow
from src.modules.finreports.services.cost_price_workbook import build_pnl_workbook
from src.modules.finreports.services.pnl.size_report import build_size_rows
from src.modules.finreports.services.pnl.sku_report import build_dashboard, build_sku_report

_ZERO = Decimal(0)


class SkuReportService:
    """Builds the «По артикулам» P&L cut for a workspace and window."""

    def __init__(
        self,
        *,
        pnl_repo: PnlRepository,
        cost_repo: CostPriceRepository,
        exclusion_repo: SkuExclusionRepository,
    ) -> None:
        """Wire the read service from its repositories."""
        self._pnl = pnl_repo
        self._costs = cost_repo
        self._exclusions = exclusion_repo

    async def set_exclusion(self, *, workspace_id: uuid.UUID, nm_id: int, excluded: bool) -> None:
        """Mark or clear one SKU's «Не включать в общий счёт» flag.

        Args:
            workspace_id: Owning workspace (the mark is shared across its users).
            nm_id: SKU the mark applies to.
            excluded: ``True`` to mark «Не включать», ``False`` to clear it.
        """
        await self._exclusions.set_excluded(
            workspace_id=workspace_id, nm_id=nm_id, excluded=excluded
        )

    async def get_sizes(
        self, *, workspace_id: uuid.UUID, nm_id: int, date_from: date, date_to: date
    ) -> PnlSizesResponse:
        """Return one article's per-size cut of the window.

        The drill-down under a row of «По артикулам», fetched on the click that
        opens it rather than with the table: a report of 40 articles carries
        ~400 size rows, and a seller opens one or two of them.

        Everything is measured off that article's own settlement rows, so the
        sizes add up to the article. There is no profit here: advertising has
        no size at WB, and a margin per size was judged not worth an allocated
        guess — the cut exists to compare how sizes SELL.

        Args:
            workspace_id: Owning workspace.
            nm_id: The article to cut.
            date_from: Inclusive settlement-date start.
            date_to: Inclusive settlement-date end.

        Returns:
            The size rows and the article-level row they sum to. An article
            with no settlement row in the window comes back with no rows, not
            an error — the window is the seller's to choose.
        """
        sa_name, currency = await self._pnl.sku_label(
            workspace_id=workspace_id, nm_id=nm_id, date_from=date_from, date_to=date_to
        )
        sizes = await self._pnl.sizes(
            workspace_id=workspace_id, nm_id=nm_id, date_from=date_from, date_to=date_to
        )
        rows, totals = build_size_rows(sizes)
        return PnlSizesResponse(
            nm_id=nm_id,
            sa_name=sa_name,
            date_from=date_from,
            date_to=date_to,
            currency=currency or "KGS",
            rows=rows,
            totals=totals,
        )

    async def get_report(
        self,
        *,
        workspace_id: uuid.UUID,
        date_from: date,
        date_to: date,
        orders: dict[int, int],
        ad_spend: dict[int, Decimal],
        ad_bonus: dict[int, Decimal],
        bonus_span: tuple[date | None, date | None],
        bonus_currencies: list[str],
        unknown_funding: list[str],
        funnel_span: tuple[date | None, date | None],
        ad_span: tuple[date | None, date | None],
        photos: dict[int, str] | None = None,
        annotated: bool = True,
    ) -> PnlSkuReportResponse:
        """Return the per-SKU report for the window.

        Args:
            workspace_id: Owning workspace.
            date_from: Inclusive settlement-date start.
            date_to: Inclusive settlement-date end.
            orders: Funnel orders per ``nm_id`` (router-resolved).
            ad_spend: Promotion-API spend per ``nm_id`` (router-resolved).
            ad_bonus: WB-funded share of that spend per ``nm_id``
                (router-resolved). In the advertising account's own unit,
                the same one ``ad_spend`` is in — never the settlement's.
            bonus_currencies: The currency labels WB put on this window's bonus
                write-offs; more than one is a caveat, not an error.
            bonus_span: ``(first, last)`` write-off day on record in the
                window. Empty means the ledger was never harvested for this
                period, so the bonus column reports ``None``, not zero.
            unknown_funding: WB funding labels in the window matching neither
                the known cash nor the known bonus set — surfaced as a caveat
                so a WB rename cannot quietly stop the deduction.
            funnel_span: ``(first, last)`` funnel day on record in the window.
            ad_span: ``(first, last)`` advertising day on record in the window.
            photos: Card thumbnails per ``nm_id`` (router-resolved through the
                monitoring contract, like ``orders`` and ``ad_spend``).

            annotated: Whether to compute the report's ANNOTATIONS as well as
                its figures — the per-article penalty categories and the caveat
                lines. Both are separate passes over the settlement detail, and
                on a multi-year window each is ~7 s for something a consumer
                that only draws figures throws away. «Сводка» is that consumer.

        Returns:
            Rows + unallocated bucket + totals + caveats.
        """
        sku_aggregates = await self._pnl.aggregate(
            workspace_id=workspace_id,
            date_from=date_from,
            date_to=date_to,
            grouping=PnlGrouping.SKU,
        )
        totals_list = await self._pnl.aggregate(
            workspace_id=workspace_id,
            date_from=date_from,
            date_to=date_to,
            grouping=PnlGrouping.TOTAL,
        )
        total_aggregate = totals_list[0]
        currency = total_aggregate.currency or "KGS"

        rows, unallocated, totals = build_sku_report(
            sku_aggregates=sku_aggregates,
            total_aggregate=total_aggregate,
            costs=await self._costs.costs_by_nm_id(workspace_id=workspace_id, currency=currency),
            orders=orders if funnel_span[0] is not None else None,
            ad_spend=ad_spend if ad_span[0] is not None else None,
            ad_bonus=ad_bonus if bonus_span[0] is not None else None,
            penalties=(
                await self._pnl.sku_penalties(
                    workspace_id=workspace_id, date_from=date_from, date_to=date_to
                )
                if annotated
                else []
            ),
            excluded=await self._exclusions.excluded_nm_ids(workspace_id),
            photos=photos,
        )
        dashboard = build_dashboard(rows=rows, totals=totals, total_aggregate=total_aggregate)
        notes = (
            []
            if not annotated
            else await self._notes(
                workspace_id=workspace_id,
                date_from=date_from,
                date_to=date_to,
                rows=rows,
                funnel_span=funnel_span,
                ad_span=ad_span,
                bonus_span=bonus_span,
                unknown_funding=unknown_funding,
                bonus_currencies=bonus_currencies,
            )
        )
        return PnlSkuReportResponse(
            date_from=date_from,
            date_to=date_to,
            currency=currency,
            rows=rows,
            unallocated=unallocated,
            totals=totals,
            dashboard=dashboard,
            notes=notes,
        )

    async def export_workbook(
        self,
        *,
        workspace_id: uuid.UUID,
        date_from: date,
        date_to: date,
        orders: dict[int, int],
        ad_spend: dict[int, Decimal],
        ad_bonus: dict[int, Decimal],
        bonus_span: tuple[date | None, date | None],
        bonus_currencies: list[str],
        unknown_funding: list[str],
        funnel_span: tuple[date | None, date | None],
        ad_span: tuple[date | None, date | None],
    ) -> bytes:
        """Render the per-SKU P&L for the window as an editable XLSX.

        The download half of the cost round trip: the same report the «По
        артикулам» view shows, serialised so the seller can fill the
        «Себестоимость за 1 ед.» column offline and upload it back. Takes the
        cross-module figures the router already resolves for :meth:`get_report`.

        Returns:
            The workbook as bytes.
        """
        report = await self.get_report(
            workspace_id=workspace_id,
            date_from=date_from,
            date_to=date_to,
            orders=orders,
            ad_spend=ad_spend,
            ad_bonus=ad_bonus,
            bonus_span=bonus_span,
            bonus_currencies=bonus_currencies,
            unknown_funding=unknown_funding,
            funnel_span=funnel_span,
            ad_span=ad_span,
        )
        return build_pnl_workbook(report)

    async def _notes(
        self,
        *,
        workspace_id: uuid.UUID,
        date_from: date,
        date_to: date,
        rows: list[PnlSkuRow],
        funnel_span: tuple[date | None, date | None],
        ad_span: tuple[date | None, date | None],
        bonus_span: tuple[date | None, date | None],
        unknown_funding: list[str],
        bonus_currencies: list[str],
    ) -> list[str]:
        """Assemble the caveats that qualify the per-SKU figures."""
        notes: list[str] = []

        uncosted = [r for r in rows if r.cost_price is None and r.sold_units]
        if uncosted:
            worst = ", ".join(r.sa_name for r in uncosted[:5])
            notes.append(
                f"Без себестоимости {len(uncosted)} SKU с продажами (крупнейшие: {worst}) — "
                "их чистая прибыль не считается. Заполните в разделе «Себестоимость»."
            )

        notes.extend(_span_note("Заказы", "истории воронки", funnel_span, date_from, date_to))
        notes.extend(_span_note("Реклама", "статистики продвижения", ad_span, date_from, date_to))
        notes.extend(_span_note("Бонусы", "истории списаний WB", bonus_span, date_from, date_to))
        # A WB rename of the funding label silently stops the deduction (the
        # match is an allowlist, on purpose). This is what keeps that silent
        # fallback from being invisible.
        if unknown_funding:
            labels = ", ".join(f"«{label}»" for label in unknown_funding[:5])
            notes.append(
                f"WB списывал рекламу способом, который мы не знаем ({labels}) — "
                "эти суммы посчитаны как деньги продавца, а не как бонусы."
            )
        # The bonus is netted against the spend it came off, and both are in
        # the advertising account's unit. More than one label in one window
        # means WB relabelled the account mid-period (RUB -> KGS on 2026-08-20)
        # — or, indistinguishably from outside, billed in two. Saying so beats
        # implying a certainty we do not have.
        if len(bonus_currencies) > 1:
            labels = ", ".join(bonus_currencies)
            notes.append(
                f"WB помечал списания рекламы разной валютой в этом периоде ({labels}); "
                "«Бонусы» просуммированы как есть — суммы WB при смене пометки не менял."
            )

        sale_rows, with_revenue = await self._pnl.revenue_coverage(
            workspace_id=workspace_id, date_from=date_from, date_to=date_to
        )
        if sale_rows and with_revenue < sale_rows:
            notes.append(
                f"Выручка заполнена только для {with_revenue} из {sale_rows} строк продаж — "
                "остальные строки ещё не догружены из WB."
            )

        notes.append(
            "Реклама — из статистики кампаний WB по дням показа (счета в выплате "
            "удерживаются позже и целиком, без разбивки по SKU). «Бонусы» — доля этих "
            "затрат, оплаченная кэшбэком WB: в выплате её нет вовсе, поэтому «К "
            "перечислению» она не меняет, а прибыль, ROI и ROMI считаются уже без неё. "
            "Налоги и расходы вне WB в отчёт не входят."
        )
        return notes


def _span_note(
    column: str,
    source: str,
    span: tuple[date | None, date | None],
    date_from: date,
    date_to: date,
) -> list[str]:
    """Caveat for a column whose source history does not cover the window."""
    first, last = span
    if first is None:
        return [f"«{column}» недоступны: за период нет {source}."]
    if first > date_from or (last is not None and last < date_to):
        until = f" по {last.isoformat()}" if last is not None and last < date_to else ""
        return [f"«{column}» известны только с {first.isoformat()}{until} — не за весь период."]
    return []
