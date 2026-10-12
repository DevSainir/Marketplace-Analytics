"""HTTP routes for uploading WB's weekly report by hand, and following it.

The seller downloads «Еженедельный детализированный отчет» from WB's кабинет —
hours before WB's API serves it — and uploads it here. The POST answers at
once: it checks the file is WB's and queues it; the worker reads it, and the
GET says how it ended. See :mod:`src.modules.finreports.services.settlement_upload`.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, File, UploadFile, status

from src.core.exceptions import ValidationError
from src.core.uploads import read_capped
from src.modules.finreports.deps import SettlementUploadServiceDep
from src.modules.finreports.models import SettlementUpload
from src.modules.finreports.schemas import SettlementUploadOut
from src.modules.finreports.tasks import process_settlement_upload
from src.modules.organizations.contract import WritingAccess
from src.modules.users.contract import CurrentUserId
from src.modules.workspaces.contract import CurrentWorkspaceId

#: WB's zip is stored, not compressed: ~0.5 KB a row, so NEVA's largest week
#: (71 539 rows) is ~36 MB. nginx's ceiling for this path is 49m to match.
_MAX_UPLOAD_BYTES = 48 * 1024 * 1024

router = APIRouter()


def _out(upload: SettlementUpload) -> SettlementUploadOut:
    return SettlementUploadOut.model_validate(upload, from_attributes=True)


@router.post(
    "/settlement-uploads",
    response_model=SettlementUploadOut,
    status_code=status.HTTP_202_ACCEPTED,
    responses={
        202: {"description": "The file is WB's weekly report; it is queued for reading."},
        401: {"description": "Unauthorized access token."},
        409: {"description": "Another upload of this кабинет is still being read."},
        422: {"description": "Not WB's weekly report file, or too large."},
    },
)
async def upload_settlement_report(
    _writer: WritingAccess,
    service: SettlementUploadServiceDep,
    workspace_id: CurrentWorkspaceId,
    user_id: CurrentUserId,
    file: UploadFile = File(description="WB's weekly detailed report: the .zip, or its .xlsx."),
) -> SettlementUploadOut:
    """Queue a hand-uploaded weekly report.

    Guard: the module's router-level P&L grant, plus ``WritingAccess`` — the
    upload writes settlement rows into the кабинет's statement, which a
    read-only member may not do. Scoped by ``CurrentWorkspaceId``, which
    validates the header against the caller's organisation and binds the tenant
    for row-level security; the worker writes for that workspace and no other.

    Bounded three ways: the body is read capped, the archive's declared size is
    checked before anything is parsed, and a кабинет has one upload in flight at
    a time.
    """
    data = await read_capped(
        file,
        max_bytes=_MAX_UPLOAD_BYTES,
        too_large="Файл слишком большой для одного недельного отчёта.",
    )
    if not data:
        raise ValidationError("Файл пуст.")
    upload = await service.accept(
        workspace_id=workspace_id, user_id=user_id, filename=file.filename or "", data=data
    )
    process_settlement_upload.delay(upload_id=str(upload.id))
    return _out(upload)


@router.get(
    "/settlement-uploads/{upload_id}",
    response_model=SettlementUploadOut,
    status_code=status.HTTP_200_OK,
    responses={
        200: {"description": "Where the upload stands."},
        401: {"description": "Unauthorized access token."},
        404: {"description": "No such upload in this кабинет."},
    },
)
async def get_settlement_upload(
    upload_id: uuid.UUID,
    service: SettlementUploadServiceDep,
    workspace_id: CurrentWorkspaceId,
) -> SettlementUploadOut:
    """Report how an upload ended, for the page polling it.

    Guard: the module's router-level P&L grant. Scoped by ``CurrentWorkspaceId``
    and read by ``(workspace_id, id)`` — another кабинет's upload is a 404, the
    same as one that does not exist.
    """
    return _out(await service.get(workspace_id=workspace_id, upload_id=upload_id))
