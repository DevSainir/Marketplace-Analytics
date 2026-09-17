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
from src.modules.summary.schemas import SummaryResponse, SummarySpan
from src.modules.workspaces.contract import CurrentWorkspaceId

#: Default window when the caller names no dates — the last week. The page is
#: «как идут дела сейчас», and a month of history flattens the few days that
#: answer that; the presets are one click away for the longer look.
DEFAULT_WINDOW_DAYS = 7

#: Hard cap on how much settlement history one request may aggregate.
#:
#: Sized to «Вся история» rather than below it: the button exists, and a cap that
#: refuses the кабинет's own settled span makes it a button that always errors.
#: The oldest settlement on this service is from 2024, so three years of slack is
#: the whole product — and the bound still has to exist, because an unbounded
#: window is a cheap way for one authenticated caller to make Postgres do a
#: minute of work per keystroke.
MAX_WINDOW_DAYS = 1200

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
    "/summary/span",
    response_model=SummarySpan,
    status_code=status.HTTP_200_OK,
    responses={
        200: {"description": "Диапазон рассчитанных дней кабинета."},
        401: {"description": "Unauthorized access token."},
        403: {"description": "Раздел доступен только внутренним учётным записям."},
    },
)
async def get_summary_span(
    service: SummaryServiceDep, session: DbSession, workspace_id: CurrentWorkspaceId
) -> SummarySpan:
    """Return the days this кабинет has data for.

    Its own route rather than a field on the summary because the picker needs it
    BEFORE a window is chosen, and because it is answered off the report headers
    and two min/max reads — a hundred rows and two index lookups — while a
    summary is a pass over the settlement rollup.
    """
    return await service.span(session, workspace_id=workspace_id)


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
) -> SummaryResponse:
    """Return every figure the «Сводка» page draws for one window.

    The window is the ONLY parameter. Price base, grouping and sort order used
    to be query parameters, and every click on one of them cost a round trip
    over the whole settlement window; both bases now travel in the response and
    the rows arrive ungrouped, so the page answers those from data it holds.

    **This GET writes, and deliberately.** Reading a window fills the settlement
    rollup for the days it did not already cover — a cache that verifies itself
    against the detail's own row counts and rebuilds whatever disagrees. Nothing
    a caller sends decides what is written: the content is derived from the
    кабинет's own settlement rows, and the tenant is bound by
    :data:`CurrentWorkspaceId` exactly as for the read.

    Otherwise read-only; the guard lives on the aggregating router
    (:mod:`src.modules.summary.routers`) so no route here can forget it.
    """
    start, end = _resolve_window(date_from, date_to)
    return await service.build(session, workspace_id=workspace_id, date_from=start, date_to=end)
