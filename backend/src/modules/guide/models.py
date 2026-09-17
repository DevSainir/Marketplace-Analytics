"""Two tables: what WB answered, and how far each source has been walked.

The payload column is deliberate. See the module docstring in
:mod:`src.modules.guide` for why a capture buffer stores JSON rather than
columns; the short version is that typing a feed nobody reads yet means
inventing its shape twice.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any

from sqlalchemy import Date, DateTime, Index, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from src.core.database import Base

_SCHEMA: str = "guide"


class GuideRecord(Base):
    """One row WB served, kept verbatim.

    Attributes:
        source: Which feed this came from — a key from
            :data:`src.modules.guide.sources.GUIDE_SOURCES`.
        workspace_id: The tenant whose token fetched it. Present even on feeds
            WB serves account-wide, because "whose data is this" must be
            answerable from the row rather than from the task that wrote it.
        record_key: The feed's own natural identity for the row (``srid`` for an
            order, the claim id for a claim, ``<date>|<warehouse>`` for a tariff
            day). Stable across re-reads, so a repeated window overwrites rather
            than duplicating — WB restates recent rows and we want the freshest.
        recorded_for: The Moscow-time day the row is ABOUT, when the feed says.
            Null where it says nothing (a document, a review). This is the only
            promoted column: every "what did we capture for that period" query
            needs it, and digging it out of the payload per row does not index.
        payload: WB's object, unmodified. Field names are WB's, camelCase and
            all — renaming them here would be the modelling this table exists to
            postpone.
        captured_at: When we stored it. Distinct from ``recorded_for``: a claim
            from last week captured today says both things, and the gap between
            them is how a serving delay becomes visible.
    """

    __tablename__ = "guide_record"
    __table_args__ = (
        Index("ix_guide_record_source_workspace_day", "source", "workspace_id", "recorded_for"),
        {"schema": _SCHEMA},
    )

    source: Mapped[str] = mapped_column(String(32), primary_key=True)
    workspace_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    record_key: Mapped[str] = mapped_column(String(160), primary_key=True)

    recorded_for: Mapped[date | None] = mapped_column(Date, nullable=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    captured_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class GuideRun(Base):
    """How far one source has been walked for one workspace, and how it went.

    One row per ``(source, workspace)``, overwritten each run. This is a
    watermark, not a log: what matters is where to resume, and a run history
    nobody reads is the kind of table that quietly becomes the biggest one.

    Attributes:
        source: Feed key, as on :class:`GuideRecord`.
        workspace_id: The tenant.
        cursor: Where to resume, in whatever form the feed's walk needs — a
            ``lastChangeDate`` for the orders stream, a ``skip`` offset for
            reviews. Text because the feeds disagree and none of it is ours to
            interpret outside its own fetcher.
        captured_through: The last day fully covered by a windowed walk. The
            windowed sources resume from here; a feed with no windows leaves it
            null.
        last_status: ``ok`` | ``empty`` | ``failed`` | ``skipped``. A failed run
            leaves the cursor at the last point every row behind it was stored —
            which since 2026-09-17 is not necessarily where the run started, because
            a walk commits its batches as they arrive. What it never does is move
            past a row that was captured and not written.
        rows: Rows captured by the last run.
        message: Why it failed, or what it skipped. Never a token — this is read
            from logs and dashboards.
        last_run_at: When the last run finished.
    """

    __tablename__ = "guide_run"
    __table_args__ = {"schema": _SCHEMA}

    source: Mapped[str] = mapped_column(String(32), primary_key=True)
    workspace_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)

    cursor: Mapped[str | None] = mapped_column(String(64), nullable=True)
    captured_through: Mapped[date | None] = mapped_column(Date, nullable=True)
    last_status: Mapped[str] = mapped_column(String(16), nullable=False, default="ok")
    rows: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    message: Mapped[str] = mapped_column(Text, nullable=False, default="")
    last_run_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


__all__ = ["GuideRecord", "GuideRun"]
