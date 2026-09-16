"""HTTP route for «Сводка».

Pure pass-through: the window is resolved and bounded here, everything else is
the service's. Workspace-scoped through ``X-Workspace-Id`` — this is a seller's
revenue and margin, so it may never resolve without a tenant.
"""

from __future__ import annotations

from datetime import date, timedelta

from fastapi import APIRouter, Query, status

from src.core.deps import DbSession
from src.core.exceptions import ValidationError
from src.core.timeutils import moscow_today
from src.modules.summary.deps import SummaryServiceDep
from src.modules.summary.schemas import CategoryGrouping, RevenueBase, SummaryResponse
from src.modules.workspaces.contract import CurrentWorkspaceId

#: Default window when the caller names no dates — the last four weeks, the same
#: default «По артикулам» uses, so switching between the two screens does not
#: silently switch the period under the reader.
DEFAULT_WINDOW_DAYS = 28

#: Hard cap on how much settlement history one request may aggregate. Two years
#: of this service's largest seller is ~670 000 rows, and the page has no use for
#: a window that size — it draws one point per day. The cap is here rather than
#: in the service because it is a bound on the REQUEST, and an unbounded window
#: is a cheap way for one authenticated caller to make Postgres do a minute of
#: work per keystroke.
MAX_WINDOW_DAYS = 400

router = APIRouter()


def _resolve_window(date_from: date | None, date_to: date | None) -> tuple[date, date]:
    """Fill and bound the requested settlement-date window.

    "Today" is the MOSCOW day: WB dates every settlement row by the Moscow
    calendar, so on a UTC host ``date.today()`` drops the newest settlement day
    between 00:00 and 03:00 MSK.

    Raises:
        ValidationError: The window is inverted or longer than the cap. The
            message names the limit and never echoes the submitted dates back.
    """
    end = date_to or moscow_today()
    start = date_from or (end - timedelta(days=DEFAULT_WINDOW_DAYS))
    if start > end:
        raise ValidationError("Конец периода раньше начала.")
    if (end - start).days > MAX_WINDOW_DAYS:
        raise ValidationError(f"Период больше {MAX_WINDOW_DAYS} дней.")
    return start, end


@router.get(
    "/summary",
    response_model=SummaryResponse,
    status_code=status.HTTP_200_OK,
    responses={
        200: {"description": "Сводные показатели кабинета за период."},
        401: {"description": "Unauthorized access token."},
        403: {"description": "Раздел доступен только внутренним учётным записям."},
        422: {"description": "Период инвертирован или длиннее допустимого."},
    },
)
async def get_summary(
    service: SummaryServiceDep,
    workspace_id: CurrentWorkspaceId,
    session: DbSession,
    date_from: date | None = Query(default=None, description="Inclusive settlement-date start."),
    date_to: date | None = Query(default=None, description="Inclusive settlement-date end."),
    revenue_base: RevenueBase = Query(
        default=RevenueBase.PAID, description="Which price revenue is taken at."
    ),
    grouping: CategoryGrouping = Query(
        default=CategoryGrouping.SKU, description="How «Выручка по категории» is cut."
    ),
) -> SummaryResponse:
    """Return every figure the «Сводка» page draws for one window.

    Read-only; the guard lives on the aggregating router
    (:mod:`src.modules.summary.routers`) so no route here can forget it.
    """
    start, end = _resolve_window(date_from, date_to)
    return await service.build(
        session,
        workspace_id=workspace_id,
        date_from=start,
        date_to=end,
        revenue_base=revenue_base,
        grouping=grouping,
    )
