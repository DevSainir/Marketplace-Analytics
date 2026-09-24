"""Financial-report header model — one WB weekly realization report.

One row per WB ``realizationreport_id``. Groups the settlement rows
(:class:`~src.modules.finreports.models.logistics_transaction.LogisticsTransaction`)
and anchors them to the official «Еженедельный отчёт реализации» document
archived from the Documents API (``archived_document_id`` — the court-grade original).
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import BigInteger, Date, DateTime, Numeric, String, func
from sqlalchemy.orm import Mapped, mapped_column

from src.core.database import Base

_SCHEMA: str = "finreports"


class FinancialReport(Base):
    """One weekly WB realization report header.

    Attributes:
        report_id: WB ``realizationreport_id`` (natural primary key).
        workspace_id: Owning workspace (tenancy; no cross-schema FK).
        date_from / date_to: The report's settlement period.
        currency: Settlement currency (``currency_name``, e.g. ``KGS``).
        create_dt: WB's report creation date, when supplied.
        archived_document_id: Optional link to the archived signed original.
        wb_for_pay_sum / wb_retail_amount_sum / wb_bank_payment_sum: WB's OWN
            totals for this report, as ``sales-reports/list`` served them.
            ``None`` for a report booked before they were kept — never derived
            from our own rows, since the whole value of these figures is that
            they come from somewhere else. Checked against our own sum when a
            report is booked — see
            :func:`~src.modules.finreports.tasks.settlement.reconcile.reconcile_against_wb`.
        harvested_at: When this header was ingested.
    """

    __tablename__ = "financial_report"
    __table_args__ = {"schema": _SCHEMA}

    report_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    workspace_id: Mapped[uuid.UUID] = mapped_column(nullable=False, index=True)
    date_from: Mapped[date | None] = mapped_column(Date, nullable=True)
    date_to: Mapped[date | None] = mapped_column(Date, nullable=True)
    currency: Mapped[str] = mapped_column(String(8), default="", nullable=False)
    create_dt: Mapped[date | None] = mapped_column(Date, nullable=True)
    archived_document_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    wb_for_pay_sum: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    wb_retail_amount_sum: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    wb_bank_payment_sum: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    harvested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
