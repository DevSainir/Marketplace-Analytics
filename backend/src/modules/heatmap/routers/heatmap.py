"""HTTP routes for the heatmap grid and the catalogue behind its filters.

Pass-through: the window is resolved and bounded here, everything else is the
service's. Workspace-scoped through ``X-Workspace-Id`` — this is a seller's
orders, advertising and profit, so it may never resolve without a tenant.
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

#: Default window when the caller names no dates: the seven days ending
#: YESTERDAY. Today's funnel is still filling, and a half-day painted red next
#: to six whole ones reads as a collapse.
DEFAULT_WINDOW_DAYS = 7

#: Longest window, inclusive. Sized like the reference tool's own limit, and it
#: has to exist: a window is a scan of every SKU-day in it, and an unbounded one
#: is a cheap way for one caller to make Postgres work for a minute.
MAX_WINDOW_DAYS = 180

router = APIRouter()

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
        raise ValidationError(f"Период больше {MAX_WINDOW_DAYS} дней.")
    return start, end


@router.get(
    "/heatmap",
    response_model=HeatmapResponse,
    status_code=status.HTTP_200_OK,
    responses={
        200: {"description": "Тепловая карта за период."},
        401: {"description": "Unauthorized access token."},
        403: {"description": "Раздел доступен только внутренним учётным записям."},
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

    The guards live on the aggregating router (:mod:`src.modules.heatmap.routers`).
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


@router.get(
    "/heatmap/catalog",
    response_model=HeatmapCatalogResponse,
    status_code=status.HTTP_200_OK,
    responses={
        200: {"description": "Каталог кабинета для фильтров."},
        401: {"description": "Unauthorized access token."},
        403: {"description": "Раздел доступен только внутренним учётным записям."},
    },
)
async def get_catalog(
    service: HeatmapServiceDep, workspace_id: CurrentWorkspaceId, session: DbSession
) -> HeatmapCatalogResponse:
    """Return the кабинет's cards and subjects, for «Категории», «Артикулы» and the group editor.

    Its own route because the filters need it before a grid exists, and because
    it does not change with the window.
    """
    return await service.catalog(session, workspace_id=workspace_id)
