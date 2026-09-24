"""ORM models for the Workspaces module (PostgreSQL ``workspaces`` schema).

A *workspace* is the tenancy unit: every monitored SKU belongs to exactly one
workspace, and each workspace owns its own set of WildBerries API tokens. The
tokens are stored **encrypted** (Fernet, key from ``FERNET_SECRET_KEY``) — the
database never sees a plaintext WB credential.
"""

from __future__ import annotations

import enum
import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.core.database import Base
from src.core.ids import uuid7

#: Every table in this module lives in the ``workspaces`` logical schema.
_SCHEMA: str = "workspaces"


class TokenKind(enum.StrEnum):
    """The WB API category a stored token is scoped to.

    The WB seller portal issues category-scoped tokens; a token can carry one or
    several of these 13 categories. A *primary* workspace stores a token per
    category (granular control); every other workspace stores a single
    :attr:`UNIFIED` token used for all categories (see
    :attr:`~.models.Workspace.is_primary`).
    """

    CONTENT = "content"  # Контент
    ANALYTICS = "analytics"  # Аналитика
    PRICES = "prices"  # Цены и скидки
    MARKETPLACE = "marketplace"  # Маркетплейс
    STATISTICS = "statistics"  # Статистика
    PROMOTION = "promotion"  # Продвижение (advertising)
    FEEDBACK = "feedback"  # Вопросы и отзывы
    CHAT = "chat"  # Чат с покупателем
    SUPPLIES = "supplies"  # Поставки
    RETURNS = "returns"  # Возвраты
    DOCUMENTS = "documents"  # Документы
    FINANCE = "finance"  # Финансы
    USERS = "users"  # Пользователи

    #: A single all-category token for non-primary workspaces (not one of the
    #: 13 real WB categories — a stand-in resolved for every surface).
    UNIFIED = "unified"


#: The 13 real WB API categories, in seller-portal order (excludes UNIFIED).
CATEGORY_KINDS: tuple[TokenKind, ...] = (
    TokenKind.CONTENT,
    TokenKind.ANALYTICS,
    TokenKind.PRICES,
    TokenKind.MARKETPLACE,
    TokenKind.STATISTICS,
    TokenKind.PROMOTION,
    TokenKind.FEEDBACK,
    TokenKind.CHAT,
    TokenKind.SUPPLIES,
    TokenKind.RETURNS,
    TokenKind.DOCUMENTS,
    TokenKind.FINANCE,
    TokenKind.USERS,
)


class BackfillLane(enum.StrEnum):
    """One module's share of a new workspace's history.

    A lane is a unit of *reporting*, not of scheduling: each one is walked by
    its own tick task at its own cadence, because the surfaces behind them are
    metered differently by three orders of magnitude — the funnel and
    advertising aggregate refill a token every ~20 s, while the settlement
    report serves **one request a minute per method** (one per fifteen minutes
    per token until the finance-api cutover on 2026-09-22). Showing them
    as one bar would park it near zero for most of a day; showing four lanes
    lets the three fast ones report «готово» while the slow one keeps its own
    honest estimate.
    """

    CATALOGUE = "catalogue"  # Каталог — cards, sizes, SKU ownership
    FUNNEL = "funnel"  # Воронка — 365 days, the WB ceiling
    ADVERTISING = "advertising"  # Реклама — to the first campaign
    PNL = "pnl"  # P&L — to the first settlement report


class BackfillState(enum.StrEnum):
    """Where one lane has got to."""

    PENDING = "pending"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"


