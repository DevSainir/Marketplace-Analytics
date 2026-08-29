"""HTTP presentation layer for the Monitoring module.

Routers are pure pass-through: they receive request parameters and return the
service result. They contain **no** business logic, **no** window resolution,
and **no** error-to-HTTP mapping — domain errors raised by the service
(``NotFoundError``, ``ValidationError``, ...) propagate to the global
``AppError`` handler in ``main.py``, which maps them to HTTP responses.

Every endpoint requires a valid access token (router-level dependency), and
every data endpoint additionally requires the ``X-Workspace-Id`` header — which
is validated against the caller's own organisation, not merely for existence. The
listing/lookup routes scope their queries by it, while the per-SKU routes pass
their path ``nm_id`` through the :data:`WorkspaceSku` ownership guard so a SKU
belonging to another workspace is indistinguishable from a nonexistent one.
"""

from __future__ import annotations

from datetime import date
from typing import Literal

from fastapi import APIRouter, Depends, Query, status

from src.modules.monitoring.constants import MAX_NM_IDS_PER_REQUEST
from src.modules.monitoring.deps import AnalyticsServiceDep, CurrentWorkspaceId, WorkspaceSku
from src.modules.monitoring.routers.clusters import router as clusters_router
from src.modules.monitoring.routers.refresh import router as refresh_router
from src.modules.monitoring.schemas import (
    AggregateChartsResponse,
    CommentUpdateRequest,
    DayActionResponse,
    DayActionState,
    DayCommentResponse,
    FunnelResponseSchema,
    MatrixPreviewRequest,
    MatrixPreviewResponse,
    MatrixSaveRequest,
    PinColorUpdateRequest,
    PinnedSkusResponse,
    PinReorderRequest,
    PinUpdateRequest,
    SkuDetailResponse,
    SkuLookupResponse,
    SkuSummaryListResponse,
    StockDayResponse,
    WarehouseMarksResponse,
    WarehouseMarkUpdateRequest,
)
from src.modules.organizations.contract import require_member

router = APIRouter(
    prefix="/v1/monitoring",
    tags=["Monitoring"],
    # Membership guard applied to every route in this module. Authentication
    # alone is no longer enough: registration is open, so a bare account must
    # not reach a data route at all. The workspace dependency re-checks tenancy
    # per request on top of this.
    dependencies=[Depends(require_member)],
)
# The WB re-harvest trigger surface (enqueue + poll) lives in its own module;
# it inherits this router's prefix and access-token dependency.
router.include_router(refresh_router)
# «Поиск по кластерам» — the keyword search over harvested search clusters plus
# the live WB-search position probe. Declared BEFORE the ``/skus/{nm_id}``
# routes for the same reason ``/skus/lookup`` is: a static path must not be
# shadowed by a typed path parameter.
router.include_router(clusters_router)


@router.get(
    "/summary",
    response_model=SkuSummaryListResponse,
    status_code=status.HTTP_200_OK,
    responses={
        200: {"description": "Per-SKU summary listing for the window."},
        401: {"description": "Unauthorized access token."},
        422: {"description": "Invalid date window."},
    },
)
async def get_summary(
    service: AnalyticsServiceDep,
    workspace_id: CurrentWorkspaceId,
    date_from: date | None = Query(default=None, description="Inclusive start."),
    date_to: date | None = Query(default=None, description="Inclusive end."),
    limit: int = Query(default=100, ge=1, le=500, description="Page size."),
    offset: int = Query(default=0, ge=0, description="Page offset (by SKU order)."),
) -> SkuSummaryListResponse:
    """Return the compact per-SKU summary listing (dashboard view)."""
    return await service.get_summary(
        workspace_id=workspace_id,
        date_from=date_from,
        date_to=date_to,
        limit=limit,
        offset=offset,
    )


