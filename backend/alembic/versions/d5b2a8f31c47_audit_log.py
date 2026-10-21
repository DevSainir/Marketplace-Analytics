"""organizations: an append-only audit log of security-relevant actions

Revision ID: d5b2a8f31c47
Revises: c4a91f6b7d20
Create Date: 2026-08-30

Attribution columns say who owns a row now; they
cannot say what happened last Tuesday, because a compromised manager who
deletes a workspace or removes a member destroys the attribution in the same
action you would be investigating.

**No foreign keys on ``actor_user_id`` or ``organization_id``, on purpose.**
Every other ``*_user_id`` in this schema is ``ON DELETE SET NULL``, which is
correct for a row describing a thing and destructive for a row describing an
event: deleting the account would blank the actor on every record of what that
account did — exactly the cleanup an attacker performs last. These are plain
values that outlive their subjects.

Enforcing append-only, and how far it actually goes
---------------------------------------------------
Two layers, and the honest limits of each are worth stating here rather than
being discovered during an incident.

1. **A trigger** refuses ``UPDATE`` and ``DELETE`` on this table for everyone,
   including the owner and including our own code. This is the layer that
   works *today*, because this deployment runs migrations and the application
   as the same PostgreSQL role — so a ``REVOKE`` against that role would be
   trivially re-granted by the thing it was meant to restrain.

2. **A ``REVOKE``** of ``UPDATE``, ``DELETE`` and ``TRUNCATE`` from ``PUBLIC``,
   which costs nothing now and is what carries the guarantee once the
   application gets a role of its own (P2.4). Until then it is documentation
   with a compiler.

Neither survives a determined superuser: the table owner can
``ALTER TABLE … DISABLE TRIGGER USER`` or drop the trigger outright. That is
not a flaw to be engineered around here — it is the reason P2.4 (least
privilege, a separate application role) is the item that finishes this one.
What both layers do achieve is that no ordinary bug, no ORM flush, and no code
path short of deliberate DDL can rewrite history.

``TRUNCATE`` deserves its own mention: it is neither ``DELETE`` nor ``UPDATE``,
so a trigger on those two does not see it. It is covered by the statement-level
trigger below and by the ``REVOKE``.
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "d5b2a8f31c47"
down_revision = "c4a91f6b7d20"
branch_labels = None
depends_on = None

_SCHEMA = "organizations"
_TABLE = "audit_log"
_QUALIFIED = f"{_SCHEMA}.{_TABLE}"

#: Raises rather than silently ignoring the write. A trigger that returned NULL
#: would make the UPDATE a no-op, and a caller that believes it edited a row is
#: worse off than one that got an error.
_GUARD_FUNCTION = f"""
CREATE OR REPLACE FUNCTION {_SCHEMA}.audit_log_is_append_only()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    RAISE EXCEPTION
        'organizations.audit_log is append-only; % is not permitted', TG_OP
        USING ERRCODE = 'insufficient_privilege';
END;
$$;
"""


def upgrade() -> None:
    """Create the audit log and make it append-only."""
    op.create_table(
        _TABLE,
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column(
            "occurred_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("event", sa.String(length=64), nullable=False),
        # Deliberately no ForeignKey — see the module docstring.
        sa.Column("actor_user_id", sa.Uuid(), nullable=True),
        sa.Column("actor_email", sa.String(length=320), nullable=True),
        sa.Column("organization_id", sa.Uuid(), nullable=True),
        sa.Column("target_type", sa.String(length=64), nullable=True),
        sa.Column("target_id", sa.String(length=128), nullable=True),
        sa.Column("ip_address", sa.String(length=45), nullable=True),
        sa.Column("user_agent", sa.String(length=256), nullable=True),
        sa.Column("metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        schema=_SCHEMA,
    )
    op.create_index(
        "ix_audit_log_org_time",
        _TABLE,
        ["organization_id", "occurred_at"],
        schema=_SCHEMA,
    )
    op.create_index(
        "ix_audit_log_actor_time",
        _TABLE,
        ["actor_user_id", "occurred_at"],
        schema=_SCHEMA,
    )

    op.execute(_GUARD_FUNCTION)
    op.execute(
        f"CREATE TRIGGER audit_log_no_rewrite "
        f"BEFORE UPDATE OR DELETE ON {_QUALIFIED} "
        f"FOR EACH ROW EXECUTE FUNCTION {_SCHEMA}.audit_log_is_append_only()"
    )
    # TRUNCATE fires no row-level trigger, so it needs a statement-level one.
    op.execute(
        f"CREATE TRIGGER audit_log_no_truncate "
        f"BEFORE TRUNCATE ON {_QUALIFIED} "
        f"FOR EACH STATEMENT EXECUTE FUNCTION {_SCHEMA}.audit_log_is_append_only()"
    )
    op.execute(f"REVOKE UPDATE, DELETE, TRUNCATE ON {_QUALIFIED} FROM PUBLIC")


def downgrade() -> None:
    """Drop the audit log, its guards and the shared guard function."""
    op.execute(f"DROP TRIGGER IF EXISTS audit_log_no_truncate ON {_QUALIFIED}")
    op.execute(f"DROP TRIGGER IF EXISTS audit_log_no_rewrite ON {_QUALIFIED}")
    op.drop_index("ix_audit_log_actor_time", table_name=_TABLE, schema=_SCHEMA)
    op.drop_index("ix_audit_log_org_time", table_name=_TABLE, schema=_SCHEMA)
    op.drop_table(_TABLE, schema=_SCHEMA)
    op.execute(f"DROP FUNCTION IF EXISTS {_SCHEMA}.audit_log_is_append_only()")
