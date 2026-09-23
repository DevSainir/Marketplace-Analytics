"""HTTP routes for the P&L statement and the cost-price editor.

Pure pass-through (no business logic), guarded by the access-token dependency
declared on the aggregating router. Everything is workspace-scoped through
``X-Workspace-Id``: cost prices are the seller's own commercial data and a
statement is their revenue, so neither may ever be resolved without tenancy.
"""

from __future__ import annotations

from datetime import date
from urllib.parse import quote

from fastapi import APIRouter, File, Query, Response, UploadFile, status

from src.core.deps import DbSession
from src.core.exceptions import ValidationError
from src.core.uploads import read_capped
from src.modules.finreports.deps import (
    CostPriceServiceDep,
    PnlServiceDep,
    SkuReportServiceDep,
)
from src.modules.finreports.repos import PnlGrouping
from src.modules.finreports.routers.window import resolve_window
from src.modules.finreports.schemas import (
    CostPriceBulkInput,
    CostPriceImportResponse,
    CostPriceListResponse,
    CostPriceSaveResponse,
    PnlResponse,
    PnlSizesResponse,
    PnlSkuReportResponse,
    SkuExclusionInput,
    WeeksResponse,
)
from src.modules.monitoring.contract import (
    ad_bonus_coverage,
    ad_bonus_currencies,
    ad_bonus_unknown_types,
    ad_coverage,
    funnel_coverage,
    load_ad_bonus_by_nm,
    load_ad_spend_by_nm,
    load_card_photos,
    load_orders_by_nm,
)
from src.modules.organizations.contract import WritingAccess
from src.modules.workspaces.contract import CurrentWorkspaceId

#: The OOXML spreadsheet media type — what browsers map to an ``.xlsx`` download.
_XLSX_MEDIA_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

#: Downloaded file name. ASCII fallback for `filename=`, the Cyrillic real name
#: goes in the RFC 5987 `filename*` field so it survives older clients.
_EXPORT_ASCII_NAME = "pnl-cost-prices.xlsx"
_EXPORT_UTF8_NAME = "P&L себестоимость.xlsx"

#: Cap on an uploaded workbook. The grid is at most a few thousand SKUs, so a
#: legitimate file is tens of KB; this simply refuses a multi-MB paste before it
#: reaches the parser and is measured in the request body, not after.
_MAX_UPLOAD_BYTES = 10 * 1024 * 1024