@router.get(
    "/charts",
    response_model=AggregateChartsResponse,
    status_code=status.HTTP_200_OK,
    responses={
        200: {"description": "Account-wide daily series for the window."},
        401: {"description": "Unauthorized access token."},
        422: {"description": "Invalid date window."},
    },
)
async def get_aggregate_charts(
    service: AnalyticsServiceDep,
    workspace_id: CurrentWorkspaceId,
    date_from: date | None = Query(default=None, description="Inclusive start."),
    date_to: date | None = Query(default=None, description="Inclusive end."),
    nm_ids: list[int] | None = Query(
        default=None,
        max_length=MAX_NM_IDS_PER_REQUEST,
        description=(
            "SKUs to include. Repeat the parameter for several; omit it "
            "entirely for every SKU in the workspace, which is what the page "
            "shows by default."
        ),
    ),
) -> AggregateChartsResponse:
    """Return the «Графики» page's day series, summed over the chosen SKUs."""
    return await service.get_aggregate_charts(
        workspace_id=workspace_id,
        date_from=date_from,
        date_to=date_to,
        nm_ids=nm_ids,
    )


@router.get(
    "/pins",
    response_model=PinnedSkusResponse,
    status_code=status.HTTP_200_OK,
    responses={
        200: {"description": "The global pinned-SKU list, in chip-row order."},
        401: {"description": "Unauthorized access token."},
    },
)
async def list_pins(
    service: AnalyticsServiceDep,
    workspace_id: CurrentWorkspaceId,
) -> PinnedSkusResponse:
    """Return the workspace's pinned-SKU chip row (shared by every account)."""
    return await service.list_pinned_skus(workspace_id=workspace_id)


@router.put(
    "/pins/order",
    response_model=PinnedSkusResponse,
    status_code=status.HTTP_200_OK,
    responses={
        200: {"description": "Order saved; the reordered pinned list is returned."},
        401: {"description": "Unauthorized access token."},
        422: {"description": "The list is not exactly the current pinned set."},
    },
)
async def reorder_pins(
    body: PinReorderRequest,
    service: AnalyticsServiceDep,
    workspace_id: CurrentWorkspaceId,
) -> PinnedSkusResponse:
    """Persist the chip row's order after a drag-and-drop (shared by everyone).

    The body carries every pinned SKU, so the service can reject a reorder
    computed against a list a teammate has since changed. No ``WorkspaceSku``
    guard here — the identifiers are in the body, not the path, so the service
    validates them against the workspace's own pins instead.
    """
    return await service.reorder_pins(workspace_id=workspace_id, nm_ids=body.nm_ids)


@router.put(
    "/skus/{nm_id}/pin",
    response_model=PinnedSkusResponse,
    status_code=status.HTTP_200_OK,
    responses={
        200: {"description": "Pin updated; the full pinned list is returned."},
        401: {"description": "Unauthorized access token."},
        422: {"description": "Invalid payload."},
    },
)
async def set_pin(
    nm_id: WorkspaceSku,
    body: PinUpdateRequest,
    service: AnalyticsServiceDep,
    workspace_id: CurrentWorkspaceId,
) -> PinnedSkusResponse:
    """Pin («Закрепить») or unpin («Закреплено» click) a SKU for everyone."""
    return await service.set_sku_pin(workspace_id=workspace_id, nm_id=nm_id, pinned=body.pinned)


@router.put(
    "/skus/{nm_id}/pin-color",
    response_model=PinnedSkusResponse,
    status_code=status.HTTP_200_OK,
    responses={
        200: {"description": "Chip painted; the full pinned list is returned."},
        401: {"description": "Unauthorized access token."},
        422: {"description": "Invalid payload (colour is not #rrggbb)."},
    },
)
async def set_pin_color(
    nm_id: WorkspaceSku,
    body: PinColorUpdateRequest,
    service: AnalyticsServiceDep,
    workspace_id: CurrentWorkspaceId,
) -> PinnedSkusResponse:
    """Paint a pinned chip's background, or clear its tint, for everyone."""
    return await service.set_sku_color(workspace_id=workspace_id, nm_id=nm_id, color=body.color)


