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
#: It bounds every photo in the test, the one marked «Главное» included. That
#: one used to be captured off the card rather than chosen, so charging it to
#: the seller's allowance would have cost them a slot they never spent; now it
#: is an upload like any other and counts like one.
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

    ``IMPRESSIONS`` — equal audience per photo, unequal wall-clock. The
    statistically sound default: every variant is judged on the same number of
    chances.

    ``TIME`` — equal wall-clock per photo, unequal audience. Worth having
    anyway, because it is the only mode that works on a card whose advertising
    is switched off (nothing accumulates, so an impression budget would never
    fire), and because a fixed slot cycles variants through the same hours of
    the day, which balances the time-of-day effect faster.

    ``EITHER`` — both settings are in force and the FIRST one reached advances
    the rotation. It used to be refused on the grounds that arms measured over
    different exposures are not comparable, and that is still true of the
    number a trigger fires on; what the refusal ignored is the failure the
    seller actually meets. A budget alone stalls a photo for days when the
    advertising slows, and a slot alone hands one photo a burst of traffic
    another never saw. Naming both bounds the turn from both sides — «не дольше
    20 минут и не больше 1 000 показов» — and every window records the exposure
    a turn really got, so the result table divides by what was measured rather
    than by what was budgeted.
    """

    IMPRESSIONS = "impressions"
    TIME = "time"
    EITHER = "either"


class AbTestStatus(enum.StrEnum):
    """Lifecycle of a test.

    ``DRAFT`` accepts variant uploads and has never touched the card.
    ``RUNNING`` has a live variant on the card and advances on the polling pass.
    ``PAUSED`` keeps the current photo but stops advancing and stops attributing
    traffic — a paused stretch belongs to no variant, because the poller skips
    the test and no window is opened over it.
    ``CANCELLED`` was stopped by hand — the only way a test ends now.

    ``COMPLETED`` is **legacy**. It used to be set when the advertising budget
    reached zero, and nothing sets it any more: a spent budget is a pause,
    because a campaign that empties overnight is topped up in the morning and
    the test should still be there. Rows that already carry it keep it, and it
    stays terminal for them; see :mod:`..services.budget`.
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
            next one is installed. Read in ``IMPRESSIONS`` and ``EITHER`` mode.
        slot_minutes: How long one variant stays up. Read in ``TIME`` and
            ``EITHER`` mode.
        active_variant_id: The variant currently on the card, or ``None`` for a
            test that has not started (or has finished).
        paused_by_ads: True when the ROTATION paused this test because nothing
            was advertising the card, as opposed to the seller pausing it by
            hand. The two look identical in ``status`` and must not be: a test
            the seller paused stays paused until they say otherwise, while this
            one resumes on its own the moment the campaign does.
        started_at: When the first variant was installed.
        finished_at: When the last variant's budget was met, or the test was
            cancelled.
        photo_conflict_at: When the poller found a main photo on the card that
            this rotation did not install, or ``None``. Set alongside a pause,
            and **not** cleared by the rotation: unlike a campaign switching
            back on, a card somebody edited by hand is not a condition that
            resolves itself, and a test that resumed on its own would fight the
            seller's own edit every five minutes. Only a deliberate restart
            clears it.
        stopped_at: When the rotation last STOPPED advancing — a pause as much
            as a finish. ``finished_at`` only answers that for a test that
            ended, and a paused test is the case where the question is actually
            asked: "since when has this been standing still?" Cleared on every
            transition back into ``RUNNING``, so it never describes a test that
            is moving.
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

    paused_by_ads: Mapped[bool] = mapped_column(Boolean, server_default="false", nullable=False)

    photo_conflict_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    stopped_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

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
    uploaded as candidates, and the one they uploaded as «Главное» — the
    baseline the others are read against. Both are uploads. The baseline used to
    be pulled off the card from WB's CDN, and it was dropped: WB serves
    renditions rather than the seller's own file, so every comparison was
    against a re-transcoded image and every re-install pushed that loss back
    onto the live card.

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
        is_original: True for the photo the seller marked as «Главное». It
            sorts first, opens the rotation and is installed like every other
            variant — nothing about it is assumed to be on the card already.
            At most one per test.
        excluded_at: When the seller took this photo out of the rotation, or
            ``None`` while it is still in. Excluding is **not** deleting: the
            row, the image and every window already credited to it stay, so the
            result table keeps showing what it earned. It is simply skipped from
            the next round on. Reversible.
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

    excluded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    @property
    def is_excluded(self) -> bool:
        """Is this photo out of the rotation?

        A property rather than a second column: two fields that must agree are
        two fields that can disagree, and the timestamp answers both «is it
        out» and «since when».
        """
        return self.excluded_at is not None

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    test: Mapped[AbTest] = relationship(back_populates="variants", foreign_keys=[test_id])
