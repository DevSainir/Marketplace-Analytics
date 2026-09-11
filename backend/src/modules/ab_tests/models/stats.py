"""What each variant was exposed to, and what it earned.

Three tables, and the shape of them is the answer to "why can a photo rotate
several times a day".

WB's advertising report has a one-day *reporting* grain — ``fullstats`` refuses
an interval shorter than a day — but not a one-day *observation* grain. Verified
live on 2026-09-04: the endpoint serves the CURRENT day and the numbers move
within minutes (four campaigns gained 75-112 impressions over an eight-minute
gap). So the counters are cumulative-since-midnight, and the difference between
two reads is the traffic of the interval between them.

That is what these tables record:

* :class:`AdCounterSnapshot` — the last cumulative reading per test per day. The
  poller's memory; nothing else reads it.
* :class:`VariantStatWindow` — one row per poll: the DIFFERENCE since the
  previous snapshot, credited to the photo that was live over that interval.
  This replaced a per-day table, and with it the rule that the day of a swap
  belonged to nobody: the poller swaps immediately after closing a window, so a
  swap always lands on a window boundary and no traffic is discarded.
* :class:`VariantExposure` — when a photo was actually installed and removed.
  Written by the code that talks to WB, so it records what happened rather than
  what was planned; a failed install leaves no row and the test does not
  advance.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime

from sqlalchemy import (
    BigInteger,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from src.core.database import Base
from src.core.ids import uuid7

_SCHEMA: str = "ab_tests"


class VariantExposure(Base):
    """One continuous stretch during which a variant was the card's main photo.

    A variant gets a second row rather than a widened one if it comes back for a
    later round, so «сколько раз этот вариант стоял» stays answerable.

    Attributes:
        id: UUIDv7 primary key.
        test_id: Owning test, denormalised so the rotation can read a test's
            whole history without joining variants.
        variant_id: The photo that was installed.
        activated_at: When WB accepted the media upload.
        deactivated_at: When the next variant replaced it; ``None`` while live.
        published_at: The ``Last-Modified`` WB's CDN reported for the card's
            main photo once this install had landed — the storefront's own
            record of when the image changed, read back rather than assumed.

            It is the witness the poller checks the card against. Measured
            2026-09-10: a media upload publishes in the second WB accepts it,
            so a main photo whose ``Last-Modified`` no longer matches this one
            was written by somebody who is not this rotation, and every window
            credited after that point belongs to a picture nobody chose.

            ``None`` means the install could not be vouched for — the CDN was
            unreachable, the card has no stored photo URL, or the timestamp
            never moved. It must read as «cannot check», never as «mismatch»:
            a test stopped by an unreachable CDN would be a worse failure than
            the one this column exists to catch.
        wb_photo_number: Which gallery slot was written — always 1 (the main
            photo) today, stored because WB's numbering is what we would need to
            reproduce to undo a rotation.
        round_number: Which lap of the rotation this turn belonged to, from 1.
            Stored rather than derived: a photo excluded mid-test, or added
            after the first lap, makes «how many turns have there been divided
            by how many photos» wrong, and the round is what the result table
            groups by.
    """

    __tablename__ = "ab_test_variant_exposure"
    __table_args__ = {"schema": _SCHEMA}

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid7)

    test_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey(f"{_SCHEMA}.ab_test.id", ondelete="CASCADE"), index=True, nullable=False
    )
    variant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey(f"{_SCHEMA}.ab_test_variant.id", ondelete="CASCADE"), index=True, nullable=False
    )

    activated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    deactivated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    wb_photo_number: Mapped[int] = mapped_column(Integer, server_default="1", nullable=False)

    round_number: Mapped[int] = mapped_column(Integer, server_default="1", nullable=False)


class AdCounterSnapshot(Base):
    """The last cumulative advertising reading for one test on one day.

    WB's counters restart at Moscow midnight, so the snapshot is keyed by day as
    well as by test: at a rollover the poller compares today's reading against
    today's snapshot (absent — so the delta is the whole reading) and yesterday's
    against yesterday's, which also picks up WB's late restatements of a day
    already closed.

    Attributes:
        test_id: Owning test (composite PK).
        stat_date: The advertising day the counters belong to (composite PK).
        views / clicks / atbs / orders: Cumulative counts as last read.
        spend: Cumulative spend as last read.
        captured_at: When the reading was taken — this is what bounds the next
            window, so it is the poller's clock rather than WB's.
    """

    __tablename__ = "ab_test_ad_snapshot"
    __table_args__ = {"schema": _SCHEMA}

    test_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey(f"{_SCHEMA}.ab_test.id", ondelete="CASCADE"), primary_key=True
    )
    stat_date: Mapped[date] = mapped_column(Date, primary_key=True)

    views: Mapped[int] = mapped_column(BigInteger, server_default="0", nullable=False)
    clicks: Mapped[int] = mapped_column(BigInteger, server_default="0", nullable=False)
    atbs: Mapped[int] = mapped_column(BigInteger, server_default="0", nullable=False)
    orders: Mapped[int] = mapped_column(BigInteger, server_default="0", nullable=False)
    spend: Mapped[float] = mapped_column(Numeric(14, 2), server_default="0", nullable=False)

    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class VariantStatWindow(Base):
    """One polling interval's traffic, credited to the photo that was live.

    The grain is a poll, not a day: ``window_start`` is the previous snapshot's
    ``captured_at`` and ``window_end`` is this one's. Because the rotation swaps
    the photo immediately after a window closes, exactly one variant was live
    for the whole of any window — which is why nothing here has to be thrown
    away, and why a test can turn over several times a day.

    Counts are stored, ratios are not: CTR and the two conversions are derived
    on read from summed counts, the same discipline «Процент выкупа» follows in
    the monitoring module. A stored percentage cannot be re-aggregated across
    windows without lying.

    Attributes:
        id: UUIDv7 primary key.
        test_id: Owning test.
        variant_id: The photo that was live for this window.
        window_start / window_end: The interval, in UTC.
        views / clicks / atbs / orders: Traffic gained during the interval.
        spend: Ad spend during the interval.
    """

    __tablename__ = "ab_test_variant_stat_window"
    __table_args__ = (
        UniqueConstraint(
            "variant_id", "window_start", name="uq_ab_test_variant_stat_window_variant_start"
        ),
        {"schema": _SCHEMA},
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid7)

    test_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey(f"{_SCHEMA}.ab_test.id", ondelete="CASCADE"), index=True, nullable=False
    )
    variant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey(f"{_SCHEMA}.ab_test_variant.id", ondelete="CASCADE"), index=True, nullable=False
    )

    window_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    window_end: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    views: Mapped[int] = mapped_column(BigInteger, server_default="0", nullable=False)
    clicks: Mapped[int] = mapped_column(BigInteger, server_default="0", nullable=False)
    atbs: Mapped[int] = mapped_column(BigInteger, server_default="0", nullable=False)
    orders: Mapped[int] = mapped_column(BigInteger, server_default="0", nullable=False)
    spend: Mapped[float] = mapped_column(Numeric(14, 2), server_default="0", nullable=False)

    currency: Mapped[str] = mapped_column(String(8), server_default="RUB", nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
