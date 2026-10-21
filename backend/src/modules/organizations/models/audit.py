"""The append-only record of security-relevant things people did (P1.3).

Attribution columns answer "who owns this row **now**". They cannot answer
"what happened last Tuesday", and the difference is the whole reason this table
exists: a compromised manager who deletes a workspace, removes a member or
rotates a WB token destroys the ``updated_by_user_id`` in the same action you
would be investigating. The evidence leaves with the row. A role change simply
overwrites the previous value and no one can say what it was.

So this is a separate table, written once and never touched again.

Three properties decide whether it is worth having, and all three are structural
rather than conventional:

**Append-only in the database, not by discipline.** A trigger refuses
``UPDATE``, ``DELETE`` and ``TRUNCATE`` on this table for every caller,
including our own code. A repository that only inserts is a promise; a database
that raises is a fact, and the threat model here explicitly includes an attacker
running our own code.

The guard is attached to the *table definition* below rather than living only in
the migration, and that is not tidiness. The migration builds production;
``Base.metadata.create_all`` builds the integration database and any fresh local
stack. A guard defined in only one of those places protects only one of those
databases, and the one it would have missed is the one the tests run against —
so the property would have been asserted where it held and shipped where it did
not.

**The actor and the tenant are denormalised, deliberately.** No foreign keys.
Every other table here uses ``ON DELETE SET NULL`` for ``*_user_id``, which is
right for a row that describes a thing and catastrophic for a row that describes
an *event*: deleting the account would blank the actor on every record of what
that account did, which is precisely the cleanup an attacker performs last. The
id and the email are stored as plain values and survive the account.

**Never the secret itself.** ``WB_TOKEN_ROTATED`` records that a rotation
happened and by whom. Not the token, before or after. The same goes for
activation codes, invitation codes and passwords — :attr:`AuditEvent` names an
action, and :attr:`AuditLogEntry.metadata_` carries *which fields changed*, not
their sensitive values.

Scope is security-relevant events only. An audit log that also records every
cost-price edit is one nobody reads, and its volume hides the twelve rows that
matter.
"""

from __future__ import annotations

import enum
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DDL, DateTime, Index, String, event, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from src.core.database import Base
from src.core.ids import uuid7

#: Every table in this module lives in the ``organizations`` logical schema.
_SCHEMA: str = "organizations"


class AuditEvent(enum.StrEnum):
    """What happened. A closed set, on purpose.

    Free text would drift into twelve spellings of the same event and make the
    table unqueryable exactly when someone is querying it in a hurry. Adding a
    member here is a deliberate act with a migration-free cost; inventing one at
    a call site is not possible.
    """

    ORG_ACTIVATED = "ORG_ACTIVATED"
    MEMBER_INVITED = "MEMBER_INVITED"
    INVITATION_REVOKED = "INVITATION_REVOKED"
    MEMBER_JOINED = "MEMBER_JOINED"
    MEMBER_REMOVED = "MEMBER_REMOVED"
    MEMBER_ROLE_CHANGED = "MEMBER_ROLE_CHANGED"
    MEMBER_ACCESS_CHANGED = "MEMBER_ACCESS_CHANGED"
    WORKSPACE_CREATED = "WORKSPACE_CREATED"
    WORKSPACE_DELETED = "WORKSPACE_DELETED"
    # S105 reads these two as hardcoded credentials. They are the opposite:
    # the names of events whose entire contract is that the secret is NOT
    # recorded — only that a rotation or a change happened, and by whom.
    WB_TOKEN_ROTATED = "WB_TOKEN_ROTATED"  # noqa: S105
    SESSIONS_REVOKED = "SESSIONS_REVOKED"
    PASSWORD_CHANGED = "PASSWORD_CHANGED"  # noqa: S105
    ACTIVATION_CODE_ISSUED = "ACTIVATION_CODE_ISSUED"
    #: A dev opened, or closed, another company's workspace to a head, read-only.
    WORKSPACE_GUEST_GRANTED = "WORKSPACE_GUEST_GRANTED"
    WORKSPACE_GUEST_REVOKED = "WORKSPACE_GUEST_REVOKED"
    #: A subscription term was moved or removed. Written by a database trigger
    #: on ``organizations.subscriptions``, never by application code, so that a
    #: renewal done at a psql prompt is recorded too (see the subscription model).
    SUBSCRIPTION_CHANGED = "SUBSCRIPTION_CHANGED"