@router.get(
    "/skus/lookup",
    response_model=SkuLookupResponse,
    status_code=status.HTTP_200_OK,
    responses={
        200: {"description": "SKUs matching the vendor-code search."},
        401: {"description": "Unauthorized access token."},
        422: {"description": "Blank vendor code."},
    },
)
async def lookup_skus(
    service: AnalyticsServiceDep,
    workspace_id: CurrentWorkspaceId,
    vendor_code: str = Query(
        min_length=1,
        description="Seller article code or fragment (e.g. 'M-TRX01' or 'M-TRX01-BLK').",
    ),
) -> SkuLookupResponse:
    """Resolve a seller vendor code (or fragment) to matching SKU identifiers.

    Declared before ``/skus/{nm_id}`` so the static ``lookup`` path is not
    swallowed by the typed integer path parameter.
    """
    return await service.lookup_skus_by_vendor_code(vendor_code, workspace_id=workspace_id)


@router.get(
    "/skus/{nm_id}",
    response_model=SkuDetailResponse,
    status_code=status.HTTP_200_OK,
    responses={
        200: {"description": "Full detailed view for one SKU."},
        401: {"description": "Unauthorized access token."},
        404: {"description": "No monitoring data for the SKU in the window."},
        422: {"description": "Invalid date window."},
    },
)
async def get_sku_detail(
    nm_id: WorkspaceSku,
    service: AnalyticsServiceDep,
    date_from: date | None = Query(default=None, description="Inclusive start."),
    date_to: date | None = Query(default=None, description="Inclusive end."),
    campaign_id: int | None = Query(
        default=None, description="Filter advertising to one campaign."
    ),
    # Literal instead of free text: a typo ("actve") should be a 422, not a
    # silently empty advertising list.
    campaign_status: (
        Literal["active", "paused", "completed", "ready", "declined", "deleting", "unknown"] | None
    ) = Query(
        default=None,
        description="Filter to campaigns of this normalized status.",
    ),
) -> SkuDetailResponse:
    """Return the full detailed view for a single SKU across all metrics."""
    return await service.get_detail(
        nm_id=nm_id,
        date_from=date_from,
        date_to=date_to,
        campaign_id=campaign_id,
        campaign_status=campaign_status,
    )


@router.get(
    "/skus/{nm_id}/stock",
    response_model=StockDayResponse,
    status_code=status.HTTP_200_OK,
    responses={
        200: {"description": "The day's size x warehouse stock breakdown."},
        401: {"description": "Unauthorized access token."},
        422: {"description": "Invalid date."},
    },
)
async def get_stock_day(
    nm_id: WorkspaceSku,
    service: AnalyticsServiceDep,
    on_date: date = Query(description="Exact snapshot day (empty breakdown when unobserved)."),
) -> StockDayResponse:
    """Return one snapshot day's stock breakdown (two-day comparison view)."""
    return await service.get_stock_day(nm_id=nm_id, on_date=on_date)


@router.put(
    "/skus/{nm_id}/warehouse-marks",
    response_model=WarehouseMarksResponse,
    status_code=status.HTTP_200_OK,
    responses={
        200: {"description": "Mark updated; the SKU's marked warehouses are returned."},
        401: {"description": "Unauthorized access token."},
        422: {"description": "Invalid payload."},
    },
)
async def set_warehouse_mark(
    nm_id: WorkspaceSku,
    body: WarehouseMarkUpdateRequest,
    service: AnalyticsServiceDep,
) -> WarehouseMarksResponse:
    """Mark («Отгрузить») or unmark («Разгрузить») a warehouse for this SKU only."""
    return await service.set_warehouse_mark(
        nm_id=nm_id, warehouse_name=body.warehouse_name, marked=body.marked
    )


