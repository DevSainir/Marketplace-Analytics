"""The request side of a hand upload: take the file, queue it, report on it.

Reading a weekly report is the worker's job — a 70 000-row week is a minute and
a half of openpyxl, far past what a request may hold — so this does only what
must be answered at once: is this WB's file at all, which report is it, and is
another upload of this workspace still being read. Everything else waits for
:mod:`src.modules.finreports.tasks.settlement_upload`.
"""

from __future__ import annotations

import uuid

from src.core.exceptions import ConflictError, NotFoundError
from src.modules.finreports.models import SettlementUpload, UploadStatus
from src.modules.finreports.repos import SettlementUploadRepository
from src.modules.finreports.services.settlement_upload.workbook import open_upload

_BUSY = "Предыдущий файл ещё обрабатывается — подождите минуту."
_UNKNOWN = "Загрузка не найдена."


class SettlementUploadService:
    """Accepts uploaded weekly reports and reports how each one ended."""

    def __init__(self, *, upload_repo: SettlementUploadRepository) -> None:
        """Wire the service to its repository."""
        self._uploads = upload_repo

    async def accept(
        self, *, workspace_id: uuid.UUID, user_id: uuid.UUID, filename: str, data: bytes
    ) -> SettlementUpload:
        """Check the file is a WB weekly report and queue it for the worker.

        One upload at a time per workspace: each costs the worker up to a minute
        and a half, and two of the same week would race to write it.

        Raises:
            ValidationError: Not WB's file, or no report number in its name.
            ConflictError: Another upload of this workspace is still being read.
        """
        opened = open_upload(filename, data)
        if await self._uploads.in_flight(workspace_id=workspace_id):
            raise ConflictError(_BUSY)
        return await self._uploads.create(
            SettlementUpload(
                workspace_id=workspace_id,
                uploaded_by=user_id,
                filename=filename[:255],
                report_id=opened.report_id,
                status=UploadStatus.QUEUED,
                message="",
                rows_total=0,
                rows_written=0,
                payload=opened.xlsx,
            )
        )

    async def get(self, *, workspace_id: uuid.UUID, upload_id: uuid.UUID) -> SettlementUpload:
        """One upload of this workspace.

        Raises:
            NotFoundError: No such upload here — including one of another
                workspace, which is indistinguishable from none.
        """
        upload = await self._uploads.get(workspace_id=workspace_id, upload_id=upload_id)
        if upload is None:
            raise NotFoundError(_UNKNOWN)
        return upload


__all__ = ["SettlementUploadService"]
