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
from src.modules.finreports.schemas.sku_report import PnlSkuReportResponse, PnlSkuRow
from src.modules.finreports.services.cost_price_workbook import build_pnl_workbook
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

    async def get_report(
        self,
        *,
        workspace_id: uuid.UUID,
        date_from: date,
        date_to: date,
        orders: dict[int, int],
        ad_spend: dict[int, Decimal],
        funnel_span: tuple[date | None, date | None],
        ad_span: tuple[date | None, date | None],
    ) -> PnlSkuReportResponse:
        """Return the per-SKU report for the window.

        Args:
            workspace_id: Owning workspace.
            date_from: Inclusive settlement-date start.
            date_to: Inclusive settlement-date end.
            orders: Funnel orders per ``nm_id`` (router-resolved).
            ad_spend: Promotion-API spend per ``nm_id`` (router-resolved).
            funnel_span: ``(first, last)`` funnel day on record in the window.
            ad_span: ``(first, last)`` advertising day on record in the window.

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
            penalties=await self._pnl.sku_penalties(
                workspace_id=workspace_id, date_from=date_from, date_to=date_to
            ),
            excluded=await self._exclusions.excluded_nm_ids(workspace_id),
        )
        dashboard = build_dashboard(rows=rows, totals=totals, total_aggregate=total_aggregate)
        notes = await self._notes(
            workspace_id=workspace_id,
            date_from=date_from,
            date_to=date_to,
            rows=rows,
            funnel_span=funnel_span,
            ad_span=ad_span,
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

        sale_rows, with_revenue = await self._pnl.revenue_coverage(
            workspace_id=workspace_id, date_from=date_from, date_to=date_to
        )
        if sale_rows and with_revenue < sale_rows:
            notes.append(
                f"Выручка заполнена только для {with_revenue} из {sale_rows} строк продаж — "
                "запустите scripts/backfill_pnl_columns.py."
            )

        notes.append(
            "Реклама — из статистики кампаний WB по дням показа (счета в выплате "
            "удерживаются позже и целиком, без разбивки по SKU). Налоги и расходы вне WB "
            "в отчёт не входят."
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
