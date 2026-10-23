"""Read an uploaded weekly report and decide what it adds — the worker's half.

The rule, decided with the owner on 2026-10-12: **if we lack the report, its rows
go into the P&L; if we hold it, nothing is written** and the seller is told so —
after checking the two are the same. Concretely, the file's rows are compared,
as a multiset (:mod:`...services.settlement_upload.compare`), with every row we
hold for the period's days, daily-tail rows included:

* the same rows → ``already_held``; nothing written;
* we hold nothing for those days → every row is written;
* we hold some and every one of them is in the file → the rest are written — a
  daily report that never arrived, filled from WB's own weekly document;
* anything else — we hold a row the file lacks, or WB's API has already served
  this report whole and it differs → ``diverged``: nothing written, an alert.

Written rows carry a negative ``rrd_id`` and ``rr_dt`` from the sale date
clamped into the period (see the model). While an upload stands, the daily lane
leaves its days alone, and the API's own report replaces it when it lands
(:mod:`...services.settlement_upload.reconcile`).

The workbook is read twice rather than held: once to fingerprint it, once to
write. A 70 000-row week is two streams of one row each, not 70 000 dicts
against the worker's 768 MiB.
"""

from __future__ import annotations

import uuid
from collections import Counter
from datetime import UTC, date, datetime, timedelta
from typing import Any

from src.core.database import AsyncSessionLocal
from src.core.exceptions import ValidationError
from src.core.logcontext import bind_workspace
from src.core.logging import get_logger
from src.core.observability.metrics import SETTLEMENT_UPLOAD_DIVERGENCES
from src.core.timeutils import moscow_today
from src.modules.finreports.models import SettlementUpload, UploadStatus
from src.modules.finreports.repos import (
    LogisticsTransactionRepository,
    PnlRepository,
    SettlementUploadRepository,
)
from src.modules.finreports.services.ingestion.columns import TXN_UPDATE
from src.modules.finreports.services.settlement_calendar import (
    settlement_period_end,
    settlement_period_start,
)
from src.modules.finreports.services.settlement_upload import wording
from src.modules.finreports.services.settlement_upload.compare import (
    KEY_COLUMNS,
    RowSet,
    difference,
    row_key,
)
from src.modules.finreports.services.settlement_upload.workbook import iter_report_rows

logger = get_logger(__name__)

#: Rows per insert — the same batch the settlement walk hands the database.
_BATCH = 2_000


class UploadNotReadyError(Exception):
    """The upload row is not visible yet — the request has not committed."""


async def process_settlement_upload(upload_id: uuid.UUID) -> str:
    """Process one queued upload end to end; return the status it ended in.

    Raises:
        UploadNotReadyError: The upload does not exist yet — the request that made
            it commits as it returns, which can be after this task starts. The
            task retries on it.
    """
    async with AsyncSessionLocal() as session:
        repo = SettlementUploadRepository(session)
        upload = await repo.claim(upload_id=upload_id)
        if upload is None:
            if await session.get(SettlementUpload, upload_id) is None:
                raise UploadNotReadyError(str(upload_id))
            return "skipped"
        await session.commit()
        workspace_id, report_id, xlsx = upload.workspace_id, upload.report_id, upload.payload
    bind_workspace(workspace_id)
    try:
        if report_id is None or not xlsx:
            raise ValidationError(wording.FAILED)
        return await _read_and_decide(upload_id, workspace_id, report_id, xlsx)
    except ValidationError as exc:
        await _finish(upload_id, status=UploadStatus.FAILED, message=exc.message)
        return UploadStatus.FAILED
    except Exception:
        logger.exception("finreports: could not process settlement upload %s.", upload_id)
        await _finish(upload_id, status=UploadStatus.FAILED, message=wording.FAILED)
        return UploadStatus.FAILED