class WorkspaceBackfill(Base):
    """One lane's progress AND its resume point, for one workspace.

    Deliberately one row rather than two mechanisms. The «Обновить все SKU»
    refresh publishes progress into Celery's result backend and the SPA polls
    it by task id, which works because that refresh is over in minutes. A
    backfill is not: the P&L lane runs for **sixteen hours** on a large
    account, across worker restarts, deploys and the seller closing the tab.
    A task id in a result backend with a TTL cannot survive that, so progress
    lives in Postgres — and once it does, the cursor may as well live in the
    same row, because "how far along are we" and "where do we resume" are the
    same fact asked by two callers.

    ``cursor`` is opaque here on purpose: each lane owns its own format (a date
    to resume walking from, a window end, an ``rrd_id`` page cursor). This
    module schedules nothing and interprets nothing — it records what the lanes
    tell it.

    Attributes:
        workspace_id: Owning workspace (FK, cascade delete).
        lane: Which :class:`BackfillLane` this row tracks.
        state: :class:`BackfillState`.
        done_units / total_units: Progress numerator and denominator, in
            whatever unit the lane counts (days, windows, pages). ``total`` is
            an ESTIMATE the lane may revise — a walk that stops early on WB's
            retention floor finishes with ``done < total``, which is why
            ``state`` and not the ratio is what says "finished".
        cursor: The lane's private resume point; ``None`` before it starts.
        message: Russian, user-facing — rendered verbatim under the lane.
        started_at / finished_at: When the lane began and stopped.
        updated_at: Last tick, so a stalled lane is visible as such.
    """

    __tablename__ = "workspace_backfill"
    __table_args__ = {"schema": _SCHEMA}

    workspace_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey(f"{_SCHEMA}.workspaces.id", ondelete="CASCADE"), primary_key=True
    )
    lane: Mapped[str] = mapped_column(String(16), primary_key=True)
    state: Mapped[str] = mapped_column(String(16), default=BackfillState.PENDING, nullable=False)
    done_units: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    total_units: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    cursor: Mapped[str | None] = mapped_column(Text, nullable=True)
    message: Mapped[str] = mapped_column(String(256), default="", nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class Workspace(Base):
    """A tenant workspace grouping SKUs and WB credentials.

    Attributes:
        id: UUIDv7 primary key (time-ordered, non-enumerable).
        organization_id: The owning tenant. NOT NULL and without a default: a
            workspace that belongs to no company is unreachable by any caller
            (every request resolves its workspaces through the caller's
            organisation) while still being harvested on the schedule — WB
            budget spent on data nobody can read. See
            ``src.modules.organizations``.
        name: Human-readable workspace name (e.g. the seller's legal name).
        is_primary: The main workspace stores a token per WB category (granular
            control); every other workspace stores a single ``unified`` token
            reused for all categories. Exactly one workspace is primary (the
            seeded «ИП Иванов. И. И.»); new workspaces are never primary.
        created_at: Server-assigned creation timestamp (UTC).
        tokens: The encrypted WB API tokens owned by this workspace.
    """

    __tablename__ = "workspaces"
    __table_args__ = {"schema": _SCHEMA}

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid7)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.organizations.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    # Unique ACROSS tenants, not per tenant. Two companies may legitimately want
    # the same workspace name, and this will have to become a per-organisation
    # constraint the first time they do — but a workspace name is also what the
    # refusing rather than a limitation worth removing.
    name: Mapped[str] = mapped_column(String(256), unique=True, nullable=False)
    is_primary: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    tokens: Mapped[list[WorkspaceToken]] = relationship(
        back_populates="workspace",
        cascade="all, delete-orphan",
    )


class WorkspaceToken(Base):
    """One encrypted WB API token of a workspace, per API surface.

    Attributes:
        id: UUIDv7 primary key.
        workspace_id: Owning workspace (FK, cascade delete).
        kind: The WB API surface this token authenticates (:class:`TokenKind`).
        token_encrypted: Fernet ciphertext of the bearer token — never the
            plaintext (see :mod:`src.core.security`).
        updated_at: Timestamp of the last rotation.
    """

    __tablename__ = "workspace_tokens"
    __table_args__ = (
        UniqueConstraint("workspace_id", "kind", name="uq_workspace_tokens_workspace_kind"),
        {"schema": _SCHEMA},
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid7)
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey(f"{_SCHEMA}.workspaces.id", ondelete="CASCADE"), index=True
    )
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    token_encrypted: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    workspace: Mapped[Workspace] = relationship(back_populates="tokens")