router = APIRouter()


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
    """List the WB weekly report periods the seller has data for.

    it is what every finreports page's period selector is built from: the SPA
    reads the full settlement span from this to pick a default window and to
    with them left a customer's P&L unable to choose a period at all.
    """
    return await service.list_weeks(workspace_id=workspace_id)


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

    Three things come from the monitoring module, resolved here through its
    orders from the funnel history, per-SKU advertising from the Promotion API
    statistics, and the card thumbnails — the settlement report carries an
    article string and no catalogue at all.
    """
    start, end = resolve_window(date_from, date_to)
    return await service.get_report(
        workspace_id=workspace_id,
        date_from=start,
        date_to=end,
        orders=await load_orders_by_nm(
            session, workspace_id=workspace_id, date_from=start, date_to=end
        ),
        ad_spend=await load_ad_spend_by_nm(
            session, workspace_id=workspace_id, date_from=start, date_to=end
        ),
        ad_bonus=await load_ad_bonus_by_nm(
            session, workspace_id=workspace_id, date_from=start, date_to=end
        ),
        bonus_span=await ad_bonus_coverage(
            session, workspace_id=workspace_id, date_from=start, date_to=end
        ),
        bonus_currencies=await ad_bonus_currencies(
            session, workspace_id=workspace_id, date_from=start, date_to=end
        ),
        unknown_funding=await ad_bonus_unknown_types(
            session, workspace_id=workspace_id, date_from=start, date_to=end
        ),
        funnel_span=await funnel_coverage(
            session, workspace_id=workspace_id, date_from=start, date_to=end
        ),
        ad_span=await ad_coverage(session, workspace_id=workspace_id, date_from=start, date_to=end),
        photos=await load_card_photos(session, workspace_id=workspace_id),
    )


@router.get(
    "/pnl/skus/{nm_id}/sizes",
    response_model=PnlSizesResponse,
    status_code=status.HTTP_200_OK,
    responses={
        200: {"description": "Per-size P&L rows for one article («подтаблица размеров»)."},
        401: {"description": "Unauthorized access token."},
    },
)
async def get_pnl_sizes(
    nm_id: int,
    service: SkuReportServiceDep,
    workspace_id: CurrentWorkspaceId,
    date_from: date | None = Query(default=None, description="Inclusive settlement-date start."),
    date_to: date | None = Query(default=None, description="Inclusive settlement-date end."),
) -> PnlSizesResponse:
    """Return one article's settlement rows cut by WB's size label.

    The drill-down the «По артикулам» table opens under a row. Nothing here
    comes from outside the settlement detail — WB stamps ``ts_name`` on every
    row it bills, so the sizes are a regrouping of the article's own rows and
    sum back to it. Advertising has no size and is therefore absent, which the
    profit column says in its name rather than in a footnote.
    """
    start, end = resolve_window(date_from, date_to)
    return await service.get_sizes(
        workspace_id=workspace_id, nm_id=nm_id, date_from=start, date_to=end
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
    _writer: WritingAccess,
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
    _writer: WritingAccess,
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
    _writer: WritingAccess,
    nm_id: int,
    service: CostPriceServiceDep,
    workspace_id: CurrentWorkspaceId,
) -> Response:
    """Clear one SKU's cost price, returning it to the "uncosted" list."""
    await service.delete_cost_price(workspace_id=workspace_id, nm_id=nm_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get(
    "/cost-prices/export",
    response_class=Response,
    status_code=status.HTTP_200_OK,
    responses={
        200: {
            "description": "The cost-price grid as an editable XLSX workbook.",
            "content": {_XLSX_MEDIA_TYPE: {}},
        },
        401: {"description": "Unauthorized access token."},
    },
)
async def export_cost_prices(
    service: SkuReportServiceDep,
    workspace_id: CurrentWorkspaceId,
    session: DbSession,
    date_from: date | None = Query(default=None, description="Inclusive settlement-date start."),
    date_to: date | None = Query(default=None, description="Inclusive settlement-date end."),
) -> Response:
    """Download the per-SKU P&L as an XLSX for bulk offline cost entry.

    The same «По артикулам» statement the screen shows, with an editable
    «Себестоимость за 1 ед.» column. The seller fills it and uploads the file
    back through ``POST /cost-prices/import``. The two cross-module columns
    (orders, advertising) are resolved here through the monitoring contract, the
    same way ``GET /pnl/skus`` does.
    """
    start, end = resolve_window(date_from, date_to)
    blob = await service.export_workbook(
        workspace_id=workspace_id,
        date_from=start,
        date_to=end,
        orders=await load_orders_by_nm(
            session, workspace_id=workspace_id, date_from=start, date_to=end
        ),
        ad_spend=await load_ad_spend_by_nm(
            session, workspace_id=workspace_id, date_from=start, date_to=end
        ),
        ad_bonus=await load_ad_bonus_by_nm(
            session, workspace_id=workspace_id, date_from=start, date_to=end
        ),
        bonus_span=await ad_bonus_coverage(
            session, workspace_id=workspace_id, date_from=start, date_to=end
        ),
        bonus_currencies=await ad_bonus_currencies(
            session, workspace_id=workspace_id, date_from=start, date_to=end
        ),
        unknown_funding=await ad_bonus_unknown_types(
            session, workspace_id=workspace_id, date_from=start, date_to=end
        ),
        funnel_span=await funnel_coverage(
            session, workspace_id=workspace_id, date_from=start, date_to=end
        ),
        ad_span=await ad_coverage(session, workspace_id=workspace_id, date_from=start, date_to=end),
    )
    disposition = (
        f'attachment; filename="{_EXPORT_ASCII_NAME}"; '
        f"filename*=UTF-8''{quote(_EXPORT_UTF8_NAME)}"
    )
    return Response(
        content=blob,
        media_type=_XLSX_MEDIA_TYPE,
        headers={"Content-Disposition": disposition},
    )


@router.post(
    "/cost-prices/import",
    response_model=CostPriceImportResponse,
    status_code=status.HTTP_200_OK,
    responses={
        200: {"description": "Costs applied; the summary reports skips and issues."},
        401: {"description": "Unauthorized access token."},
        422: {"description": "The upload is not a readable cost-price workbook."},
    },
)
async def import_cost_prices(
    _writer: WritingAccess,
    service: CostPriceServiceDep,
    workspace_id: CurrentWorkspaceId,
    file: UploadFile = File(description="Cost sheet (.xlsx, .xls or .csv) with costs filled in."),
) -> CostPriceImportResponse:
    """Apply the «Себестоимость» column of an uploaded cost sheet.

    Accepts ``.xlsx``, ``.xls`` and ``.csv``. Costs are written only for SKUs
    this workspace already knows and only in its settlement currency; blanks
    change nothing and every other skip is reported. A file that is not a
    readable cost sheet is a 422, not a partial, guessed import.
    """
    data = await read_capped(
        file,
        max_bytes=_MAX_UPLOAD_BYTES,
        too_large="Файл слишком большой для загрузки себестоимости.",
    )
    if not data:
        raise ValidationError("Файл пуст.")
    return await service.import_workbook(
        workspace_id=workspace_id, filename=file.filename or "", data=data
    )
