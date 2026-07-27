"""HTTP presentation layer for the ``finreports`` module.

Pure pass-through routers (no business logic), guarded by the access-token
per-SKU evidence route is looked up by the globally-unique WB ``nm_id``.

Domain errors raised by the service propagate to the global ``AppError`` handler
in ``main.py``; the router maps nothing itself.
"""

from __future__ import annotations

from datetime import date, timedelta

from fastapi import APIRouter, Depends, Query, Response, status

from src.core.deps import DbSession, get_current_user_id
from src.core.timeutils import moscow_today
from src.modules.finreports.schemas import (
    WeeksResponse,
)
from src.modules.workspaces.contract import CurrentWorkspaceId, load_workspace_name

router = APIRouter(
    prefix="/v1/finreports",
    tags=["FinReports"],
    dependencies=[Depends(get_current_user_id)],
)

#: Default reporting window when the caller passes no dates (last full 4 weeks).
_DEFAULT_WINDOW_DAYS = 28


def _resolve_window(date_from: date | None, date_to: date | None) -> tuple[date, date]:
    """Fill a missing settlement-date window with a sane default (last 4 weeks).

    "Today" is the MOSCOW day (:func:`~src.core.timeutils.moscow_today`), not the
    server's: WB dates every settlement row by the Moscow calendar, so on a UTC
    host ``date.today()`` resolves a window one day short between 00:00 and
    03:00 MSK — silently dropping the most recent settlement day.
    """
    end = date_to or moscow_today()
    start = date_from or (end - timedelta(days=_DEFAULT_WINDOW_DAYS))
    return start, end


@router.get(
    "/weeks",
    response_model=WeeksResponse,
    status_code=status.HTTP_200_OK,
    responses={
        200: {"description": "Harvested weekly report periods (newest first)."},
        401: {"description": "Unauthorized access token."},
    },
)
async def list_weeks(
    workspace_id: CurrentWorkspaceId,
) -> WeeksResponse:
    """List the WB weekly report periods, for the summary's week selector."""
    return await service.list_weeks(workspace_id=workspace_id)


@router.get(
    status_code=status.HTTP_200_OK,
    responses={
        401: {"description": "Unauthorized access token."},
    },
)
    workspace_id: CurrentWorkspaceId,
    date_from: date | None = Query(default=None, description="Inclusive settlement-date start."),
    date_to: date | None = Query(default=None, description="Inclusive settlement-date end."),
    start, end = _resolve_window(date_from, date_to)


@router.get(
    status_code=status.HTTP_200_OK,
    responses={
        401: {"description": "Unauthorized access token."},
    },
)
    nm_id: int,
    workspace_id: CurrentWorkspaceId,
    date_from: date | None = Query(default=None, description="Inclusive settlement-date start."),
    date_to: date | None = Query(default=None, description="Inclusive settlement-date end."),
    start, end = _resolve_window(date_from, date_to)
        workspace_id=workspace_id, nm_id=nm_id, date_from=start, date_to=end
    )


@router.get(
    status_code=status.HTTP_200_OK,
    response_class=Response,
    responses={
        200: {
            "content": {"application/zip": {}},
        },
        401: {"description": "Unauthorized access token."},
    },
)
    workspace_id: CurrentWorkspaceId,
    session: DbSession,
    date_from: date | None = Query(default=None, description="Inclusive settlement-date start."),
    date_to: date | None = Query(default=None, description="Inclusive settlement-date end."),
) -> Response:

    the printable per-report summary, the line-by-line ledger with the
    """
    start, end = _resolve_window(date_from, date_to)
    seller_name = await load_workspace_name(session, workspace_id)
    blob, filename = await service.build_package(
        workspace_id=workspace_id,
        seller_name=seller_name or "Продавец",
        date_from=start,
        date_to=end,
    )
    return Response(
        content=blob,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
