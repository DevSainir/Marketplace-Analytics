"""A weekly report the seller uploaded by hand, and what became of it.

WB shows the weekly report in the seller's кабинет hours — once eight days —
before its API serves it. The seller can download it there («Еженедельный
детализированный отчет №…», a zip with one .xlsx) and upload it here; the rows
then stand in the P&L until the API serves the same report.

The file is WB's own document and carries every money column the API row does
(matched column for column on 992915233, 3 257 rows), but not two things the
service keys on: the row's ``rrdId`` and its operation date ``rr_dt``. So the
rows are written with negative ids from ``finreports.upload_row_seq`` — never a
real WB id — and with ``rr_dt`` taken from «Дата продажи» clamped into the
period, which is the operation date on 97.6 % of rows and a day or two early on
some logistics rows. When the API serves the report the uploaded rows are
compared with it and removed, the API's taking their place with the real id and
date; a difference is an alert, never a silent overwrite.

``payload`` holds the uploaded workbook only until the worker has read it.
"""

from __future__ import annotations

import enum
import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    Date,
    DateTime,
    Integer,
    LargeBinary,
    Numeric,
    Sequence,
    String,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from src.core.database import Base
from src.core.ids import uuid7

_SCHEMA: str = "finreports"

#: Where an uploaded row's ``rrd_id`` comes from, negated. A real WB ``rrdId`` is
#: positive, so the sign alone says a row came from a file — and a sequence, not
#: the report number, because ``rrd_id`` is unique across every кабинет.
UPLOAD_ROW_SEQUENCE = Sequence("upload_row_seq", schema=_SCHEMA, metadata=Base.metadata)


class UploadStatus(enum.StrEnum):
    """Where an upload stands.

    ``queued`` / ``processing`` while the worker has it; then one of:
    ``written`` — its rows stand in the P&L; ``already_held`` — we hold every
    row of it already, nothing written; ``diverged`` — we hold this period and
    it differs from the file, nothing written, alerted; ``failed`` — the file
    was refused, ``message`` says why. A ``written`` upload ends as
    ``confirmed`` or ``replaced_diverged`` once the API serves the report.
    """

    QUEUED = "queued"
    PROCESSING = "processing"
    WRITTEN = "written"
    ALREADY_HELD = "already_held"
    DIVERGED = "diverged"
    FAILED = "failed"
    CONFIRMED = "confirmed"
    REPLACED_DIVERGED = "replaced_diverged"


class SettlementUpload(Base):
    """One uploaded weekly report file.

    Attributes:
        id: UUIDv7.
        workspace_id: Owning workspace (tenancy; no cross-schema FK).
        uploaded_by: The user who uploaded it.
        filename: As uploaded — the report number is read from it.
        report_id: WB's report number, from the file name.
        date_from / date_to: The settlement period, derived from the rows.
        status: See :class:`UploadStatus`.
        message: What the seller is told, in Russian.
        rows_total: Data rows in the file.
        rows_written: Rows this upload put into ``logistics_transaction``.
        for_pay_sum: Σ «К перечислению Продавцу», signed by document type.
        digest: Fingerprint of the file's rows, order-free — see
            :mod:`~src.modules.finreports.services.settlement_upload.compare`.
        payload: The workbook bytes, cleared once read.
        uploaded_at / finished_at / resolved_at: When it arrived, when the
            worker finished, when the API's report settled it.
    """

    __tablename__ = "settlement_upload"
    __table_args__ = {"schema": _SCHEMA}

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid7)
    workspace_id: Mapped[uuid.UUID] = mapped_column(nullable=False, index=True)
    uploaded_by: Mapped[uuid.UUID] = mapped_column(nullable=False)
    filename: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    report_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    date_from: Mapped[date | None] = mapped_column(Date, nullable=True)
    date_to: Mapped[date | None] = mapped_column(Date, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default=UploadStatus.QUEUED, nullable=False)
    message: Mapped[str] = mapped_column(Text, default="", nullable=False)
    rows_total: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    rows_written: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    for_pay_sum: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    digest: Mapped[str] = mapped_column(String(32), default="", nullable=False)
    payload: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    uploaded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