@router.put(
    "/skus/{nm_id}/comments/{comment_date}",
    response_model=DayCommentResponse,
    status_code=status.HTTP_200_OK,
    responses={
        200: {"description": "Comment saved (or cleared); the stored note is returned."},
        401: {"description": "Unauthorized access token."},
        422: {"description": "Invalid payload (e.g. body too long) or date."},
    },
)
async def set_day_comment(
    nm_id: WorkspaceSku,
    comment_date: date,
    body: CommentUpdateRequest,
    service: AnalyticsServiceDep,
) -> DayCommentResponse:
    """Save one day's note on a SKU — its comment, its header, or both.

    Omitted fields keep their stored value, so the two inputs save
    independently; blanking both clears the day. Notes are shared by everyone.
    """
    return await service.set_day_note(
        nm_id=nm_id, comment_date=comment_date, body=body.body, header=body.header
    )


@router.put(
    "/skus/{nm_id}/actions/{action_date}",
    response_model=DayActionResponse,
    status_code=status.HTTP_200_OK,
    responses={
        200: {"description": "Day actions saved (or cleared); the stored state is returned."},
        401: {"description": "Unauthorized access token."},
        422: {"description": "Invalid payload (e.g. negative budget) or date."},
    },
)
async def set_day_action(
    nm_id: WorkspaceSku,
    action_date: date,
    body: DayActionState,
    service: AnalyticsServiceDep,
) -> DayActionResponse:
    """Save one day's «Действия» row on a SKU (shared by everyone).

    The body is the WHOLE day state (last write wins); a body with every
    answer null clears the day's row.
    """
    return await service.set_day_action(nm_id=nm_id, action_date=action_date, action=body)


@router.post(
    "/skus/{nm_id}/matrix/preview",
    response_model=MatrixPreviewResponse,
    status_code=status.HTTP_200_OK,
    responses={
        200: {"description": "Recomputed working copy + matrix after one edit."},
        401: {"description": "Unauthorized access token."},
        422: {"description": "Edit targets a read-only / non-invertible cell."},
    },
)
async def preview_matrix_edit(
    nm_id: WorkspaceSku,
    body: MatrixPreviewRequest,
    service: AnalyticsServiceDep,
) -> MatrixPreviewResponse:
    """Apply one pending cell-edit to the working copy and recompute (no save).

    The frontend holds the working copy; this resolves the edit into its inputs
    (setting an input, or reverse-solving one for a derived cell) and returns
    the recomputed matrix. Nothing is persisted — «Сохранить» does that.
    """
    return service.preview_matrix_edit(body.base, body.edit, nm_id=nm_id)


@router.put(
    "/skus/{nm_id}/matrix",
    response_model=SkuDetailResponse,
    status_code=status.HTTP_200_OK,
    responses={
        200: {"description": "Overrides saved; the refreshed detail is returned."},
        401: {"description": "Unauthorized access token."},
        422: {"description": "Invalid date window."},
    },
)
async def save_matrix(
    nm_id: WorkspaceSku,
    body: MatrixSaveRequest,
    service: AnalyticsServiceDep,
    date_from: date | None = Query(default=None, description="Inclusive start."),
    date_to: date | None = Query(default=None, description="Inclusive end."),
) -> SkuDetailResponse:
    """Persist the manual edits as overrides and return the refreshed detail."""
    return await service.save_matrix(
        nm_id=nm_id, base=body.base, date_from=date_from, date_to=date_to
    )


@router.get(
    "/funnel/{nm_id}",
    response_model=FunnelResponseSchema,
    status_code=status.HTTP_200_OK,
    responses={
        200: {"description": "Raw organic funnel for the SKU."},
        401: {"description": "Unauthorized access token."},
        404: {"description": "SKU funnel metrics not found."},
        422: {"description": "Invalid date window."},
    },
)
async def get_sku_funnel(
    nm_id: WorkspaceSku,
    service: AnalyticsServiceDep,
    date_from: date | None = Query(default=None, description="Inclusive start."),
    date_to: date | None = Query(default=None, description="Inclusive end."),
) -> FunnelResponseSchema:
    """Expose the raw organic sales funnel for a single SKU."""
    return await service.get_sku_funnel(nm_id, date_from=date_from, date_to=date_to)
