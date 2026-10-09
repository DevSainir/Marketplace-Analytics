"""Pre-summed settlement detail — one row per кабинет / отчёт / день / артикул.

**This table is a cache, and the read path proves it before trusting it.** Every
query that reads it first asks the detail how many rows each day of the window
has — an index-only scan, 16 MB against the detail's 755 — and any day whose
counts disagree is recomputed from the detail and rewritten here. A stale or
missing row therefore costs time, never correctness, which is the only property
that makes a derived copy of a seller's money safe to keep at all.

Why it exists: the settlement detail is 1 459 394 rows and 870 MB against a
128 MB `shared_buffers`, so a window covering most of it is a parallel *seq*
scan — 714 MB off disk, ~7 s per pass, measured. The same rows collapse to
27 857 groups on this key, which is a 40-fold reduction and small enough to live in
cache. That is the difference between «Вся история» being a page and being a
timeout.

The key carries ``report_id`` as well as ``rr_dt`` so every cut the statement
offers — total, day, week (per report), month, SKU — is derivable from one
stored grain. Rows WB dated with no ``rr_dt`` are not summarised: every windowed
query filters on that column, so such rows are outside all of them anyway.

Column for column, this mirrors ``SettlementAggregate``. That is deliberate and
load-bearing: the reader sums these into exactly that dataclass, so a column
added to the aggregate without a column here would silently read as zero.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import BigInteger, Date, DateTime, Integer, Numeric, String, func
from sqlalchemy.orm import Mapped, mapped_column

from src.core.database import Base


def _money() -> Mapped[Decimal]:
    """A settlement money column: same precision as the detail it sums."""
    return mapped_column(Numeric(18, 2), default=Decimal(0), nullable=False)


class SettlementDailyRollup(Base):
    """One day of one article's settlement, pre-summed."""

    __tablename__ = "settlement_daily_rollup"
    __table_args__ = {"schema": "finreports"}

    workspace_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    report_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    rr_dt: Mapped[date] = mapped_column(Date, primary_key=True)
    nm_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)

    #: The modal currency of the group's rows. A кабинет is effectively
    #: single-currency, but stray rows exist and `max()` is lexical — it would
    #: report "RUB" for a KGS window and make every cost price unmatchable.
    currency: Mapped[str] = mapped_column(String(8), default="", nullable=False)
    #: The seller's article. Not part of the summed set — it is the LABEL of the
    #: per-article cut, and a cut cannot name its own rows without it.
    sa_name: Mapped[str] = mapped_column(String(128), default="", nullable=False)
    subject_name: Mapped[str] = mapped_column(String(128), default="", nullable=False)
    brand_name: Mapped[str] = mapped_column(String(128), default="", nullable=False)

    sold_units: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    returned_units: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    #: Forward logistics legs — units carried to a buyer; the «Выкуп» denominator.
    delivered_units: Mapped[int] = mapped_column(
        Integer, default=0, server_default="0", nullable=False
    )

    sales_gross: Mapped[Decimal] = _money()
    returns_gross: Mapped[Decimal] = _money()
    sales_before_spp: Mapped[Decimal] = _money()
    returns_before_spp: Mapped[Decimal] = _money()
    payout_sales: Mapped[Decimal] = _money()
    payout_returns: Mapped[Decimal] = _money()
    payout_other: Mapped[Decimal] = _money()

    #: Kept at the detail's own 10-decimal precision: `ppvz_vw` is a
    #: VAT-inclusive figure divided by 1.12 and the commission line is a
    #: residual over it, so rounding here moves the printed commission.
    wb_commission_reported: Mapped[Decimal] = mapped_column(
        Numeric(22, 10), default=Decimal(0), nullable=False
    )
    wb_commission_vat: Mapped[Decimal] = _money()
    wb_reward: Mapped[Decimal] = _money()
    acquiring_withheld: Mapped[Decimal] = _money()
    acquiring_billed_apart: Mapped[Decimal] = _money()
    agency_vat: Mapped[Decimal] = _money()

    logistics_forward: Mapped[Decimal] = _money()
    logistics_return: Mapped[Decimal] = _money()
    logistics_unlegged: Mapped[Decimal] = _money()

    storage: Mapped[Decimal] = _money()
    acceptance: Mapped[Decimal] = _money()
    penalties: Mapped[Decimal] = _money()
    deductions: Mapped[Decimal] = _money()
    additional_payments: Mapped[Decimal] = _money()
    rebill_logistic_cost: Mapped[Decimal] = _money()
    advertising: Mapped[Decimal] = _money()

    #: P&L aggregate on purpose; written by the same rebuild.
        Numeric(18, 2), default=Decimal(0), server_default="0", nullable=False
    )
        Integer, default=0, server_default="0", nullable=False
    )
        Integer, default=0, server_default="0", nullable=False
    )
        Numeric(18, 2), default=Decimal(0), server_default="0", nullable=False
    )
    #: How many detail rows this group sums. THE verification column: a read
    #: compares it against the detail's own count for the same day and rebuilds
    #: the day when the two disagree.
    rows: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    #: every write to the detail deletes the days it touches, so a restated row
    #: comes back here with a new ``built_at`` even when the count is the same.
    built_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
