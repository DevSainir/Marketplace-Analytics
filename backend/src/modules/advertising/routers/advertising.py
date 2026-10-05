"""HTTP routes for «Реклама».

Pure pass-through: the window is resolved and bounded here, everything else is
the service's. Workspace-scoped through ``X-Workspace-Id`` — this is a seller's
advertising and sales, so it may never resolve without a tenant.
"""

from __future__ import annotations

from datetime import date, timedelta

from fastapi import APIRouter, Query, status

from src.core.deps import DbSession
from src.core.exceptions import ValidationError
from src.core.timeutils import moscow_today
from src.modules.advertising.deps import AdvertisingServiceDep
from src.modules.advertising.schemas import AdvertisingResponse, AdvertisingSpan
from src.modules.workspaces.contract import CurrentWorkspaceId

#: Default window when the caller names no dates: the last thirty days, the
#: span a seller reviews an advertising budget over.
DEFAULT_WINDOW_DAYS = 29

#: Hard cap on one request — sized to «Вся история», like «Сводка»'s.
#:
#: WB keeps advertising statistics for a campaign's whole life (no retention
#: cliff; «Демо» goes back to 2023-10-24), so a cap below the кабинет's own
#: history would make the «Вся история» button an error. Measured 2026-10-05:
#: that whole span answers in ~1 s on «Демо». The bound still has to exist —
#: an unbounded window is a cheap way for one caller to keep Postgres busy.
MAX_WINDOW_DAYS = 1200

router = APIRouter()


def _resolve_window(date_from: date | None, date_to: date | None) -> tuple[date, date]:
    """Fill and bound the requested window, in Moscow days.

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
    "/advertising/span",
    response_model=AdvertisingSpan,
    status_code=status.HTTP_200_OK,
    responses={
        200: {"description": "Дни, за которые у кабинета есть реклама."},
        401: {"description": "Unauthorized access token."},
        403: {"description": "Раздел доступен только внутренним учётным записям."},
    },
)
async def get_advertising_span(
    service: AdvertisingServiceDep, session: DbSession, workspace_id: CurrentWorkspaceId
) -> AdvertisingSpan:
    """Return the days this кабинет has advertising for, before a window is chosen."""
    return await service.span(session, workspace_id=workspace_id)


@router.get(
    "/advertising",
    response_model=AdvertisingResponse,
    status_code=status.HTTP_200_OK,
    responses={
        200: {"description": "Реклама кабинета за период."},
        401: {"description": "Unauthorized access token."},
        403: {"description": "Раздел доступен только внутренним учётным записям."},
        422: {"description": "Период инвертирован или длиннее допустимого."},
    },
)
async def get_advertising(
    service: AdvertisingServiceDep,
    workspace_id: CurrentWorkspaceId,
    session: DbSession,
    date_from: date | None = Query(default=None, description="Inclusive day start."),
    date_to: date | None = Query(default=None, description="Inclusive day end."),
) -> AdvertisingResponse:
    """Return every figure the «Реклама» page draws for one window.

    **This GET may write, as «Сводка»'s does**: reading settled sales fills the
    settlement rollup for days it did not already cover. Nothing the caller
    sends decides what is written — it is derived from the кабинет's own
    settlement rows, under the tenant :data:`CurrentWorkspaceId` binds.
    """
    start, end = _resolve_window(date_from, date_to)
    return await service.build(session, workspace_id=workspace_id, date_from=start, date_to=end)
