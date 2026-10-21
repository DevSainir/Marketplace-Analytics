"""The provisional daily tail in front of the settled weekly history.

WB forms a realization report **per day** as well as per week, on the same two
methods — `period: "daily"` against `sales-reports/list` and
`sales-reports/detailed`, defaulting to `weekly`, which is why this service read
only half of the surface until 2026-09-23. A daily report is stamped
``date_to + 1`` and WB serves it that morning, so yesterday's settled money is
readable today instead of waiting the one to eight days a weekly report takes.

Measured on «Демо» for the closed week 14.09-20.09: the seven daily reports
and the weekly report `989438999` are the **same 4 424 rows**, sharing their
``rrdId`` one for one, with every money column summing to the same figure and no
row present in one lane and absent from the other.

**So why a table of its own rather than a row in `financial_report`.** Not
because a daily report is a different kind of document — it is the same
document, cut at a different boundary — but because `financial_report` is what
the weekly machinery reads to answer «how far is this workspace settled».
:meth:`~src.modules.finreports.repos.financial_report.FinancialReportRepository.latest_settled_date`
is ``max(date_to)`` over that table, and a daily header for yesterday would move
it to yesterday: the freshness gate would then conclude that everything WB can
have formed is already held, and stop asking for the weekly report entirely. The
weekly lane's bookkeeping means «settled», this table's means «provisional, and
being watched» — and while the second claim is still unproven, keeping the two
apart is what makes the first one safe.

**The one fact this table exists to settle.** Whether a daily report is revised
after WB first serves it is *not* known. Re-reading one 42 minutes later found it
identical to the digit, which rules out minute-by-minute top-ups and nothing
else; the week-long reconciliation proves dailies end up complete, not how soon.
Until that is answered, a day harvested here must not be treated as settled. So
every report keeps the row count and content digest it had when first ingested,
and :func:`~src.modules.finreports.tasks.daily_tail.verify_daily_tail` re-reads
it a day later and records whether the two agree. The answer accumulates as
data rather than as an assumption.
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
    Index,
    Integer,
    Numeric,
    String,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from src.core.database import Base

_SCHEMA: str = "finreports"


class DailyReportVerdict(enum.StrEnum):
    """What the day-later re-read of a daily report found.

    Stored as its value, so a verdict added later cannot silently re-label the
    rows already recorded.
    """

    #: WB served the same rows: same count, same digest. The expected outcome.
    UNCHANGED = "unchanged"
    #: WB served something different. The rows in
    #: ``logistics_transaction`` are the NEW ones — the re-read upserts over the
    #: top — and the stored digest is what they were before. This is the outcome
    #: that would mean a daily figure must not be shown as final.
    CHANGED = "changed"
    #: The weekly report covering this day has since landed, so the weekly lane
    #: owns these rows and re-reading the daily one would only flip their
    #: ``report_id`` back. Recorded rather than fetched: no request is spent,
    #: and the report is taken off the verification queue honestly rather than
    #: left on it for ever.
    SUPERSEDED = "superseded"
    #: WB no longer lists the report at all. Not a content change and not our
    #: failure to ask — the report we hold rows for has stopped existing on WB's
    #: side, which nothing in this service was able to express before and which
    #: would be indistinguishable from «unchanged» if the screen only compared
    #: figures it could find.
    WITHDRAWN = "withdrawn"


class DailySettlementReport(Base):
    """One WB daily realization report this workspace has harvested.

    Attributes:
        report_id: WB's own ``reportId``. Daily ids are constructed rather than
            allocated — ``938364620260922`` is ``{supplier}{YYYYMMDD}`` — and WB
            warns they need a BigInt-capable JSON parser. Python and this column
            are fine; JavaScript is not, which is why no daily id is sent to the
            frontend.
        workspace_id: Owning workspace (tenancy; no cross-schema FK).
        day: The single settlement day the report covers (``dateFrom`` ==
            ``dateTo``).
        create_dt: WB's own ``createDate``. ``day + 1`` going forward, but NOT
            in the history: every 2024 daily report carries 2024-04-04, the day
            WB backfilled the lane.
        rows: Settlement rows the first ingest left in
            ``logistics_transaction`` for this report.
        digest: Content fingerprint of those same rows. See
            :meth:`DailySettlementRepository.fingerprint
            <src.modules.finreports.repos.daily_settlement.DailySettlementRepository.fingerprint>`.
        first_seen_at: When this report was first harvested. What the
            day-later re-read is measured from.
        verified_at: When the re-read happened, or ``None`` while it is still
            queued.
        verified_rows / verified_digest: What the re-read found. Kept next to
            the originals rather than overwriting them, because the pair IS the
            measurement.
        wb_for_pay_sum / wb_retail_amount_sum / wb_bank_payment_sum: WB's OWN
            totals for this report, as ``sales-reports/list`` served them at
            ingest. The day-later check compares these against the same fields
            listed again — WB's figure against WB's earlier figure, so the
            comparison costs no detail request and our own classification of
            operations never enters it.
        verdict: :class:`DailyReportVerdict`, or ``None`` before the re-read.
    """

    __tablename__ = "daily_settlement_report"
    __table_args__ = (
        # The verification queue's access path: «this workspace's unverified
        # reports, oldest first». Partial, because a verified report stays in
        # the table for ever and within a month outnumbers the pending ones.
        Index(
            "ix_daily_settlement_pending",
            "workspace_id",
            "first_seen_at",
            postgresql_where=text("verdict IS NULL"),
        ),
        {"schema": _SCHEMA},
    )

    # BigInteger, not the default Integer: a daily id is fifteen digits.
    report_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    workspace_id: Mapped[uuid.UUID] = mapped_column(nullable=False, index=True)
    day: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    create_dt: Mapped[date | None] = mapped_column(Date, nullable=True)
    rows: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    digest: Mapped[str] = mapped_column(String(32), default="", nullable=False)
    first_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    verified_rows: Mapped[int | None] = mapped_column(Integer, nullable=True)
    verified_digest: Mapped[str | None] = mapped_column(String(32), nullable=True)
    verdict: Mapped[str | None] = mapped_column(String(16), nullable=True)
    wb_for_pay_sum: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    wb_retail_amount_sum: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    wb_bank_payment_sum: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
