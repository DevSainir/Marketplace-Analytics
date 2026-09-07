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
    Boolean,
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
#:
#: It bounds **uploads**. The card's own photo is enrolled on top of it, because
#: it is not a choice the user made: a test whose tenth upload silently pushed
#: the current image out of the comparison would answer a question nobody asked.
#: A full test therefore rotates eleven photos.
MAX_VARIANTS_PER_TEST: int = 10

#: Impressions one variant must accumulate before the rotation advances. The
#: default is the product's, not WB's — see :mod:`.services.rotation` for what
#: this number can and cannot resolve statistically.
DEFAULT_IMPRESSION_BUDGET: int = 10_000

#: Minutes one variant stays on the card when the test rotates on time. An hour
#: is short enough to give every variant several turns a day and long enough
#: that WB's ~3-minute reporting lag and the photo's own propagation are a small
#: fraction of the slot.
DEFAULT_SLOT_MINUTES: int = 60


class TriggerMode(enum.StrEnum):
    """What makes a test advance to its next photo.

    The two are **mutually exclusive** by design, not by accident. A test that
    rotated on "10 000 impressions OR 2 hours, whichever first" would produce
    variants measured over different exposures, and the whole point of the
    budget is that the arms are comparable. Whichever mode is chosen, the other
    one's setting is ignored — and the API refuses a request that sets it.

    ``IMPRESSIONS`` — equal audience per photo, unequal wall-clock. The
    statistically sound default: every variant is judged on the same number of
    chances.

    ``TIME`` — equal wall-clock per photo, unequal audience. Worth having
    anyway, because it is the only mode that works on a card whose advertising
    is switched off (nothing accumulates, so an impression budget would never
    fire), and because a fixed slot cycles variants through the same hours of
    the day, which balances the time-of-day effect faster.
    """

    IMPRESSIONS = "impressions"
    TIME = "time"


class AbTestStatus(enum.StrEnum):
    """Lifecycle of a test.

    ``DRAFT`` accepts variant uploads and has never touched the card.
    ``RUNNING`` has a live variant on the card and advances on the polling pass.
    ``PAUSED`` keeps the current photo but stops advancing and stops attributing
    traffic — a paused stretch belongs to no variant, because the poller skips
    the test and no window is opened over it.
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
        trigger_mode: What advances the rotation — see :class:`TriggerMode`.
        impression_budget: Ad impressions one variant must gather before the
            next one is installed. Read only in ``IMPRESSIONS`` mode.
        slot_minutes: How long one variant stays up. Read only in ``TIME``
            mode.
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

    trigger_mode: Mapped[str] = mapped_column(
        String(16), server_default=TriggerMode.IMPRESSIONS.value, nullable=False
    )

    impression_budget: Mapped[int] = mapped_column(
        Integer, server_default=str(DEFAULT_IMPRESSION_BUDGET), nullable=False
    )

    slot_minutes: Mapped[int] = mapped_column(
        Integer, server_default=str(DEFAULT_SLOT_MINUTES), nullable=False
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

    Two kinds of row, distinguished by ``is_original``: the photos the user
    uploaded, and the one that was already on the card. The second is captured
    from WB when the test is created and joins the rotation ahead of the
    uploads, so every test measures its candidates against the image they would
    be replacing rather than only against each other — and so the seller can see
    that baseline in the list while they are still choosing what to compare.

    The image bytes live on disk (see :mod:`.services.photos`) rather than in
    the row: they are pushed to WB as multipart, and streaming them back to the
    SPA from a file is cheaper than carrying megabytes through the ORM.

    Attributes:
        id: UUIDv7 primary key.
        test_id: Owning test.
        position: Rotation order; the rotation walks these ascending. Uploads
            are numbered from 1 in the order they arrived. **Position 0 is
            reserved for the card's own photo** — see ``is_original`` — so that
            enrolling it needs no renumbering of rows a running test is already
            attributing traffic to.
        is_original: True for the photo that was the card's main image when the
            test was created. It is captured from WB rather than uploaded, it
            always sorts first, and it is the one variant the rotation does not
            have to install: it is what the card is showing.
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

    is_original: Mapped[bool] = mapped_column(Boolean, server_default="false", nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    test: Mapped[AbTest] = relationship(back_populates="variants", foreign_keys=[test_id])
