"""HTTP routes for the heatmap grid and the catalogue behind its filters.

Pass-through: the window is resolved and bounded here, everything else is the
service's. Workspace-scoped through ``X-Workspace-Id`` — this is a seller's
orders, advertising and profit, so it may never resolve without a tenant.

Two routers, because the two routes answer to different grants: the grid is
«Тепловая карта» (:data:`router`), the catalogue is what the group editor picks
articles from on every page that has groups (:data:`catalog_router`). The
guards are attached where :mod:`src.modules.heatmap.routers` includes them.
"""

from __future__ import annotations

import uuid
from datetime import date, timedelta
from typing import Annotated

from fastapi import APIRouter, Query, status
from pydantic import Field, StringConstraints

from src.core.deps import DbSession
from src.core.exceptions import ValidationError
from src.core.timeutils import moscow_today
from src.modules.heatmap.deps import HeatmapServiceDep
from src.modules.heatmap.schemas import (
    GroupBy,
    HeatmapCatalogResponse,
    HeatmapResponse,
    MetricKey,
    Period,
)
from src.modules.heatmap.services import HeatmapQuery
from src.modules.workspaces.contract import CurrentWorkspaceId

#: Default window when the caller names no dates: the thirty days ending
#: YESTERDAY. Today's funnel is still filling, and a half-day painted red next
#: to whole ones reads as a collapse.
DEFAULT_WINDOW_DAYS = 30

#: Longest window, inclusive: a year. It has to exist — a window is a scan of
#: every SKU-day in it, and an unbounded one is a cheap way for one caller to
#: make Postgres work for a minute. Measured on NEVA (262 cards, 2026-09-28) at
#: 180 days: 1.4-3.8 s and ~0.5 MB, so a year stays within seconds. It was the
#: reference tool's 180 until the owner asked for more.
MAX_WINDOW_DAYS = 366

router = APIRouter()
catalog_router = APIRouter()

Subject = Annotated[str, StringConstraints(max_length=128)]
PositiveNm = Annotated[int, Field(ge=1)]


def _resolve_window(date_from: date | None, date_to: date | None) -> tuple[date, date]:
    """Fill and bound the requested window.

    Raises:
        ValidationError: The window is inverted or longer than the cap. The
            message names the limit and never echoes the submitted dates back.
    """
    end = date_to or (moscow_today() - timedelta(days=1))
    start = date_from or (end - timedelta(days=DEFAULT_WINDOW_DAYS - 1))
    if start > end:
        raise ValidationError("Конец периода раньше начала.")
    if (end - start).days + 1 > MAX_WINDOW_DAYS:
        raise ValidationError(
            f"Можно выбрать только период не длиннее {MAX_WINDOW_DAYS} дней — выберите короче."
        )
    return start, end


@router.get(
    "/heatmap",
    response_model=HeatmapResponse,
    status_code=status.HTTP_200_OK,
    responses={
        200: {"description": "Тепловая карта за период."},
        401: {"description": "Unauthorized access token."},
        403: {"description": "Нет раздела «Тепловая карта»."},
        422: {"description": "Период инвертирован или длиннее допустимого."},
    },
)
async def get_heatmap(
    service: HeatmapServiceDep,
    workspace_id: CurrentWorkspaceId,
    session: DbSession,
    date_from: date | None = Query(default=None, description="Inclusive start."),
    date_to: date | None = Query(default=None, description="Inclusive end."),
    metric: MetricKey = Query(default="orders", description="The metric painted."),
    metric2: MetricKey | None = Query(default=None, description="Optional second metric."),
    period: Period = Query(default="day", description="Column width."),
    group_by: GroupBy = Query(default="sku", description="What one row stands for."),
    subjects: list[Subject] = Query(default=[], max_length=200, description="WB «Предмет»."),
    group_ids: list[uuid.UUID] = Query(default=[], max_length=100, description="Groups."),
    nm_ids: list[PositiveNm] = Query(default=[], max_length=1000, description="Articles."),
) -> HeatmapResponse:
    """Return the grid: one row per article (or category, brand, group), one column per period.

    **This GET can write, and deliberately** — the same way «Сводка» does. A
    finance metric reads the settlement rollup, which verifies itself against
    the detail's own row counts and rebuilds the days that disagree. Nothing a
    caller sends decides what is written; the tenant is bound by
    :data:`CurrentWorkspaceId` exactly as for the read.

    The «Тепловая карта» grant is attached where the router is included
    (:mod:`src.modules.heatmap.routers`), and it opens every metric: the money
    ones stopped asking for P&L as well on 2026-10-12, when each page became a
    grant of its own.
    """
    start, end = _resolve_window(date_from, date_to)
    query = HeatmapQuery(
        date_from=start,
        date_to=end,
        period=period,
        group_by=group_by,
        metric=metric,
        metric2=metric2 if metric2 != metric else None,
        subjects=frozenset(subjects),
        group_ids=frozenset(group_ids),
        nm_ids=frozenset(nm_ids),
    )
    return await service.build(session, workspace_id=workspace_id, query=query)


@catalog_router.get(
    "/heatmap/catalog",
    response_model=HeatmapCatalogResponse,
    status_code=status.HTTP_200_OK,
    responses={
        200: {"description": "Каталог кабинета для фильтров."},
        401: {"description": "Unauthorized access token."},
        403: {"description": "Нет ни одного раздела с группами."},
    },
)
async def get_catalog(
    service: HeatmapServiceDep,
    workspace_id: CurrentWorkspaceId,
    session: DbSession,
    date_from: date | None = Query(default=None, description="Inclusive start."),
    date_to: date | None = Query(default=None, description="Inclusive end."),
) -> HeatmapCatalogResponse:
    """Return the workspace's cards and subjects, for «Категории», «Артикулы» and the group editor.

    Its own route because the filters need it before a grid exists. The window
    only orders the cards — most-ordered first — so it is bounded the same way
    as the grid's.
    """
    start, end = _resolve_window(date_from, date_to)
    return await service.catalog(session, workspace_id=workspace_id, date_from=start, date_to=end)
