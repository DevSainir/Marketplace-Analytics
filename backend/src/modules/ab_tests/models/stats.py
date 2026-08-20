"""What each variant was exposed to, and what it earned.

Two tables, deliberately separate:

* :class:`VariantExposure` is the **audit trail of the rotation** — when a photo
  was actually installed on the card and when it came off. It is written by the
  code that talks to WB, so it records what happened rather than what was
  planned; a failed install leaves no row and the test does not advance.
* :class:`VariantStatDaily` is the **attributed advertising day**. Its grain is
  one variant per day, summed across every campaign and platform that served the
  card that day.

The join between them is a whole-day rule: a day belongs to a variant only if
that variant was live for the entire day. WB reports advertising by calendar day
and nothing finer, so the day a photo is swapped is split between two variants
and cannot be honestly assigned to either — it is attributed to neither. See
:mod:`.services.attribution`.
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
        wb_photo_number: Which gallery slot was written — always 1 (the main
            photo) today, stored because WB's numbering is what we would need to
            reproduce to undo a rotation.
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

    wb_photo_number: Mapped[int] = mapped_column(Integer, server_default="1", nullable=False)


class VariantStatDaily(Base):
    """One advertising day attributed to one variant.

    The counts are copied verbatim from ``/adv/v3/fullstats`` and summed over the
    campaigns and platforms that served this SKU that day. Ratios are **not**
    stored: CTR and the two conversions are derived on read from these counts,
    the same discipline «Процент выкупа» follows in the monitoring module — a
    stored percentage cannot be re-aggregated across days without lying.

    Attributes:
        variant_id: Which photo was live that day (composite PK).
        stat_date: The advertising day, Moscow time (composite PK).
        views: Impressions of the card in ad placements («Показы»).
        clicks: Clicks through to the card («Переходы в карточку»).
        atbs: Add-to-basket events («Добавления в корзину»).
        orders: Orders placed («Оформления заказов»).
        spend: Ad spend for the day, in the account's currency.
    """

    __tablename__ = "ab_test_variant_stat_daily"
    __table_args__ = {"schema": _SCHEMA}

    variant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey(f"{_SCHEMA}.ab_test_variant.id", ondelete="CASCADE"), primary_key=True
    )
    stat_date: Mapped[date] = mapped_column(Date, primary_key=True)

    test_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey(f"{_SCHEMA}.ab_test.id", ondelete="CASCADE"), index=True, nullable=False
    )

    views: Mapped[int] = mapped_column(BigInteger, server_default="0", nullable=False)
    clicks: Mapped[int] = mapped_column(BigInteger, server_default="0", nullable=False)
    atbs: Mapped[int] = mapped_column(BigInteger, server_default="0", nullable=False)
    orders: Mapped[int] = mapped_column(BigInteger, server_default="0", nullable=False)
    spend: Mapped[float] = mapped_column(Numeric(14, 2), server_default="0", nullable=False)

    currency: Mapped[str] = mapped_column(String(8), server_default="RUB", nullable=False)

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
