"""HTTP surface of the A/B-tests module.

One list, one detail, and the photo endpoints. Every route is scoped by the
workspace header, and a test belonging to another workspace reads as a 404
rather than a 403 — a test names a card the caller should not know exists.

The module is a product surface like monitoring and finreports
(``require_ab_tests``): any organisation with a live subscription reaches it,
and a manager only with the "A/B tests" grant. It was internal-only until
2026-09-24, while the rotation was being built against our own catalogue.

The state-changing routes carry ``WritingAccess`` on top of that.
Reachability and writing are separate questions: a manager granted "A/B tests"
at ``read_only`` may read the results table and may not install a photo on a
live card. Reads stay open, as everywhere else —
the results of a rotation someone else started are still theirs to look at.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Literal

from fastapi import APIRouter, Depends, File, Query, UploadFile, status
from fastapi.responses import Response

from src.core.uploads import read_capped
from src.modules.ab_tests.deps import (
    AbTestCatalogServiceDep,
    FinisherDep,
    InstallerDep,
    SkuCatalogueDep,
    VariantServiceDep,
)
from src.modules.ab_tests.schemas import (
    AbTestCreate,
    AbTestDetail,
    AbTestFinish,
    AbTestRead,
    AbTestSettingsUpdate,
    AbTestStatusUpdate,
    SkuOption,
    VariantExclusionUpdate,
)
from src.modules.ab_tests.services.photos import MAX_IMAGE_BYTES
from src.modules.organizations.contract import WritingAccess, require_ab_tests
from src.modules.workspaces.contract import CurrentWorkspaceId

router = APIRouter(
    prefix="/ab-tests",
    tags=["ab-tests"],
    # Membership + subscription + the "A/B tests" grant, like every other
    # product surface. Writing to the live card is WritingAccess, per route.
    dependencies=[Depends(require_ab_tests)],
)


@router.get(
    "",
    response_model=list[AbTestRead],
    summary="List A/B tests",
    responses={401: {"description": "Not authenticated"}},
)
async def list_tests(
    service: AbTestCatalogServiceDep,
    workspace_id: CurrentWorkspaceId,
    q: str | None = Query(default=None, description="Search by name, WB ID and vendor code"),
) -> list[AbTestRead]:
    """Return the workspace's tests, newest first."""
    return await service.list_tests(workspace_id=workspace_id, query=q)


@router.post(
    "",
    response_model=AbTestRead,
    status_code=status.HTTP_201_CREATED,
    summary="Create a test",
    responses={
        401: {"description": "Not authenticated"},
        403: {"description": "Read-only access"},
    },
)
async def create_test(
    _writer: WritingAccess,
    payload: AbTestCreate,
    service: AbTestCatalogServiceDep,
    catalogue: SkuCatalogueDep,
    workspace_id: CurrentWorkspaceId,
) -> AbTestRead:
    """Create an empty draft test.

    The SKU is resolved against the workspace's catalogue before anything is
    written, and the vendor code is read off that card rather than taken from
    the body — the two could otherwise disagree.

    No photo comes with it. The card's live main image used to be downloaded
    from WB's CDN as the baseline; that is gone, because WB serves renditions
    rather than the seller's own file and re-installing one put the transcoding
    loss back on the live card. The baseline is now an upload marked "Main photo".
    """
    return await service.create_test(
        workspace_id=workspace_id,
        payload=payload,
        card=await catalogue.resolve(workspace_id=workspace_id, nm_id=payload.nm_id),
    )


@router.get(
    "/skus",
    response_model=list[SkuOption],
    summary="Catalog for picking a SKU",
    responses={401: {"description": "Not authenticated"}},
)
async def search_skus(
    catalogue: SkuCatalogueDep,
    workspace_id: CurrentWorkspaceId,
    q: str = Query(default="", description="Part of the WB ID, vendor code or title"),
) -> list[SkuOption]:
    """Return the cards a test may be created against.

    Declared before ``/{test_id}`` so the static path is not swallowed by the
    UUID path parameter — the same ordering trap monitoring's own lookup route
    documents.

    A blank query returns the first page rather than nothing, so the picker
    opens with something in it instead of looking broken — and the order it
    opens in is advertised cards first, then last week's orders descending, so
    the top of an unfiltered list is the cards worth testing rather than
    whichever SKU happens to sort first alphabetically.
    """
    cards = await catalogue.search(workspace_id=workspace_id, needle=q)
    return [
        SkuOption(
            nm_id=card.nm_id,
            vendor_code=card.vendor_code,
            title=card.title,
            orders_7d=card.orders_7d,
            has_ads=card.has_ads,
        )
        for card in cards
    ]


