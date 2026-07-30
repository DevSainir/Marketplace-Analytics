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

from sqlalchemy import Boolean, DateTime, ForeignKey, String, Text, UniqueConstraint, func
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


class Workspace(Base):
    """A tenant workspace grouping SKUs and WB credentials.

    Attributes:
        id: UUIDv7 primary key (time-ordered, non-enumerable).
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
