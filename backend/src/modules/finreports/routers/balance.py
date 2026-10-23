"""HTTP routes for "Stock balance" — the stock-balance grid.

Pure pass-through (no business logic), guarded by the access-token dependency
declared on the aggregating router. Everything is workspace-scoped through
``X-Workspace-Id``: the grid is built from the seller's stock and their own cost
prices, so neither half may ever be resolved without tenancy.

The stock itself belongs to the monitoring module and is resolved here through
its contract — the same pattern ``GET /pnl/skus`` uses for orders and
advertising, and the reason this router (not the service) picks the day: which
day exists is a fact about monitoring's snapshots, not about the balance.
"""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Query, Response, status

from src.core.deps import DbSession
from src.modules.finreports.deps import BalanceServiceDep
from src.modules.finreports.schemas import BalancePinInput, BalanceResponse
from src.modules.monitoring.contract import (
    load_stock_by_warehouse,
    load_vendor_codes,
    stock_day_span,
)
from src.modules.organizations.contract import WritingAccess
from src.modules.workspaces.contract import CurrentWorkspaceId

router = APIRouter()


@router.get(
    "/balance",
    response_model=BalanceResponse,
    status_code=status.HTTP_200_OK,
    responses={
        200: {"description": "The SKU x warehouse stock balance for one day."},
        401: {"description": "Unauthorized access token."},
        403: {"description": "Subscription expired — read-only access."},
    },
)
async def get_balance(
    service: BalanceServiceDep,
    workspace_id: CurrentWorkspaceId,
    session: DbSession,
    stat_date: date | None = Query(
        default=None, description="Snapshot day; defaults to the newest one on record."
    ),
) -> BalanceResponse:
    """Return the stock balance grid for one snapshot day.

    Stock is a point-in-time snapshot with no carry-over, so the day is picked,
    never a range. Asking for a day WB never reported returns an empty grid
    carrying a note that says so, rather than the previous day's stock under
    today's date.
    """
    span = await stock_day_span(session, workspace_id=workspace_id)
    day = stat_date or span[1] or date.today()
    return await service.get_balance(
        workspace_id=workspace_id,
        stat_date=day,
        stock=await load_stock_by_warehouse(session, workspace_id=workspace_id, stat_date=day),
        vendor_codes=await load_vendor_codes(session, workspace_id=workspace_id),
        span=span,
    )


@router.put(
    "/balance/pins",
    status_code=status.HTTP_204_NO_CONTENT,
    responses={
        204: {"description": "Row or column marked, or unmarked."},
        401: {"description": "Unauthorized access token."},
        403: {"description": "Subscription expired — read-only access."},
    },
)
async def set_balance_pin(
    _writer: WritingAccess,
    payload: BalancePinInput,
    service: BalanceServiceDep,
    workspace_id: CurrentWorkspaceId,
) -> Response:
    """Mark ("Don't count") a SKU row or a warehouse column, or clear the mark.

    Stored per workspace, so the marks are shared across its users. A mark
    changes only what the grid's totals are drawn from and where the row or
    column sorts — never a quantity or a cost. Idempotent in both directions.
    """
    await service.set_pin(
        workspace_id=workspace_id,
        kind=payload.kind,
        value=payload.value,
        pinned=payload.pinned,
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)
