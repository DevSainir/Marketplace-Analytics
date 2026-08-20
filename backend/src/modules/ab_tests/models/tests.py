"""The A/B test itself and its photo variants.

A test is a **sequential rotation**, not a simultaneous split: a WB card has
exactly one main photo at a time, so variants take turns. Each variant is set as
the card's main photo, left there until it has accumulated the test's impression
budget, and then replaced by the next one. That is the only shape WB's API
permits — see the ``wildberries-api`` skill for why a true concurrent A/B is not
buildable on this platform.

Impressions come from **advertising** (`/adv/v3/fullstats`), the sole surface on
WB that reports them at all; organic показы exist in the seller cabinet and in no
API. A test therefore only advances while the card is being advertised.
"""

from __future__ import annotations

import enum
import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    DateTime,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.core.database import Base
from src.core.ids import uuid7

_SCHEMA: str = "ab_tests"

#: WB refuses a card with no images, and the cabinet's own tool caps a gallery
#: well below this; ten is the product limit the upload endpoint enforces.
MAX_VARIANTS_PER_TEST: int = 10

#: Impressions one variant must accumulate before the rotation advances. The
#: default is the product's, not WB's — see :mod:`.services.rotation` for what
#: this number can and cannot resolve statistically.
DEFAULT_IMPRESSION_BUDGET: int = 10_000


class AbTestStatus(enum.StrEnum):
    """Lifecycle of a test.

    ``DRAFT`` accepts variant uploads and has never touched the card.
    ``RUNNING`` has a live variant on the card and advances on the daily pass.
    ``PAUSED`` keeps the current photo but stops advancing and stops attributing
    days — a paused stretch belongs to no variant.
    ``COMPLETED`` finished its last round; ``CANCELLED`` was stopped by hand.
    """

    DRAFT = "draft"
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


#: Statuses in which the rotation task may act on a test.
ADVANCEABLE_STATUSES: frozenset[str] = frozenset({AbTestStatus.RUNNING})


class AbTest(Base):
    """One photo-rotation test over a single WB card.

    Attributes:
        id: UUIDv7 primary key.
        workspace_id: Owning workspace — tests are per-tenant, like tokens.
        nm_id: The WB SKU whose main photo is rotated.
        vendor_code: Артикул продавца, denormalised from the card so the list
            can be searched by it without joining the monitoring module.
        name: Human title of the test, shown in the list.
        status: See :class:`AbTestStatus`.
        impression_budget: Ad impressions one variant must gather before the
            next one is installed.
        active_variant_id: The variant currently on the card, or ``None`` for a
            test that has not started (or has finished).
        started_at: When the first variant was installed.
        finished_at: When the last variant's budget was met, or the test was
            cancelled.
    """

    __tablename__ = "ab_test"
    __table_args__ = {"schema": _SCHEMA}

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid7)

    workspace_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workspaces.workspaces.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )

    nm_id: Mapped[int] = mapped_column(BigInteger, index=True, nullable=False)
    vendor_code: Mapped[str] = mapped_column(String(255), server_default="", nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)

    status: Mapped[str] = mapped_column(
        String(16), server_default=AbTestStatus.DRAFT.value, index=True, nullable=False
    )

    impression_budget: Mapped[int] = mapped_column(
        Integer, server_default=str(DEFAULT_IMPRESSION_BUDGET), nullable=False
    )

    active_variant_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey(f"{_SCHEMA}.ab_test_variant.id", ondelete="SET NULL"), nullable=True
    )

    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    variants: Mapped[list[AbTestVariant]] = relationship(
        back_populates="test",
        cascade="all, delete-orphan",
        order_by="AbTestVariant.position",
        foreign_keys="AbTestVariant.test_id",
    )


class AbTestVariant(Base):
    """One candidate main photo inside a test.

    The image bytes live on disk (see :mod:`.services.photos`) rather than in
    the row: they are pushed to WB as multipart, and streaming them back to the
    SPA from a file is cheaper than carrying megabytes through the ORM.

    Attributes:
        id: UUIDv7 primary key.
        test_id: Owning test.
        position: 1-based rotation order. Rotation walks these ascending.
        image_path: Path of the stored original, relative to the media root.
        image_sha256: Digest of the stored bytes — identifies a re-upload of the
            same picture and proves what was actually sent to WB.
        content_type: MIME type as uploaded, replayed to WB on install.
        original_filename: What the user called the file, for the UI only.
    """

    __tablename__ = "ab_test_variant"
    __table_args__ = (
        UniqueConstraint("test_id", "position", name="uq_ab_test_variant_test_position"),
        {"schema": _SCHEMA},
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid7)

    test_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey(f"{_SCHEMA}.ab_test.id", ondelete="CASCADE"), index=True, nullable=False
    )

    position: Mapped[int] = mapped_column(Integer, nullable=False)

    image_path: Mapped[str] = mapped_column(String(512), nullable=False)
    image_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    content_type: Mapped[str] = mapped_column(
        String(64), server_default="image/jpeg", nullable=False
    )
    original_filename: Mapped[str] = mapped_column(String(255), server_default="", nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    test: Mapped[AbTest] = relationship(back_populates="variants", foreign_keys=[test_id])