@router.get(
    "/{test_id}",
    response_model=AbTestDetail,
    summary="A test with its result table",
    responses={404: {"description": "Test not found"}},
)
async def get_test(
    test_id: uuid.UUID,
    service: AbTestCatalogServiceDep,
    workspace_id: CurrentWorkspaceId,
) -> AbTestDetail:
    """Return one test and its per-photo metrics."""
    return await service.get_detail(workspace_id=workspace_id, test_id=test_id)


@router.patch(
    "/{test_id}",
    response_model=AbTestRead,
    summary="Change the name or the rotation trigger",
    responses={
        403: {"description": "Read-only access"},
        404: {"description": "Test not found"},
        409: {"description": "The test is already finished"},
        422: {"description": "A setting from the other mode"},
    },
)
async def update_settings(
    _writer: WritingAccess,
    test_id: uuid.UUID,
    payload: AbTestSettingsUpdate,
    service: AbTestCatalogServiceDep,
    workspace_id: CurrentWorkspaceId,
) -> AbTestRead:
    """Change a running test's trigger without restarting it.

    Needs no WB token: nothing here touches the card. The next polling pass
    reads the new setting, so lowering a budget below what the live photo has
    already gathered rotates within minutes rather than at some later reset.
    """
    return await service.update_settings(
        workspace_id=workspace_id, test_id=test_id, payload=payload
    )


@router.patch(
    "/{test_id}/status",
    response_model=AbTestRead,
    summary="Start, pause or cancel",
    responses={
        403: {"description": "Read-only access"},
        404: {"description": "Test not found"},
        409: {"description": "Not possible from the current status"},
        422: {"description": "Unknown status"},
    },
)
async def set_status(
    _writer: WritingAccess,
    test_id: uuid.UUID,
    payload: AbTestStatusUpdate,
    service: AbTestCatalogServiceDep,
    installer: InstallerDep,
    workspace_id: CurrentWorkspaceId,
) -> AbTestRead:
    """Change a test's status; starting installs the first photo on the card.

    This is the only route that needs a WB token, so it is the only one that
    depends on the installer — reading a test must stay possible for a workspace
    that has not stored its credentials yet.
    """
    return await service.set_status(
        workspace_id=workspace_id,
        test_id=test_id,
        status=payload.status,
        installer=installer,
    )


@router.post(
    "/{test_id}/finish",
    response_model=AbTestDetail,
    summary="Finish the test, leaving the chosen photo on the card",
    responses={
        403: {"description": "Read-only access"},
        404: {"description": "Test or photo not found"},
        409: {"description": "The test is neither running nor paused"},
    },
)
async def finish_test(
    _writer: WritingAccess,
    test_id: uuid.UUID,
    payload: AbTestFinish,
    finisher: FinisherDep,
    service: AbTestCatalogServiceDep,
    installer: InstallerDep,
    workspace_id: CurrentWorkspaceId,
) -> AbTestDetail:
    """End a test and leave the chosen photo on the live card.

    ``WritingAccess`` and not a weaker guard because this installs a picture on
    the seller's storefront — the same reach as starting a test. Not owner-only
    either: whoever may start and pause a rotation may end it.

    A separate route from ``PATCH /status`` because a finish carries a choice
    and a WB upload, where the status route carries neither for a cancel; the
    bare cancel there stays for API callers that want the card left as it is.

    The whole test comes back so the page re-renders "On the card" and the
    status from one answer.
    """
    await finisher.finish(
        workspace_id=workspace_id,
        test_id=test_id,
        keep_variant_id=payload.keep_variant_id,
        installer=installer,
        now=datetime.now(UTC),
    )
    return await service.get_detail(workspace_id=workspace_id, test_id=test_id)


@router.delete(
    "/{test_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a test",
    responses={
        403: {"description": "Read-only access"},
        404: {"description": "Test not found"},
    },
)
async def delete_test(
    _writer: WritingAccess,
    test_id: uuid.UUID,
    service: AbTestCatalogServiceDep,
    workspace_id: CurrentWorkspaceId,
) -> None:
    """Delete a test and its photos."""
    await service.delete_test(workspace_id=workspace_id, test_id=test_id)


