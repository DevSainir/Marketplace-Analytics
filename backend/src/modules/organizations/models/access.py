"""The two ways into an organisation: an activation code, or an invitation.

Registration is open — anyone may create an account — and a bare account can
reach nothing. These two tables are what turn one into a member of a company.

**Activation code → owner.** We are paid outside the system, generate a code,
and hand it over. The customer enters it on ``/profile``; redeeming it creates
their organisation, makes them its owner, and starts a subscription. Single use.

**Invitation → manager.** The owner invites someone into the organisation they
already own. One table serves both shapes the flow takes, because they differ
only in who does the finding:

* *by email* — the person already has an account, and the invitation waits for
  them on their own profile page;
* *by link* — the owner sends a URL, which lands on ``/register`` and attaches
  the membership the moment the account is created.

Both are the same row: ``email`` set means it is also offered in-app, and the
token is what a link carries. That is deliberate — two tables would need the
same expiry, the same revocation and the same single-use rule, kept in step by
hand.

**Secrets are stored as SHA-256, never in plaintext, and never bcrypt.** Both
credentials are 256-bit random strings we generate, so they carry their entropy
already; bcrypt buys nothing against a value that cannot be guessed and costs
~200 ms on a path a user is waiting on. This is the same reasoning as the
refresh-token secrets in :mod:`src.core.security`, and the same trade.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, func, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from src.core.database import Base
from src.core.ids import uuid7

#: Every table in this module lives in the ``organizations`` logical schema.
_SCHEMA: str = "organizations"


class ActivationCode(Base):
    """A single-use code that turns a registered user into an owner.

    A redeemed code is kept, not deleted: ``used_at`` / ``used_by_user_id`` /
    ``organization_id`` are the only record linking a payment we took offline to
    the organisation it created, and "which code made this company?" is a
    question that gets asked months later.

    Attributes:
        id: UUIDv7 primary key.
        code_hash: SHA-256 of the code (UNIQUE — the lookup key at redemption).
        note: Free text for whoever generated it: who paid, how much, when.
            The only place that context exists, since billing is off-system.
        subscription_days: The term this code buys when redeemed. Carried on the
            code rather than read from settings at redemption, so a code sold on
            one price list still delivers what was sold after the default
            changes.
        expires_at: When the code stops being redeemable; ``NULL`` = never.
            Bounded codes matter because a code handed out and not used is a
            standing grant of a paid account sitting in someone's messages.
        max_workspaces: The кабинет cap the subscription starts with;
            ``NULL`` = unlimited. On the code for the same reason as the term:
            what was sold is what gets delivered.
        max_managers: The manager cap, likewise; ``NULL`` = unlimited.
        used_at: When it was redeemed; ``NULL`` while unused.
        used_by_user_id: Who redeemed it (FK, SET NULL if that account goes).
        organization_id: The organisation it created (FK, SET NULL if that
            organisation is deleted).
        created_by_user_id: The dev who generated it.
        created_at: Generation timestamp (UTC).
    """

    __tablename__ = "activation_codes"
    __table_args__ = {"schema": _SCHEMA}

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid7)
    code_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    note: Mapped[str] = mapped_column(String(256), default="", nullable=False)
    subscription_days: Mapped[int] = mapped_column(Integer, nullable=False)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    max_workspaces: Mapped[int | None] = mapped_column(Integer, nullable=True)
    max_managers: Mapped[int | None] = mapped_column(Integer, nullable=True)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    used_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("auth.users.id", ondelete="SET NULL"), nullable=True
    )
    organization_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey(f"{_SCHEMA}.organizations.id", ondelete="SET NULL"), nullable=True
    )
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("auth.users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class Invitation(Base):
    """An owner's offer of manager membership in their organisation.

    Attributes:
        id: UUIDv7 primary key.
        organization_id: The organisation being joined (FK, cascade delete —
            an invitation into a deleted company means nothing).
        email: The address it was addressed to, normalised lowercase, or
            ``NULL`` for a link anyone holding it may use. When set, the
            invitation also appears on that user's own profile page, so an
            existing account never needs the URL at all.
        token_hash: SHA-256 of the link token (UNIQUE).
        role: The membership it grants. Always ``manager`` today; a column
            rather than a constant so granting something else later is a value
            change and not a migration.
        created_by_user_id: The owner who issued it.
        expires_at: When it stops being acceptable. Never ``NULL``: an
            invitation link that works forever is a permanent back door into a
            customer's data, sitting in a chat log.
        accepted_at: When it was LAST accepted; ``NULL`` while unused. It no
            longer means "spent" — an invitation is reusable until it expires.
        accepted_by_user_id: Who accepted most recently (FK, SET NULL if that
            account goes).
        accepted_count: How many people came through this link. The question an
            owner has to be able to ask once one link can admit several, and
            the only way to notice a link that got out.
        revoked_at: When the owner withdrew it; ``NULL`` while live. Revoking
            marks rather than deletes, so "this link stopped working" has an
            answer.
        created_at: Issue timestamp (UTC).
    """

    __tablename__ = "invitations"
    __table_args__ = {"schema": _SCHEMA}

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid7)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey(f"{_SCHEMA}.organizations.id", ondelete="CASCADE"), index=True
    )
    email: Mapped[str | None] = mapped_column(String(320), nullable=True, index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    role: Mapped[str] = mapped_column(String(16), nullable=False)
    #: The access the resulting membership starts with, chosen by the owner on
    #: the invite form and copied across on acceptance. Held here rather than
    #: set afterwards because the alternative is a window — however short — in
    #: which a new manager has more access than the owner intended them to.
    access_level: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default="read_write"
    )
    modules: Mapped[list[str]] = mapped_column(
        JSONB,
        nullable=False,
        server_default=text("""'["monitoring", "finreports", "ab_tests"]'::jsonb"""),
    )
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("auth.users.id", ondelete="SET NULL"), nullable=True
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    accepted_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("auth.users.id", ondelete="SET NULL"), nullable=True
    )
    accepted_count: Mapped[int] = mapped_column(
        Integer, default=0, server_default="0", nullable=False
    )
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
