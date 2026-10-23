"""The heatmap service: one request in, the whole grid out.

Orchestration only — which articles are selected, which sources to load, and
handing the facts to the pure folding in :mod:`.table`. The numbers themselves
are decided in :mod:`.metrics`.

Filters narrow, they never widen, and they combine by intersection — "Categories",
"Groups" and "SKUs" all at once. Every one of them is applied to the workspace's OWN
catalogue, so an article id from somewhere else is not in the set to begin with.
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date

from sqlalchemy.ext.asyncio import AsyncSession

from src.modules.finreports.contract import PnlService, SkuReportService
from src.modules.heatmap.repos import SkuGroupRepository
from src.modules.heatmap.schemas import (
    GroupBy,
    HeatmapCatalogItem,
    HeatmapCatalogResponse,
    HeatmapColumn,
    HeatmapResponse,
    MetricKey,
    Period,
)
from src.modules.heatmap.services.loader import FactsWindow, load_facts
from src.modules.heatmap.services.metrics import METRIC_SOURCES, Facts
from src.modules.heatmap.services.periods import build_columns
from src.modules.heatmap.services.table import (
    GroupSpec,
    build_row_specs,
    build_rows,
    fold_sku_days,
)
from src.modules.monitoring.contract import (
    CatalogCard,
    load_ad_currencies,
    load_orders_by_nm,
    load_price_currency,
    load_workspace_catalog,
)

#: Above this many articles the narrowing is applied after the load rather
#: than as an ``IN`` list: the tenant is in the ``WHERE`` either way, and a list
#: this long costs the planner more than the rows it saves.
_MAX_SQL_NARROWING = 2000


@dataclass(frozen=True, slots=True)
class HeatmapQuery:
    """One request for the grid, already validated at the route."""

    date_from: date
    date_to: date
    period: Period
    group_by: GroupBy
    metric: MetricKey
    metric2: MetricKey | None
    subjects: frozenset[str] = frozenset()
    group_ids: frozenset[uuid.UUID] = frozenset()
    nm_ids: frozenset[int] = frozenset()


class HeatmapService:
    """Builds the heatmap grid and the catalogue behind its filters."""

    def __init__(
        self, *, groups: SkuGroupRepository, pnl: PnlService, skus: SkuReportService
    ) -> None:
        """Wire the service from its repository and the finreports read services."""
        self._groups = groups
        self._pnl = pnl
        self._skus = skus

    async def catalog(
        self, session: AsyncSession, *, workspace_id: uuid.UUID, date_from: date, date_to: date
    ) -> HeatmapCatalogResponse:
        """Every card of the workspace, most-ordered in the window first, and its subjects.

        The article pickers — the "SKUs" filter and the group editor — list a
        few hundred cards on a large workspace; the ones a seller is looking for
        are the ones that sell, so they come first rather than alphabetically.
        """
        cards = await load_workspace_catalog(session, workspace_id=workspace_id)
        orders = await load_orders_by_nm(
            session, workspace_id=workspace_id, date_from=date_from, date_to=date_to
        )
        items = [
            HeatmapCatalogItem(**card._asdict(), orders=orders.get(card.nm_id, 0)) for card in cards
        ]
        items.sort(key=lambda item: (-item.orders, item.vendor_code.lower(), item.nm_id))
        return HeatmapCatalogResponse(
            items=items,
            subjects=sorted({card.subject_name for card in cards if card.subject_name}),
        )

    async def build(
        self, session: AsyncSession, *, workspace_id: uuid.UUID, query: HeatmapQuery
    ) -> HeatmapResponse:
        """Compute the grid for one window.

        Args:
            session: The request's session, tenant bound.
            workspace_id: The caller's workspace.
            query: Window, cut, metrics and filters.
        """
        cards = {
            card.nm_id: card
            for card in await load_workspace_catalog(session, workspace_id=workspace_id)
        }
        groups = [
            GroupSpec(key=str(group_id), name=name, nm_ids=frozenset(members))
            for group_id, name, members in await self._groups.list_groups(workspace_id)
        ]
        selection = _select(cards, groups, query)

        metrics = (query.metric, query.metric2)
        sources = frozenset().union(*(METRIC_SOURCES[m] for m in metrics if m is not None))
        loaded = await load_facts(
            session,
            FactsWindow(
                workspace_id=workspace_id,
                date_from=query.date_from,
                date_to=query.date_to,
                sources=sources,
                nm_ids=_sql_narrowing(selection, cards),
            ),
            pnl=self._pnl,
            skus=self._skus,
        )
        facts = loaded.facts
        if selection is not None:
            facts = {key: value for key, value in facts.items() if key[0] in selection}

        columns = build_columns(query.date_from, query.date_to, query.period)
        grid = fold_sku_days(facts, columns)
        specs = build_row_specs(query.group_by, nm_ids=grid.cells, cards=cards, groups=groups)
        settled_to = loaded.settled_to
        totals, rows = build_rows(
            specs,
            grid,
            width=len(columns),
            metrics=metrics,
            rank=loaded.rank,
            settled=[settled_to is not None and start <= settled_to for start, _ in columns],
        )
        return HeatmapResponse(
            date_from=query.date_from,
            date_to=query.date_to,
            period=query.period,
            group_by=query.group_by,
            metric=query.metric,
            metric2=query.metric2,
            currency=loaded.currency
            or await self._pnl.settlement_currency(workspace_id=workspace_id),
            price_currency=await load_price_currency(session, workspace_id=workspace_id),
            order_currency=_order_currency(loaded.facts),
            ad_currencies=await load_ad_currencies(
                session,
                workspace_id=workspace_id,
                date_from=query.date_from,
                date_to=query.date_to,
            ),
            settled_to=loaded.settled_to,
            columns=[HeatmapColumn(start=start, end=end) for start, end in columns],
            totals=totals,
            rows=rows,
        )


def _order_currency(facts: Mapping[tuple[int, date], Facts]) -> str:
    """The currency WB's funnel sums are in — one per workspace, the settlement's."""
    for cell in facts.values():
        if len(cell.order_currencies) == 1:
            return next(iter(cell.order_currencies))
    return ""


def _sql_narrowing(
    selection: frozenset[int] | None, cards: dict[int, CatalogCard]
) -> frozenset[int] | None:
    """The articles to name in the fact queries — the whole catalogue when nothing is filtered.

    Naming them is a plan, not a scope: the tenant semijoin is there either way.
    The fact tables hold every workspace's articles, and against the semijoin
    alone Postgres reads the whole window of all of them — measured on
    one workspace (64 cards, 180 days, 2026-09-30) advertising was a cold
    sequential scan of 5 459 pages in 2.05 s. Named, it is a bitmap scan of the
    (nm_id, stat_date) index: 762 pages, 14 ms.
    """
    wanted = frozenset(cards) if selection is None else selection
    return wanted if len(wanted) <= _MAX_SQL_NARROWING else None


def _select(
    cards: dict[int, CatalogCard], groups: list[GroupSpec], query: HeatmapQuery
) -> frozenset[int] | None:
    """The selected articles, or ``None`` for "every article of the workspace".

    Always a subset of the workspace's own catalogue: each filter intersects it.
    """
    if not (query.subjects or query.group_ids or query.nm_ids):
        return None
    selected = frozenset(cards)
    if query.subjects:
        selected &= {nm for nm, card in cards.items() if card.subject_name in query.subjects}
    if query.group_ids:
        wanted = {str(group_id) for group_id in query.group_ids}
        members: set[int] = set()
        for group in groups:
            if group.key in wanted:
                members |= group.nm_ids
        selected &= members
    if query.nm_ids:
        selected &= query.nm_ids
    return selected
