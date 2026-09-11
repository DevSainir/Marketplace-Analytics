"""HTTP surface of the A/B-tests module.

One list, one detail, and the photo endpoints. Every route is scoped by the
workspace header, and a test belonging to another workspace reads as a 404
rather than a 403 — a test names a card the caller should not know exists.

The whole module is **internal-only** (``require_internal``): it installs photos
on a live WB card through the Content API and was built against our own
catalogue. It is not part of what a customer's subscription buys.

The five state-changing routes carry ``WritingAccess`` on top of that.
Reachability and writing are separate questions: a manager of the primary
organisation granted A/Б-тесты at ``read_only`` may read the results table and
may not install a photo on a live card. Reads stay open, as everywhere else —
the results of a rotation someone else started are still theirs to look at.
"""

from __future__ import annotations

import uuid
from typing import Literal

from fastapi import APIRouter, Depends, File, Query, UploadFile, status
from fastapi.responses import Response

from src.core.uploads import read_capped
from src.modules.ab_tests.deps import (
    AbTestCatalogServiceDep,
    InstallerDep,
    SkuCatalogueDep,
    VariantServiceDep,
)
from src.modules.ab_tests.schemas import (
    AbTestCreate,
    AbTestDetail,
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
    # Internal-only. The rotation writes to a seller's live WB card through the
    # Content API, and it was built against our own catalogue; it is not a
    # feature customers have bought. Devs and the primary organisation only.
    dependencies=[Depends(require_ab_tests)],
)


@router.get(
    "",
    response_model=list[AbTestRead],
    summary="Список A/Б-тестов",
    responses={401: {"description": "Не аутентифицирован"}},
)
async def list_tests(
    service: AbTestCatalogServiceDep,
    workspace_id: CurrentWorkspaceId,
    q: str | None = Query(default=None, description="Поиск по названию и артикулам"),
) -> list[AbTestRead]:
    """Return the workspace's tests, newest first."""
    return await service.list_tests(workspace_id=workspace_id, query=q)


@router.post(
    "",
    response_model=AbTestRead,
    status_code=status.HTTP_201_CREATED,
    summary="Создать тест",
    responses={
        401: {"description": "Не аутентифицирован"},
        403: {"description": "Доступ только для чтения"},
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

    The article is resolved against the workspace's catalogue before anything is
    written, and the seller article is read off that card rather than taken from
    the body — the two could otherwise disagree.

    No photo comes with it. The card's live main image used to be downloaded
    from WB's CDN as the baseline; that is gone, because WB serves renditions
    rather than the seller's own file and re-installing one put the transcoding
    loss back on the live card. The baseline is now an upload marked «Главное».
    """
    return await service.create_test(
        workspace_id=workspace_id,
        payload=payload,
        card=await catalogue.resolve(workspace_id=workspace_id, nm_id=payload.nm_id),
    )


@router.get(
    "/skus",
    response_model=list[SkuOption],
    summary="Каталог для выбора артикула",
    responses={401: {"description": "Не аутентифицирован"}},
)
async def search_skus(
    catalogue: SkuCatalogueDep,
    workspace_id: CurrentWorkspaceId,
    q: str = Query(default="", description="Часть артикула WB, артикула продавца или названия"),
) -> list[SkuOption]:
    """Return the cards a test may be created against.

    Declared before ``/{test_id}`` so the static path is not swallowed by the
    UUID path parameter — the same ordering trap monitoring's own lookup route
    documents.

    A blank query returns the first page rather than nothing, so the picker
    opens with something in it instead of looking broken — and the order it
    opens in is advertised cards first, then last week's orders descending, so
    the top of an unfiltered list is the cards worth testing rather than
    whichever article happens to sort first alphabetically.
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
    summary="Тест с таблицей результатов",
    responses={404: {"description": "Тест не найден"}},
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
    summary="Изменить название или триггер ротации",
    responses={
        403: {"description": "Доступ только для чтения"},
        404: {"description": "Тест не найден"},
        409: {"description": "Тест уже завершён"},
        422: {"description": "Настройка не от того режима"},
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
    summary="Запустить, поставить на паузу или отменить",
    responses={
        403: {"description": "Доступ только для чтения"},
        404: {"description": "Тест не найден"},
        409: {"description": "Переход невозможен в текущем статусе"},
        422: {"description": "Неизвестный статус"},
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


@router.delete(
    "/{test_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Удалить тест",
    responses={
        403: {"description": "Доступ только для чтения"},
        404: {"description": "Тест не найден"},
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
    summary="Загрузить фото в тест",
    responses={
        403: {"description": "Доступ только для чтения"},
        404: {"description": "Тест не найден"},
        409: {"description": "Достигнут предел в 10 фото, или главное фото уже загружено"},
        422: {"description": "Файл не является поддерживаемым изображением"},
    },
)
async def upload_variant(
    _writer: WritingAccess,
    test_id: uuid.UUID,
    service: AbTestCatalogServiceDep,
    photos: VariantServiceDep,
    workspace_id: CurrentWorkspaceId,
    file: UploadFile = File(description="Изображение до 32 МБ"),
    main: bool = Query(default=False, description="Загрузить как главное фото карточки"),
) -> AbTestDetail:
    """Append a photo to the rotation and return the refreshed test.

    ``main=true`` files it as «Главное»: position 0, first out of the gate, and
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
            too_large="Изображение больше 32 МБ — WB такой файл не примет.",
        ),
        content_type=file.content_type or "application/octet-stream",
        filename=file.filename or "",
        as_main=main,
    )
    return await service.get_detail(workspace_id=workspace_id, test_id=test_id)


@router.delete(
    "/{test_id}/variants/{variant_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Удалить фото из теста",
    responses={
        403: {"description": "Доступ только для чтения"},
        404: {"description": "Тест или вариант не найден"},
        409: {"description": "Фото сейчас стоит на карточке"},
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
    summary="Убрать фото из ротации или вернуть",
    responses={
        403: {"description": "Доступ только для чтения"},
        404: {"description": "Тест или вариант не найден"},
        409: {"description": "Это последнее фото в ротации"},
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
    summary="Изображение варианта",
    response_class=Response,
    responses={
        200: {"content": {"image/*": {}}, "description": "Файл изображения"},
        404: {"description": "Тест, вариант или файл не найден"},
    },
)
async def get_variant_image(
    test_id: uuid.UUID,
    variant_id: uuid.UUID,
    photos: VariantServiceDep,
    workspace_id: CurrentWorkspaceId,
    size: Literal["full", "thumb"] = Query(
        default="full", description="thumb — уменьшенная копия для списков и таймлайна"
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
