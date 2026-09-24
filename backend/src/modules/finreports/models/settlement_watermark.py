"""How far the settlement walk has actually got, per workspace.

Not the same question as "what period does the newest report claim to cover",
and the difference is what this table exists to keep apart.

WB served the settlement report once per ~917 s per token, so a span needing
more than one request was walked over several ticks (see
:mod:`src.modules.finreports.tasks.settlement`). Every page that landed wrote
the report header with the period **WB states** — the full week — so after a
single page of a six-day report the header already said it covered all six
days. (Since 2026-09-23 the header is written only after all of a report's rows;
the separation this table keeps is still the rule.)
Reading the harvest's watermark off that header therefore claimed days that had
never been fetched: on 2026-09-07 four of five workspaces held one day of the
01.09-06.09 week while the header said six, the freshness gate probed only the
day after the stated end, found nothing, and skipped the week forever. The P&L
was short five days of settlement and nothing about it looked like an error.

So the watermark is recorded from what the walk *completed*, not from what WB
*published*, and it advances only over an unbroken prefix of completed windows —
a gap behind it would be invisible to a single high-water date.

**It is a ceiling on the reachable history, never the history itself.** A window
WB answers *empty* completes like any other, and WB forms a week's report the day
after the week ends — so the Sunday-night tick asks about the open week, is told
nothing, and the watermark certifies days no report exists for yet. Read alone it
then closes the gate on the report that lands on Monday, which on 2026-09-14 left
three of five workspaces without the 07.09-13.09 week while every tick answered
«settled through 13.09 — nothing newer can exist yet». What the gate and the walk
span read is therefore the *earlier* of this mark and the last day a harvested
report covers — see
:func:`~src.modules.finreports.tasks.spans.settlement_frontier`. Each of the two
dates over-claims in the direction the other one does not.

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