class AuditLogEntry(Base):
    """One thing that happened, recorded so it survives its subject.

    Attributes:
        id: UUIDv7 primary key — sortable by creation, so ``ORDER BY id`` and
            ``ORDER BY occurred_at`` agree without a second index.
        occurred_at: Server time, not client time. An attacker who can choose
            the timestamp can hide in the ordering.
        event: One of :class:`AuditEvent`, stored as its name.
        actor_user_id: Who did it. **No foreign key** — see the module
            docstring. ``NULL`` only for something the system did unattended.
        actor_email: The actor's address as it was at the time, so the record
            still names a person after the account is gone (and after they
            change their address).
        organization_id: The tenant this happened inside, denormalised for the
            same reason. ``NULL`` for events that precede any organisation.
        target_type: What kind of thing it was done to (``"workspace"``,
            ``"membership"``, ``"invitation"``…), as a plain string.
        target_id: Which one, as a plain value rather than a reference.
        ip_address: Where from. Resolved by ``src.core.client_ip``, so it is the
            address nginx wrote and never one the client chose.
        user_agent: What with. Truncated — it is a hint, not evidence.
        metadata_: Before/after for the fields that changed. **Never a secret
            value.** Mapped to the ``metadata`` column; the attribute carries a
            trailing underscore because ``metadata`` is taken by SQLAlchemy's
            declarative base.
    """

    __tablename__ = "audit_log"
    __table_args__ = (
        # The two questions actually asked of this table, in the order they are
        # asked: "what happened in this tenant lately" and "what did this
        # account do". Both are read during an incident, when a sequential scan
        # of a year of events is not an acceptable answer.
        Index("ix_audit_log_org_time", "organization_id", "occurred_at"),
        Index("ix_audit_log_actor_time", "actor_user_id", "occurred_at"),
        {"schema": _SCHEMA},
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid7)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    event: Mapped[str] = mapped_column(String(64), nullable=False)
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    actor_email: Mapped[str | None] = mapped_column(String(320), nullable=True)
    organization_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    target_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    target_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    ip_address: Mapped[str | None] = mapped_column(String(45), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(String(256), nullable=True)
    metadata_: Mapped[dict[str, Any] | None] = mapped_column("metadata", JSONB, nullable=True)


# SQLAlchemy ships no annotation for ``DDL.__init__``; the ignores below are
# that and nothing else, and `warn_unused_ignores` will flag them the day it
# gains one.
#: Raises rather than silently ignoring the write: a trigger returning NULL
#: would turn the UPDATE into a no-op, and a caller that believes it edited a
#: row is worse off than one that got an error.
#:
#: Kept in step with ``alembic/versions/d5b2a8f31c47_audit_log.py``, which
#: issues the same DDL for the migrated path. The two are checked against each
#: other by ``tests/integration/organizations/test_audit_log_is_append_only.py``
#: running on the create_all database and by the migration tier applying the
#: other — a divergence fails one of them.
_GUARD_FUNCTION = DDL(  # type: ignore[no-untyped-call]
    """
    CREATE OR REPLACE FUNCTION organizations.audit_log_is_append_only()
    RETURNS trigger
    LANGUAGE plpgsql
    AS $$
    BEGIN
        RAISE EXCEPTION
            -- The doubled percent is required: SQLAlchemy's DDL construct
            -- runs this string through percent-style substitution, so a single
            -- one is read as a placeholder and raises at create_all time.
            -- Alembic's op.execute does not, which is why the migration spells
            -- the same line with a single percent.
            'organizations.audit_log is append-only; %% is not permitted', TG_OP
            USING ERRCODE = 'insufficient_privilege';
    END;
    $$;
    """
)

_ROW_GUARD = DDL(  # type: ignore[no-untyped-call]
    "CREATE TRIGGER audit_log_no_rewrite "
    "BEFORE UPDATE OR DELETE ON organizations.audit_log "
    "FOR EACH ROW EXECUTE FUNCTION organizations.audit_log_is_append_only()"
)

#: TRUNCATE fires no row-level trigger, so it needs a statement-level one of its
#: own — otherwise the table is emptied without the guard ever running.
_TRUNCATE_GUARD = DDL(  # type: ignore[no-untyped-call]
    "CREATE TRIGGER audit_log_no_truncate "
    "BEFORE TRUNCATE ON organizations.audit_log "
    "FOR EACH STATEMENT EXECUTE FUNCTION organizations.audit_log_is_append_only()"
)

#: Costs nothing while the application shares a role with the migrations, and is
#: what carries the guarantee once it gets one of its own (P2.4).
_REVOKE_REWRITES = DDL(  # type: ignore[no-untyped-call]
    "REVOKE UPDATE, DELETE, TRUNCATE ON organizations.audit_log FROM PUBLIC"
)

for _ddl in (_GUARD_FUNCTION, _ROW_GUARD, _TRUNCATE_GUARD, _REVOKE_REWRITES):
    event.listen(
        AuditLogEntry.__table__,
        "after_create",
        _ddl.execute_if(dialect="postgresql"),
    )


__all__ = ["AuditEvent", "AuditLogEntry"]