@router.post(
    "/{test_id}/variants",
    response_model=AbTestDetail,
    status_code=status.HTTP_201_CREATED,
    summary="Upload a photo to a test",
    responses={
        403: {"description": "Read-only access"},
        404: {"description": "Test not found"},
        409: {"description": "The 10-photo limit is reached, or a main photo is already uploaded"},
        422: {"description": "The file is not a supported image"},
    },
)
async def upload_variant(
    _writer: WritingAccess,
    test_id: uuid.UUID,
    service: AbTestCatalogServiceDep,
    photos: VariantServiceDep,
    workspace_id: CurrentWorkspaceId,
    file: UploadFile = File(description="An image up to 32 MB"),
    main: bool = Query(default=False, description="Upload as the card's main photo"),
) -> AbTestDetail:
    """Append a photo to the rotation and return the refreshed test.

    ``main=true`` files it as "Main photo": position 0, first out of the gate, and
    the row every other photo's result is read against. One per test — the
    seller replaces it by deleting it and uploading another, which is the same
    two steps as changing any other photo.

    The whole test comes back rather than just the new variant: the result
    table has to re-render anyway, and one round trip keeps the upload list and
    the table from disagreeing.
    """
    await photos.add_variant(
        workspace_id=workspace_id,
        test_id=test_id,
        content=await read_capped(
            file,
            max_bytes=MAX_IMAGE_BYTES,
            too_large="Image over 32 MB — WB won't accept it.",
        ),
        content_type=file.content_type or "application/octet-stream",
        filename=file.filename or "",
        as_main=main,
    )
    return await service.get_detail(workspace_id=workspace_id, test_id=test_id)


@router.delete(
    "/{test_id}/variants/{variant_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a photo from a test",
    responses={
        403: {"description": "Read-only access"},
        404: {"description": "Test or variant not found"},
        409: {"description": "The photo is on the card right now"},
    },
)
async def delete_variant(
    _writer: WritingAccess,
    test_id: uuid.UUID,
    variant_id: uuid.UUID,
    photos: VariantServiceDep,
    workspace_id: CurrentWorkspaceId,
) -> None:
    """Remove a photo from the rotation."""
    await photos.delete_variant(workspace_id=workspace_id, test_id=test_id, variant_id=variant_id)


@router.patch(
    "/{test_id}/variants/{variant_id}",
    response_model=AbTestDetail,
    summary="Remove a photo from the rotation, or bring it back",
    responses={
        403: {"description": "Read-only access"},
        404: {"description": "Test or variant not found"},
        409: {"description": "The last photo in the rotation"},
    },
)
async def set_variant_excluded(
    _writer: WritingAccess,
    test_id: uuid.UUID,
    variant_id: uuid.UUID,
    payload: VariantExclusionUpdate,
    service: AbTestCatalogServiceDep,
    photos: VariantServiceDep,
    workspace_id: CurrentWorkspaceId,
) -> AbTestDetail:
    """Take a photo out of the running rotation, or put it back.

    Deliberately allowed while the test is running — that is the point. Nothing
    is deleted: the photo keeps its row, its image and every window already
    credited to it, so the result table goes on showing what it did. It simply
    stops being dealt, from the next pass on.

    Returns the whole test for the same reason the upload route does: the table
    re-renders anyway, and one round trip keeps the photo list and the figures
    from disagreeing.
    """
    await photos.set_variant_excluded(
        workspace_id=workspace_id,
        test_id=test_id,
        variant_id=variant_id,
        excluded=payload.excluded,
    )
    return await service.get_detail(workspace_id=workspace_id, test_id=test_id)


@router.get(
    "/{test_id}/variants/{variant_id}/image",
    summary="A variant's image",
    response_class=Response,
    responses={
        200: {"content": {"image/*": {}}, "description": "The image file"},
        404: {"description": "Test, variant or file not found"},
    },
)
async def get_variant_image(
    test_id: uuid.UUID,
    variant_id: uuid.UUID,
    photos: VariantServiceDep,
    workspace_id: CurrentWorkspaceId,
    size: Literal["full", "thumb"] = Query(
        default="full", description="thumb — a small copy for lists and the timeline"
    ),
) -> Response:
    """Stream a variant's stored image, full size or as a thumbnail.

    Served from our own store rather than WB's CDN because a variant that has
    not been installed yet has no WB URL at all, and one that has been replaced
    no longer has one.

    ``size=thumb`` is what every screen in the SPA asks for, and it is not a
    nicety: the originals are phone photos of eight or nine megabytes, and the
    largest any of them is drawn at is 88 CSS pixels. The full size stays the
    default because the full size is what WB is sent.
    """
    content, content_type = await photos.read_variant_image(
        workspace_id=workspace_id,
        test_id=test_id,
        variant_id=variant_id,
        thumbnail=size == "thumb",
    )
    # Immutable: the path contains the content digest, so a cached copy can
    # never be stale for the same variant id — and a variant's image is never
    # replaced in place, only deleted with the variant.
    return Response(
        content=content,
        media_type=content_type,
        headers={"Cache-Control": "private, max-age=604800, immutable"},
    )


__all__ = ["router"]
