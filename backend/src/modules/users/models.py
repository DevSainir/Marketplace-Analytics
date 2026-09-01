"""ORM models for the Users module (PostgreSQL ``auth`` schema).

Contains the ``User`` aggregate, the ``RefreshToken`` session-tracking table
that powers Refresh Token Rotation (RTR) with breach detection, and the
short-lived ``VerificationCode`` rows behind email confirmation and password
reset (register P1.6).
"""

from __future__ import annotations

import enum
import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.core.database import Base
from src.core.ids import uuid7

#: Every table in this module lives in the ``auth`` logical schema.
_SCHEMA: str = "auth"

#: Default role: regular platform user.
ROLE_USER: str = "user"
#: Developer role: may create/delete workspaces and manage their WB tokens.
ROLE_DEV: str = "dev"


class User(Base):
    """A platform user / seller account.

    Attributes:
        id: UUIDv7 primary key (time-ordered, non-enumerable).
        email: Unique login identifier.
        hashed_password: bcrypt digest of the account password.
        is_active: Soft-disable flag; inactive users cannot authenticate.
        role: Coarse authorization role (:data:`ROLE_USER` default;
            :data:`ROLE_DEV` unlocks workspace administration). Read/write
            separation inside an organisation is a deliberate non-goal — see
            register P1.4 — so this column plus the membership role is the
            whole authorization model on purpose.
        email_confirmed_at: When the address was proven, or ``NULL`` if never.
            Nullable rather than a boolean so the *when* survives: "this
            account confirmed before we required it" and "confirmed last
            Tuesday" are different facts during an incident.
        created_at: Server-assigned creation timestamp (UTC).
        refresh_tokens: All refresh-token rows ever issued to this user.
    """

    __tablename__ = "users"
    __table_args__ = {"schema": _SCHEMA}

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid7)
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True)
    hashed_password: Mapped[str] = mapped_column(String(128))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    role: Mapped[str] = mapped_column(String(32), default=ROLE_USER, nullable=False)
    email_confirmed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
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


class VerificationPurpose(enum.StrEnum):
    """What a verification code proves.

    Two purposes, one mechanism, and they are kept apart by this column rather
    than by two tables. A code issued to confirm an address must never be
    accepted to reset a password: the two are requested under different
    circumstances and one of them changes a credential.
    """

    EMAIL_CONFIRMATION = "email_confirmation"
    # S105 reads this as a hardcoded credential. It is the opposite: the name of
    # the purpose a code is issued FOR, stored in a column beside a hash — the
    # credential itself never reaches this table.
    PASSWORD_RESET = "password_reset"  # noqa: S105


class VerificationCode(Base):
    """A short-lived, single-use code proving control of an email address.

    Stored **hashed**, like every other credential in this schema. The code
    itself exists only in the message that was sent; a database dump, a backup
    or a stray `SELECT *` never yields something that can be redeemed. This is
    the same reasoning as ``activation_codes.code_hash`` and
    ``refresh_tokens.token_hash``, applied to a credential that is short-lived
    rather than long-lived.

    **Six digits is deliberate, and so is what makes it safe.** A person retypes
    a code from their mail client, so it has to be short; short means low
    entropy — a million possibilities — which is fine only because guessing is
    bounded on three axes at once: the row expires in minutes, ``attempts`` is
    capped and the row dies when the cap is hit, and the endpoints sit behind
    the per-IP throttle. Remove any one of those and the length becomes a
    problem.

    Attributes:
        id: UUIDv7 primary key.
        user_id: The account this code was issued to.
        purpose: What it proves — see :class:`VerificationPurpose`.
        code_hash: SHA-256 of the code. Never the code.
        expires_at: When it stops being redeemable.
        consumed_at: When it was redeemed; ``NULL`` while live. Kept rather than
            deleted so "this code was already used" is answerable — a replay is
            worth being able to see.
        attempts: Wrong guesses so far, against the cap.
        created_at: Issue time (UTC).
    """

    __tablename__ = "verification_codes"
    __table_args__ = (
        # The lookup every redemption makes: this account's live code for this
        # purpose. Partial on unconsumed rows would be tighter, but the table is
        # tiny and short-lived by construction.
        Index("ix_verification_codes_user_purpose", "user_id", "purpose"),
        {"schema": _SCHEMA},
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid7)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey(f"{_SCHEMA}.users.id", ondelete="CASCADE"), nullable=False
    )
    purpose: Mapped[str] = mapped_column(String(32), nullable=False)
    code_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
