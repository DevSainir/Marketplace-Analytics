"""When WB's API first named each report — the publication log.

WB shows a report on its own site hours before ``sales-reports/list`` names it
(12.10.2026: on the site by 08:00, absent from the list at 08:05), and nothing
we kept said WHEN the API caught up: ``financial_report.harvested_at`` is when
the rows were booked, which is later still and moves with our own pacing.

So each list answer is checked against this table, and a report seen for the
first time is written once, with two instants: when we first saw it, and the
last list answer before that which did NOT name it. The report reached the API
between the two — a window as narrow as the tick cadence (15 minutes on the
day a weekly report is formed, hourly otherwise). ``prior_list_at`` is null
when no earlier answer is on record, which is a missing bound, not a zero.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime

from sqlalchemy import BigInteger, Date, DateTime, String
from sqlalchemy.orm import Mapped, mapped_column

from src.core.database import Base

_SCHEMA: str = "finreports"


class ReportPublication(Base):
    """The first time ``sales-reports/list`` named one report for one workspace.

    Attributes:
        report_id: WB ``reportId`` (natural primary key, unique across WB).
        workspace_id: Owning workspace (tenancy; no cross-schema FK).
        period: ``weekly`` or ``daily`` — which list answered.
        date_from / date_to: The period WB states the report covers.
        create_date: WB's own ``createDate``.
        first_listed_at: The first list answer that named it.
        prior_list_at: The last list answer before that which did not.
    """

    __tablename__ = "report_publication"
    __table_args__ = {"schema": _SCHEMA}

    report_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    workspace_id: Mapped[uuid.UUID] = mapped_column(nullable=False, index=True)
    period: Mapped[str] = mapped_column(String(8), nullable=False)
    date_from: Mapped[date | None] = mapped_column(Date, nullable=True)
    date_to: Mapped[date | None] = mapped_column(Date, nullable=True)
    create_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    first_listed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    prior_list_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