async def _read_and_decide(
    upload_id: uuid.UUID, workspace_id: uuid.UUID, report_id: int, xlsx: bytes
) -> str:
    """Fingerprint the file, compare it with what we hold, and write what is missing."""
    file = RowSet()
    last_sale: date | None = None
    for row in iter_report_rows(xlsx):
        file.add(row)
        sale = row.get("sale_dt")
        if sale is not None and (last_sale is None or sale > last_sale):
            last_sale = sale
    if file.count == 0 or last_sale is None:
        raise ValidationError(wording.EMPTY)
    # No row of a weekly report is dated after its period, and a week's last
    # day always has sales: the latest sale date names the period.
    date_to = settlement_period_end(last_sale)
    date_from = settlement_period_start(date_to)
    if date_to >= moscow_today():
        raise ValidationError(wording.not_over(date_from, date_to))

    async with AsyncSessionLocal() as session:
        repo = SettlementUploadRepository(session)
        currency = await PnlRepository(session).settlement_currency(workspace_id=workspace_id)
        if not currency:
            raise ValidationError(wording.NO_CURRENCY)
        booked = await repo.report_is_booked(workspace_id=workspace_id, report_id=report_id)
        ours = RowSet()
        async for held in repo.rows_in_period(
            workspace_id=workspace_id, date_from=date_from, date_to=date_to, columns=KEY_COLUMNS
        ):
            ours.add(held)
        diff = difference(file, ours)
        upload = await session.get(SettlementUpload, upload_id)
        assert upload is not None  # claimed above, and nothing deletes uploads
        upload.date_from, upload.date_to = date_from, date_to
        upload.rows_total, upload.for_pay_sum, upload.digest = file.count, file.for_pay, file.digest

        if diff.same:
            status, message, added = UploadStatus.ALREADY_HELD, wording.ALREADY_HELD, 0
        elif booked or (ours.count and not diff.file_extends_ours):
            status, message, added = UploadStatus.DIVERGED, wording.DIVERGED, 0
            SETTLEMENT_UPLOAD_DIVERGENCES.inc()
            logger.error(
                "finreports: uploaded report %d (%s..%s) differs from what we hold: file %d "
                "rows, for-pay %s; ours %d rows, for-pay %s; %d file-only, %d ours-only.",
                report_id,
                date_from,
                date_to,
                file.count,
                file.for_pay,
                ours.count,
                ours.for_pay,
                diff.only_file.total(),
                diff.only_ours.total(),
            )
        else:
            added = await _write_missing(
                session,
                xlsx,
                wanted=Counter(diff.only_file),
                frame={"workspace_id": workspace_id, "report_id": report_id},
                currency=currency,
                period=(date_from, date_to),
            )
            status = UploadStatus.WRITTEN
            message = wording.written(date_from, date_to, total=file.count, added=added)
        upload.status, upload.message, upload.rows_written = status, message, added
        upload.payload, upload.finished_at = None, datetime.now(UTC)
        await session.commit()
    logger.info(
        "finreports: settlement upload of report %d (%s..%s) ended %s, %d of %d rows written.",
        report_id,
        date_from,
        date_to,
        status,
        added,
        file.count,
    )
    return status


async def _write_missing(
    session: Any,
    xlsx: bytes,
    *,
    wanted: Counter[bytes],
    frame: dict[str, Any],
    currency: str,
    period: tuple[date, date],
) -> int:
    """Second pass over the file: insert each row ``wanted`` still counts."""
    ids = iter(await SettlementUploadRepository(session).next_row_ids(wanted.total()))
    rows = LogisticsTransactionRepository(session)
    batch: list[dict[str, Any]] = []
    written = 0
    for row in iter_report_rows(xlsx):
        key = row_key(row)
        if wanted[key] <= 0:
            continue
        wanted[key] -= 1
        batch.append(
            row
            | frame
            | {
                "rrd_id": next(ids),
                "currency_name": currency,
                "rr_dt": _operation_day(row.get("sale_dt"), period),
            }
        )
        if len(batch) >= _BATCH:
            written += await _insert(rows, batch)
            batch = []
    if batch:
        written += await _insert(rows, batch)
    return written


async def _insert(rows: LogisticsTransactionRepository, batch: list[dict[str, Any]]) -> int:
    await rows.bulk_upsert(batch, conflict_columns=["rrd_id"], update_columns=TXN_UPDATE)
    return len(batch)


def _operation_day(sale: date | None, period: tuple[date, date]) -> date:
    """The sale date clamped into the period — the operation date on 97.6 % of rows."""
    start, end = period
    if sale is None:
        return start
    return min(max(sale, start), end)


async def _finish(upload_id: uuid.UUID, *, status: str, message: str) -> None:
    """Close an upload the worker could not take further."""
    async with AsyncSessionLocal() as session:
        upload = await session.get(SettlementUpload, upload_id)
        if upload is not None:
            upload.status, upload.message = status, message
            upload.payload, upload.finished_at = None, datetime.now(UTC)
            await session.commit()


async def standing_upload_days(session: Any, *, workspace_id: uuid.UUID) -> set[date]:
    """Every day a standing upload covers — the days the daily lane must leave alone."""
    days: set[date] = set()
    for upload in await SettlementUploadRepository(session).standing(workspace_id=workspace_id):
        if upload.date_from is None or upload.date_to is None:
            continue
        day = upload.date_from
        while day <= upload.date_to:
            days.add(day)
            day += timedelta(days=1)
    return days


__all__ = ["UploadNotReadyError", "process_settlement_upload", "standing_upload_days"]
