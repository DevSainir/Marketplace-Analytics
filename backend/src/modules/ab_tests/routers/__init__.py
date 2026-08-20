"""HTTP surface of the A/B-tests module.

One list, one detail, and the photo endpoints. Every route is scoped by the
workspace header, and a test belonging to another workspace reads as a 404
rather than a 403 — a test names a card the caller should not know exists.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, File, Query, UploadFile, status
from fastapi.responses import Response

from src.modules.ab_tests.deps import AbTestCatalogServiceDep, InstallerDep
from src.modules.ab_tests.schemas import (
    AbTestCreate,
    AbTestDetail,
    AbTestRead,
    AbTestStatusUpdate,
)
from src.modules.workspaces.contract import CurrentWorkspaceId

router = APIRouter(prefix="/ab-tests", tags=["ab-tests"])


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
    responses={401: {"description": "Не аутентифицирован"}},
)
async def create_test(
    payload: AbTestCreate,
    service: AbTestCatalogServiceDep,
    workspace_id: CurrentWorkspaceId,
) -> AbTestRead:
    """Create a draft test; photos are uploaded separately."""
    return await service.create_test(workspace_id=workspace_id, payload=payload)


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
    "/{test_id}/status",
    response_model=AbTestRead,
    summary="Запустить, поставить на паузу или отменить",
    responses={
        404: {"description": "Тест не найден"},
        409: {"description": "Переход невозможен в текущем статусе"},
        422: {"description": "Неизвестный статус"},
    },
)
async def set_status(
    test_id: uuid.UUID,
    payload: AbTestStatusUpdate,
    service: AbTestCatalogServiceDep,
    installer: InstallerDep,
    workspace_id: CurrentWorkspaceId,
) -> AbTestRead:
    """Change a test's status; starting installs the first photo on the card.

    This is the only route that needs a WB token, so it is the only one that
    depends on the installer — reading a test must stay possible for a
    workspace that has not stored its credentials yet.
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
    responses={404: {"description": "Тест не найден"}},
)
async def delete_test(
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
        404: {"description": "Тест не найден"},
        409: {"description": "Достигнут предел в 10 фото"},
        422: {"description": "Файл не является поддерживаемым изображением"},
    },
)
async def upload_variant(
    test_id: uuid.UUID,
    service: AbTestCatalogServiceDep,
    workspace_id: CurrentWorkspaceId,
    file: UploadFile = File(description="Изображение до 32 МБ"),
) -> AbTestDetail:
    """Append a photo to the rotation and return the refreshed test.

    The whole test comes back rather than just the new variant: the result
    table has to re-render anyway, and one round trip keeps the upload list and
    the table from disagreeing.
    """
    await service.add_variant(
        workspace_id=workspace_id,
        test_id=test_id,
        content=await file.read(),
        content_type=file.content_type or "application/octet-stream",
        filename=file.filename or "",
    )
    return await service.get_detail(workspace_id=workspace_id, test_id=test_id)


@router.delete(
    "/{test_id}/variants/{variant_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Удалить фото из теста",
    responses={
        404: {"description": "Тест или вариант не найден"},
        409: {"description": "Фото сейчас стоит на карточке"},
    },
)
async def delete_variant(
    test_id: uuid.UUID,
    variant_id: uuid.UUID,
    service: AbTestCatalogServiceDep,
    workspace_id: CurrentWorkspaceId,
) -> None:
    """Remove a photo from the rotation."""
    await service.delete_variant(workspace_id=workspace_id, test_id=test_id, variant_id=variant_id)


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
    service: AbTestCatalogServiceDep,
    workspace_id: CurrentWorkspaceId,
) -> Response:
    """Stream a variant's stored original.

    Served from our own store rather than WB's CDN because a variant that has
    not been installed yet has no WB URL at all, and one that has been replaced
    no longer has one.
    """
    content, content_type = await service.read_variant_image(
        workspace_id=workspace_id, test_id=test_id, variant_id=variant_id
    )
    # Immutable: the path contains the content digest, so a cached copy can
    # never be stale for the same variant id.
    return Response(
        content=content,
        media_type=content_type,
        headers={"Cache-Control": "private, max-age=86400, immutable"},
    )


__all__ = ["router"]
