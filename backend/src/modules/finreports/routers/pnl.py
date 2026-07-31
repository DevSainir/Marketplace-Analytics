"""HTTP routes for the P&L statement and the cost-price editor.

Pure pass-through (no business logic), guarded by the access-token dependency
declared on the aggregating router. Everything is workspace-scoped through
``X-Workspace-Id``: cost prices are the seller's own commercial data and a
statement is their revenue, so neither may ever be resolved without tenancy.
"""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Query, Response, status

from src.core.deps import DbSession
from src.modules.finreports.deps import (
    CostPriceServiceDep,
    PnlServiceDep,
    SkuReportServiceDep,
)
from src.modules.finreports.repos import PnlGrouping
from src.modules.finreports.routers.window import resolve_window
from src.modules.finreports.schemas import (
    CostPriceBulkInput,
    CostPriceListResponse,
    CostPriceSaveResponse,
    PnlResponse,
    PnlSkuReportResponse,
    SkuExclusionInput,
)
from src.modules.monitoring.contract import (
    ad_coverage,
    funnel_coverage,
    load_ad_spend_by_nm,
    load_orders_by_nm,
)
from src.modules.workspaces.contract import CurrentWorkspaceId

router = APIRouter()


@router.get(
    "/pnl",
    response_model=PnlResponse,
    status_code=status.HTTP_200_OK,
    responses={
        200: {"description": "Settlement-basis P&L for the window."},
        401: {"description": "Unauthorized access token."},
    },
)
async def get_pnl(
    service: PnlServiceDep,
    workspace_id: CurrentWorkspaceId,
    date_from: date | None = Query(default=None, description="Inclusive settlement-date start."),
    date_to: date | None = Query(default=None, description="Inclusive settlement-date end."),
    grouping: PnlGrouping = Query(
        default=PnlGrouping.WEEK, description="How the breakdown rows are cut."
    ),
) -> PnlResponse:
    """Return the profit-and-loss statement for a settlement-date window.

    Built entirely from WB's weekly report detail plus the seller's own cost
    prices. The response carries its own caveats in ``notes`` — cost coverage,
    unbackfilled columns, operations the taxonomy does not recognise — because
    every one of them changes how the bottom line should be read.
    """
    start, end = resolve_window(date_from, date_to)
    return await service.get_statement(
        workspace_id=workspace_id, date_from=start, date_to=end, grouping=grouping
    )


@router.get(
    "/pnl/skus",
    response_model=PnlSkuReportResponse,
    status_code=status.HTTP_200_OK,
    responses={
        200: {"description": "Per-SKU P&L rows for the window («По артикулам»)."},
        401: {"description": "Unauthorized access token."},
    },
)
async def get_pnl_by_sku(
    service: SkuReportServiceDep,
    workspace_id: CurrentWorkspaceId,
    session: DbSession,
    date_from: date | None = Query(default=None, description="Inclusive settlement-date start."),
    date_to: date | None = Query(default=None, description="Inclusive settlement-date end."),
) -> PnlSkuReportResponse:
    """Return the per-SKU P&L cut for an arbitrary settlement-date window.

    Two columns come from the monitoring module, resolved here through its
    orders from the funnel history and per-SKU advertising from the Promotion
    API statistics — the settlement report itself carries neither.
    """
    start, end = resolve_window(date_from, date_to)
    return await service.get_report(
        workspace_id=workspace_id,
        date_from=start,
        date_to=end,
        orders=await load_orders_by_nm(session, date_from=start, date_to=end),
        ad_spend=await load_ad_spend_by_nm(session, date_from=start, date_to=end),
        funnel_span=await funnel_coverage(session, date_from=start, date_to=end),
        ad_span=await ad_coverage(session, date_from=start, date_to=end),
    )


@router.put(
    "/pnl/skus/{nm_id}/exclusion",
    status_code=status.HTTP_204_NO_CONTENT,
    responses={
        204: {"description": "SKU marked «Не включать в общий счёт», or cleared."},
        401: {"description": "Unauthorized access token."},
    },
)
async def set_sku_exclusion(
    nm_id: int,
    payload: SkuExclusionInput,
    service: SkuReportServiceDep,
    workspace_id: CurrentWorkspaceId,
) -> Response:
    """Mark or clear one SKU's «Не включать в общий счёт» flag.

    The mark is stored per workspace, so it is shared across the workspace's
    users, and it changes only the dashboard's «общий счёт» — the per-SKU rows
    and the reconciled totals are unaffected. Idempotent in both directions.
    """
    await service.set_exclusion(workspace_id=workspace_id, nm_id=nm_id, excluded=payload.excluded)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get(
    "/cost-prices",
    response_model=CostPriceListResponse,
    status_code=status.HTTP_200_OK,
    responses={
        200: {"description": "Cost prices on file, plus SKUs still missing one."},
        401: {"description": "Unauthorized access token."},
    },
)
async def list_cost_prices(
    service: CostPriceServiceDep,
    workspace_id: CurrentWorkspaceId,
) -> CostPriceListResponse:
    """List the seller's per-SKU cost prices and the gaps in them."""
    return await service.list_cost_prices(workspace_id=workspace_id)


@router.put(
    "/cost-prices",
    response_model=CostPriceSaveResponse,
    status_code=status.HTTP_200_OK,
    responses={
        200: {"description": "Cost prices saved."},
        401: {"description": "Unauthorized access token."},
        422: {"description": "A negative/absurd cost, or one nm_id twice."},
    },
)
async def save_cost_prices(
    payload: CostPriceBulkInput,
    service: CostPriceServiceDep,
    workspace_id: CurrentWorkspaceId,
) -> CostPriceSaveResponse:
    """Insert or overwrite a batch of cost prices.

    A whole-grid save, so the editor never has to sequence per-row requests and
    a partially-applied save cannot leave the margin half-restated.
    """
    return await service.save_cost_prices(workspace_id=workspace_id, items=payload.items)


@router.delete(
    "/cost-prices/{nm_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    responses={
        204: {"description": "Cost price removed (or was already absent)."},
        401: {"description": "Unauthorized access token."},
    },
)
async def delete_cost_price(
    nm_id: int,
    service: CostPriceServiceDep,
    workspace_id: CurrentWorkspaceId,
) -> Response:
    """Clear one SKU's cost price, returning it to the "uncosted" list."""
    await service.delete_cost_price(workspace_id=workspace_id, nm_id=nm_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
