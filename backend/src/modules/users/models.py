"""ORM models for the Users module (PostgreSQL ``auth`` schema).

Contains the ``User`` aggregate and the ``RefreshToken`` session-tracking table
that powers Refresh Token Rotation (RTR) with breach detection.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.core.database import Base
from src.core.ids import uuid7

#: Every table in this module lives in the ``auth`` logical schema.
_SCHEMA: str = "auth"


class User(Base):
    """A platform user / seller account.

    Attributes:
        id: UUIDv7 primary key (time-ordered, non-enumerable).
        email: Unique login identifier.
        hashed_password: bcrypt digest of the account password.
        is_active: Soft-disable flag; inactive users cannot authenticate.
        created_at: Server-assigned creation timestamp (UTC).
        refresh_tokens: All refresh-token rows ever issued to this user.
    """

    __tablename__ = "users"
    __table_args__ = {"schema": _SCHEMA}

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid7)
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True)
    hashed_password: Mapped[str] = mapped_column(String(128))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    refresh_tokens: Mapped[list[RefreshToken]] = relationship(
        back_populates="user",
        cascade="all, delete-orphan",
    )


class RefreshToken(Base):
    """A single node in a refresh-token family chain (RTR state machine).

    Each successful refresh consumes one row (``is_used = True``) and issues a
    child row pointing back via ``parent_id``. Replay of a consumed row signals
    theft and triggers a full family revocation.

    Attributes:
        id: UUIDv7 primary key — also the JWT ``jti`` of the issued pair.
        user_id: Owning user's id (FK, indexed for bulk revocation).
        parent_id: The token this one superseded (``None`` for a fresh login).
        family_id: Stable identifier shared by every token in one login lineage.
        token_hash: SHA-256 digest of the opaque refresh secret.
        is_used: ``True`` once the token has been rotated/consumed.
        is_revoked: ``True`` once invalidated (logout or breach response).
        expires_at: Absolute expiry (UTC).
        created_at: Server-assigned issuance timestamp (UTC).
    """

    __tablename__ = "refresh_tokens"
    __table_args__ = {"schema": _SCHEMA}

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid7)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey(f"{_SCHEMA}.users.id", ondelete="CASCADE"), index=True
    )
    parent_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey(f"{_SCHEMA}.refresh_tokens.id", ondelete="SET NULL"),
        nullable=True,
    )
    family_id: Mapped[uuid.UUID] = mapped_column(index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    is_used: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_revoked: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    user: Mapped[User] = relationship(back_populates="refresh_tokens")
