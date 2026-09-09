"""The tenancy root: an organisation and who belongs to it.

An **organisation is a customer company**, and it is the level tenancy is
enforced at. It exists because a workspace is not a company: one seller runs
several WB accounts, each a workspace of its own, and every question that
matters commercially — who paid, who may add a workspace, who may read the
P&L — is answered about the company, never about one of its accounts.

Below it sit two things it owns: its **workspaces** (``workspaces.workspaces``
carries the foreign key, since a workspace cannot exist without a tenant) and
its **members**.

Two invariants are enforced by partial unique indexes rather than by
application code, because both are the kind that is cheap to violate under
concurrency and expensive to discover afterwards:

* **At most one primary organisation.** :attr:`Organization.is_primary` marks
  *ours*, and it is what unlocks the internal-only surfaces. A second row
  labs.
* **At most one owner per organisation.** Two owners is not a richer model, it
  is an unresolvable argument about who may remove whom.
"""

from __future__ import annotations

import enum
import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    String,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.core.database import Base
from src.core.ids import uuid7

#: Every table in this module lives in the ``organizations`` logical schema.
_SCHEMA: str = "organizations"


class MemberRole(enum.StrEnum):
    """What a member may do inside their organisation.

    Deliberately only two. The platform-wide ``dev`` role is NOT here — it
    lives on ``auth.users.role`` because it is a property of the person, not of
    a membership, and a dev sees everything regardless of which organisation
    they happen to belong to. A registered user with no membership row at all
    is the fourth role, ``user``, and is represented by the absence of a row
    rather than by a value here: "belongs to nothing" is not a kind of
    membership.
    """

    #: Bought the subscription. May create and delete workspaces, invite and
    #: remove managers, and rename the organisation.
    OWNER = "owner"
    #: Invited by the owner. Reaches the modules the owner granted, at the
    #: level the owner set; no control over workspaces, members or billing.
    MANAGER = "manager"


class AccessLevel(enum.StrEnum):
    """How much a manager may do in the modules they can reach.

    One level per membership rather than one per module: an owner deciding
    "this person is here to look, not to touch" is making a single judgement
    about a person, and splitting it per module produced a matrix nobody could
    read and few would ever use unevenly.

    The owner has no level of their own — an owner writes everywhere by
    definition, and giving them a value here would create a representable
    state ("read-only owner") that nothing means to support.
    """

    #: May change things in every module they can reach.
    READ_WRITE = "read_write"
    #: May look, and nothing more. Refused at the same guard that the expired
    #: subscription is refused at, so a route never has to check two things.
    READ_ONLY = "read_only"


class ModuleKey(enum.StrEnum):
    """The product surfaces a manager can be granted or denied.

    Deliberately coarser than the navigation. «Сравнение SKU» is not here because it
    renders monitoring's own data: a manager who may not see the monitoring
    tables must not see the same numbers drawn as lines, and two switches that
    must always agree are a bug waiting for someone to set them apart.
    """

    #: Мониторинг, and «Сравнение SKU» with it.
    MONITORING = "monitoring"
    #: P&L — the profit-and-loss statement built from WB's settlement detail.
    FINREPORTS = "finreports"
    #: A/Б-тесты.
    AB_TESTS = "ab_tests"


#: Everything there is to grant. The default for a new manager and the value
#: every pre-existing membership was backfilled with, so nobody's access
#: narrowed on the deploy that introduced the column.
ALL_MODULES: tuple[str, ...] = tuple(m.value for m in ModuleKey)


class Organization(Base):
    """A customer company — the unit of tenancy, billing and feature access.

    Attributes:
        id: UUIDv7 primary key (time-ordered, non-enumerable).
        name: Display name. **Nullable, and filled with the owner's email at
            activation**, so nothing has to be typed on the one screen where a
            new customer is already entering a code. It is a real column rather
            than a derived value because identity must survive both an email
            change and an ownership transfer — anchoring the name to whoever
            currently owns the row would rename the company when its owner
            leaves it. The owner may edit it afterwards.
        is_primary: ``True`` for OUR organisation, which unlocks the surfaces
            labs). Exactly one row may carry it; see the partial index below.
        created_at: Server-assigned creation timestamp (UTC).
        members: Everyone who belongs to this organisation.
        subscription: The one subscription row governing its access.
    """

    __tablename__ = "organizations"
    __table_args__ = (
        # "At most one primary organisation", as a database fact. A partial
        # unique index over a constant is the standard way to say "only one row
        # may have this flag" in PostgreSQL, and it holds under concurrency
        # where an application-level check does not.
        Index(
            "uq_organizations_single_primary",
            "is_primary",
            unique=True,
            postgresql_where=text("is_primary"),
        ),
        {"schema": _SCHEMA},
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid7)
    name: Mapped[str | None] = mapped_column(String(256), nullable=True)
    is_primary: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    members: Mapped[list[Membership]] = relationship(
        back_populates="organization",
        cascade="all, delete-orphan",
    )


class Membership(Base):
    """One person's place in one organisation.

    ``user_id`` is UNIQUE, which is the model's central simplification: **a user
    belongs to at most one organisation.** That is what makes "the caller's
    organisation" a single unambiguous answer on every request, with no
    organisation switcher, no per-request scope header to validate, and no way
    for a manager to be looking at company A while acting on company B. If
    multi-org membership is ever wanted, this constraint is the one thing that
    has to change, and the compiler will find every caller that assumed it.

    Attributes:
        id: UUIDv7 primary key.
        organization_id: The organisation joined (FK, cascade delete).
        user_id: The member (FK to ``auth.users``, cascade delete, UNIQUE).
        role: :class:`MemberRole` — ``owner`` or ``manager``.
        invited_by_user_id: Who invited them, for an audit trail that survives
            the invitation row being cleaned up. ``NULL`` for an owner, who was
            invited by nobody, and for a member whose inviter was deleted.
        joined_at: When the code was redeemed or the invitation accepted.
    """

    __tablename__ = "memberships"
    __table_args__ = (
        # "At most one owner per organisation", again as a database fact.
        Index(
            "uq_memberships_single_owner",
            "organization_id",
            unique=True,
            postgresql_where=text("role = 'owner'"),
        ),
        {"schema": _SCHEMA},
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid7)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey(f"{_SCHEMA}.organizations.id", ondelete="CASCADE"), index=True
    )
    #: UNIQUE — one organisation per user (see the class docstring).
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("auth.users.id", ondelete="CASCADE"), unique=True, index=True
    )
    role: Mapped[str] = mapped_column(String(16), nullable=False)
    #: Meaningful for a manager only; an owner writes everywhere regardless.
    access_level: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default=AccessLevel.READ_WRITE.value
    )
    #: The :class:`ModuleKey` values this member may reach, as a JSON array.
    #: A list rather than a column per module because the set is a product
    #: decision that will change again, and a new surface should be a value to
    #: write rather than a migration to run. The server default grants
    #: everything, which is what backfills existing managers untouched.
    modules: Mapped[list[str]] = mapped_column(
        JSONB,
        nullable=False,
        server_default=text("""'["monitoring", "finreports", "ab_tests"]'::jsonb"""),
    )
    invited_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("auth.users.id", ondelete="SET NULL"), nullable=True
    )
    joined_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    organization: Mapped[Organization] = relationship(back_populates="members")
