"""When WB's API serves a report a seller uploaded: compare, then hand over.

Run where the report's header is booked — the one moment every row of it the
API serves is in the table. The uploaded rows are compared with the API's as
multisets (:mod:`.compare`), against the fingerprint the WHOLE file had at
upload, so a file that only filled a gap is still checked row for row.

Either way the uploaded rows then go: the API's carry WB's row id and the true
operation date, which the file has neither of, and keeping both would count the
week twice. What a difference changes is what is SAID. Both are WB's documents,
so a disagreement is never resolved quietly: it is counted for the alert, logged
with both sides' totals under the seller's ``workspace_id``, and recorded on the
upload, which keeps the file's own fingerprint and totals for whoever checks.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from src.core.logging import get_logger
from src.core.observability.metrics import SETTLEMENT_UPLOAD_DIVERGENCES
from src.modules.finreports.models import UploadStatus
from src.modules.finreports.repos import SettlementUploadRepository
from src.modules.finreports.services.settlement_upload.compare import KEY_COLUMNS, RowSet

logger = get_logger(__name__)


async def settle_upload_on_booking(
    uploads: SettlementUploadRepository, *, workspace_id: uuid.UUID, report_id: int
) -> None:
    """Retire the upload standing in for ``report_id``, if any, saying whether it matched.

    Nothing is committed here; the caller owns the transaction — the same one
    that booked the header, so the hand-over is all or nothing.

    Args:
        uploads: Repository on the booking's session.
        workspace_id: Tenancy scope.
        report_id: The report whose header was just booked.
    """
    upload = await uploads.standing_for_report(workspace_id=workspace_id, report_id=report_id)
    if upload is None:
        return
    api = RowSet()
    async for row in uploads.report_rows(
        workspace_id=workspace_id, report_id=report_id, columns=KEY_COLUMNS
    ):
        api.add(row)
    same = api.digest == upload.digest
    dropped = await uploads.drop_uploaded_rows(workspace_id=workspace_id, report_id=report_id)
    upload.status = UploadStatus.CONFIRMED if same else UploadStatus.REPLACED_DIVERGED
    upload.resolved_at = datetime.now(UTC)
    if same:
        logger.info(
            "finreports: WB's API served uploaded report %d — %d rows, identical to the "
            "file; %d uploaded rows replaced.",
            report_id,
            api.count,
            dropped,
        )
        return
    SETTLEMENT_UPLOAD_DIVERGENCES.inc()
    logger.error(
        "finreports: WB's API served uploaded report %d and it differs from the file: "
        "file %d rows, for-pay %s; API %d rows, for-pay %s. The API's rows now stand; "
        "check the file against WB's seller portal.",
        report_id,
        upload.rows_total,
        upload.for_pay_sum,
        api.count,
        api.for_pay,
    )


__all__ = ["settle_upload_on_booking"]
