"""HTTP presentation layer for the Monitoring module.

Routers are pure pass-through: they receive request parameters and return the
service result. They contain **no** business logic, **no** window resolution,
and **no** error-to-HTTP mapping — domain errors raised by the service
(``NotFoundError``, ``ValidationError``, ...) propagate to the global
``AppError`` handler in ``main.py``, which maps them to HTTP responses.

Every endpoint requires a valid access token (router-level dependency).
"""

from __future__ import annotations

from datetime import date
from typing import Literal

from fastapi import APIRouter, Depends, Query, status

from src.core.deps import get_current_user_id
from src.modules.monitoring.deps import AnalyticsServiceDep
from src.modules.monitoring.schemas import (
    FunnelResponseSchema,
    SkuDetailResponse,
    SkuLookupResponse,
    SkuSummaryListResponse,
)

router = APIRouter(
    prefix="/v1/monitoring",
    tags=["Monitoring"],
    # Authentication guard applied to every route in this module.
    dependencies=[Depends(get_current_user_id)],
)


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
    date_from: date | None = Query(default=None, description="Inclusive start."),
    date_to: date | None = Query(default=None, description="Inclusive end."),
    limit: int = Query(default=100, ge=1, le=500, description="Page size."),
    offset: int = Query(default=0, ge=0, description="Page offset (by SKU order)."),
) -> SkuSummaryListResponse:
    """Return the compact per-SKU summary listing (dashboard view)."""
    return await service.get_summary(
        date_from=date_from, date_to=date_to, limit=limit, offset=offset
    )


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
    vendor_code: str = Query(
        min_length=1,
        description="Seller article code or fragment (e.g. 'M-TRX01' or 'M-TRX01-BLK').",
    ),
) -> SkuLookupResponse:
    """Resolve a seller vendor code (or fragment) to matching SKU identifiers.

    Declared before ``/skus/{nm_id}`` so the static ``lookup`` path is not
    swallowed by the typed integer path parameter.
    """
    return await service.lookup_skus_by_vendor_code(vendor_code)


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
    nm_id: int,
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
    nm_id: int,
    service: AnalyticsServiceDep,
    date_from: date | None = Query(default=None, description="Inclusive start."),
    date_to: date | None = Query(default=None, description="Inclusive end."),
) -> FunnelResponseSchema:
    """Expose the raw organic sales funnel for a single SKU."""
    return await service.get_sku_funnel(nm_id, date_from=date_from, date_to=date_to)
