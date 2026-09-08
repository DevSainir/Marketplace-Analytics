"""How far the settlement walk has actually got, per workspace.

Not the same question as "what period does the newest report claim to cover",
and the difference is what this table exists to keep apart.

WB serves the settlement report once per ~917 s per token, so a span needing
more than one request is walked over several ticks (see
:mod:`src.modules.finreports.tasks.settlement`). Every page that lands writes
the report header with the period **WB states** — the full week — so after a
single page of a six-day report the header already says it covers all six days.
Reading the harvest's watermark off that header therefore claimed days that had
never been fetched: on 2026-09-07 four of five workspaces held one day of the
01.09-06.09 week while the header said six, the freshness gate probed only the
day after the stated end, found nothing, and skipped the week forever. The P&L
was short five days of settlement and nothing about it looked like an error.

So the watermark is recorded from what the walk *completed*, not from what WB
*published*, and it advances only over an unbroken prefix of completed windows —
a gap behind it would be invisible to a single high-water date.

Deliberately per workspace rather than per report: the walk asks for date spans,
not for report ids, and a span can cover days WB has published no report for at
all. The question the gate asks is "which days have I asked about and got a
complete answer for", which is a property of the asking, not of the reports.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime

from sqlalchemy import Date, DateTime, func
from sqlalchemy.orm import Mapped, mapped_column

from src.core.database import Base

_SCHEMA: str = "finreports"


class SettlementWatermark(Base):
    """The last settlement day one workspace's walk has completed.

    Attributes:
        workspace_id: Owning workspace (tenancy; no cross-schema FK).
        settled_through: Last day covered by an unbroken run of completed
            settlement windows. Monotonic — see
            :meth:`~src.modules.finreports.repos.settlement_watermark.SettlementWatermarkRepository.advance_to`.
        updated_at: When the walk last moved it.
    """

    __tablename__ = "settlement_watermark"
    __table_args__ = {"schema": _SCHEMA}

    workspace_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    settled_through: Mapped[date] = mapped_column(Date, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
