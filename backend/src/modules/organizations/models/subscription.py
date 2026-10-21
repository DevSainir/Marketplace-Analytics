"""What an organisation has paid for, and what happens when it lapses.

One row per organisation, created when its activation code is redeemed. Payment
itself happens outside this system — we are handed money and hand back a code —
so this table records the *consequence* of a payment, never the payment.

**Expiry is a short ramp onto a closed door.** Three states, in order:

``active``
    ``now < expires_at``. Everything works.
``grace``
    ``expires_at <= now < expires_at + grace_days``. Everything still works and
    the UI says the subscription has lapsed. This period exists because the
    renewal is a manual bank transfer between two humans in two countries, and
    the failure it prevents — a seller locked out of their own numbers on the
    morning the payment is still clearing — is far worse than a few extra days
    of access.
``expired``
    Past the grace period. **The service closes.** Every tenant-scoped route
    refuses, reads included, and the SPA draws a paywall over the whole app —
    ``/v1/organizations/me`` is left reachable precisely so it has something to
    draw it from, and the header stays usable so nobody is trapped without a
    logout.

    This was a read-only landing until 2026-09-09. The reasoning was that the
    data is the customer's own and withholding it is a hostage position; what
    that missed is that a tenant which keeps its dashboards has no deadline,
    so the state it was meant to be — an uncomfortable prompt to renew — was
    just a cheaper product. Nothing is deleted and nothing is lost: renewing
    restores every row, because expiry gates access and never storage.

    The grace days are what protects a customer who is actually paying. Past
    them, the honest reading is that they are not.

The limits are nullable and ``NULL`` means unlimited, which is what every
organisation gets today. They exist as columns now because retrofitting a quota
onto live tenants is the kind of change that needs a migration, a backfill and a
conversation with every customer at once; a column that is always ``NULL`` costs
nothing and turns that into a single ``UPDATE``.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DDL, DateTime, ForeignKey, Integer, event, func
from sqlalchemy.orm import Mapped, mapped_column

from src.core.database import Base
from src.core.ids import uuid7

#: Every table in this module lives in the ``organizations`` logical schema.
_SCHEMA: str = "organizations"

#: How long a redeemed activation code buys. The base term, in days.
DEFAULT_SUBSCRIPTION_DAYS: int = 30


class Subscription(Base):
    """One organisation's access term.

    Attributes:
        id: UUIDv7 primary key.
        organization_id: The organisation this governs (FK, UNIQUE, cascade
            delete). One row per organisation: a second one would make "is this
            company paid up?" a question with two answers.
        started_at: When the term began (the activation, or the last renewal).
        expires_at: When it ends. The ramp above starts here.
        grace_days: How long full access survives past ``expires_at``, and
            therefore how long there is before the service closes. A column
            rather than a constant so a specific customer can be given more
            without a deploy — the default comes from settings.
        max_workspaces: Cap on the organisation's workspaces; ``NULL`` =
            unlimited.
        max_managers: Cap on managers (the owner is never counted, since an
            organisation cannot exist without one); ``NULL`` = unlimited.
        created_at: Row creation timestamp (UTC).
        updated_at: Last renewal or limit change (UTC).
    """

    __tablename__ = "subscriptions"
    __table_args__ = {"schema": _SCHEMA}

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid7)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey(f"{_SCHEMA}.organizations.id", ondelete="CASCADE"),
        unique=True,
        index=True,
    )
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    grace_days: Mapped[int] = mapped_column(Integer, nullable=False)
    #: NULL = unlimited (see the module docstring).
    max_workspaces: Mapped[int | None] = mapped_column(Integer, nullable=True)
    #: NULL = unlimited.
    max_managers: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


# ---------------------------------------------------------------------------
# The change trail, enforced by the database.
#
# There is no renewal screen: a renewal is done by hand, and until 2026-10-06
# "by hand" meant an `UPDATE` in psql. That moved `expires_at` and nothing else
# — the ORM's `onupdate` never ran, so `updated_at` still said the activation
# day, and no audit row was written — so when a customer's term ran out a week early by
# their own count, the database could not say it had ever been extended.
#
# So the record is a trigger rather than a call in a service: it fires for the
# renewal script, for the ORM, and for the next person at a psql prompt alike.
# A caller that knows who it is says so first with
# `SET LOCAL app.audit_actor = '<email>'`; without it the row is still written,
# with no actor and `source = 'sql'`, which is itself the finding.
#
# INSERT is not recorded: activation already writes ORG_ACTIVATED with the
# redeemer. An UPDATE that changes none of the term's fields writes nothing.
#
# Kept in step with `alembic/versions/b7e4c2a90d15_subscription_change_trail.py`,
# which issues the same DDL for the migrated path; see the audit model for why
# the guard has to live in both places.
# ---------------------------------------------------------------------------
_TRAIL_FUNCTION = DDL(  # type: ignore[no-untyped-call]
    """
    CREATE OR REPLACE FUNCTION organizations.record_subscription_change()
    RETURNS trigger
    LANGUAGE plpgsql
    AS $$
    DECLARE
        actor text := nullif(current_setting('app.audit_actor', true), '');
        after_term jsonb := '{}'::jsonb;
    BEGIN
        IF TG_OP = 'UPDATE' THEN
            IF NEW.expires_at IS NOT DISTINCT FROM OLD.expires_at
               AND NEW.started_at IS NOT DISTINCT FROM OLD.started_at
               AND NEW.grace_days IS NOT DISTINCT FROM OLD.grace_days
               AND NEW.max_workspaces IS NOT DISTINCT FROM OLD.max_workspaces
               AND NEW.max_managers IS NOT DISTINCT FROM OLD.max_managers THEN
                RETURN NEW;
            END IF;
            NEW.updated_at := now();
            after_term := jsonb_build_object(
                'expires_at', NEW.expires_at,
                'grace_days', NEW.grace_days,
                'max_workspaces', NEW.max_workspaces,
                'max_managers', NEW.max_managers
            );
        END IF;

        INSERT INTO organizations.audit_log (
            id, occurred_at, event, actor_email, organization_id,
            target_type, target_id, metadata
        )
        VALUES (
            gen_random_uuid(),
            now(),
            'SUBSCRIPTION_CHANGED',
            actor,
            OLD.organization_id,
            'subscription',
            OLD.id::text,
            after_term || jsonb_build_object(
                'operation', lower(TG_OP),
                'previous_expires_at', OLD.expires_at,
                'previous_grace_days', OLD.grace_days,
                'previous_max_workspaces', OLD.max_workspaces,
                'previous_max_managers', OLD.max_managers,
                'source', CASE WHEN actor IS NULL THEN 'sql' ELSE 'tool' END,
                'db_user', session_user,
                'application_name', current_setting('application_name', true)
            )
        );

        IF TG_OP = 'DELETE' THEN
            RETURN OLD;
        END IF;
        RETURN NEW;
    END;
    $$;
    """
)

_TRAIL_TRIGGER = DDL(  # type: ignore[no-untyped-call]
    "CREATE TRIGGER subscription_change_trail "
    "BEFORE UPDATE OR DELETE ON organizations.subscriptions "
    "FOR EACH ROW EXECUTE FUNCTION organizations.record_subscription_change()"
)

for _ddl in (_TRAIL_FUNCTION, _TRAIL_TRIGGER):
    event.listen(
        Subscription.__table__,
        "after_create",
        _ddl.execute_if(dialect="postgresql"),
    )
