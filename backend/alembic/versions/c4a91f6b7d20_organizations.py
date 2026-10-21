"""organizations: the top-level tenant, its members, subscription and doors in

Revision ID: c4a91f6b7d20
Revises: b1e7c9d4a2f6
Create Date: 2026-08-27

Introduces the level tenancy is actually enforced at. Until now a workspace was
the only tenant-shaped thing in the schema, and it is the wrong shape: one
seller runs several WB accounts, and every commercial question — who paid, who
may add an account, who may read the P&L — is about the company.

Five tables plus one column, and the column is the point: ``workspaces``
gains ``organization_id NOT NULL``, which is what lets every query in the
application scope by tenant instead of trusting a header.

**The backfill.** This runs against a deployment that already has four
workspaces and four users, so the column cannot simply be declared NOT NULL —
existing rows need an owner first. The upgrade therefore goes in three steps:
add the column nullable, adopt whatever is already there into one primary
organisation, then tighten to NOT NULL. On an empty database (CI, a fresh local
stack, the migration-drift test) the middle step finds nothing and does nothing,
and the tighten is trivially satisfied.

Who becomes the owner is a fact about that one deployment, not about the
schema, so it is written here as a constant with a documented fallback rather
than guessed: :data:`_OWNER_EMAIL` if that account exists, otherwise the oldest
account. Everyone else becomes a manager — **including the ``dev`` account**.

That last part is not a formality. The ``dev`` role elevates what a caller may
DO; it does not supply a tenant to do it in, and every data route resolves its
workspace through the caller's organisation. A dev with no membership therefore
cannot open «Мониторинг», «Графики» or «Прибыли и убытки» at all — the platform role
would let them past the role checks and the workspace lookup would then find
nothing of theirs. So the dev joins the primary organisation like everyone else
and keeps seeing every internal feature through their role.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision = "c4a91f6b7d20"
down_revision = "b1e7c9d4a2f6"
branch_labels = None
depends_on = None

_SCHEMA = "organizations"

#: The account that owns the primary organisation on the deployment this
#: migration was written for. Absent anywhere else, in which case the fallback
#: below applies. Not a secret — an email address identifying a colleague.
_OWNER_EMAIL = "owner@example.com"

#: What the adopted organisation is called. The seller-facing name of the
#: company that has been the only tenant so far.
_PRIMARY_NAME = "Демо"

#: The backfilled subscription's term. Long rather than the 30-day default: our
#: own organisation is not a paying customer, and a 30-day term here would drop
#: the whole team to read-only a month after deploy for no reason anyone would
#: connect to this migration.
_PRIMARY_TERM_DAYS = 3650

#: Grace days written onto the backfilled row. Matches the SUBSCRIPTION_GRACE_DAYS
#: default; hard-coded because a migration must not depend on runtime settings
#: that may differ between the machine that runs it and the one that reads it.
_GRACE_DAYS = 3


def _uuid7_like() -> uuid.UUID:
    """A time-ordered UUID for the rows this migration inserts.

    ``src.core.ids.uuid7`` is the application's generator, but a migration must
    not import application code — that code changes underneath old migrations
    and turns a replay into a moving target. The rows here are few and their
    ordering does not matter, so a v4 is sufficient and honest about it.
    """
    return uuid.uuid4()


def upgrade() -> None:
    """Create the organisation tables, then adopt any existing tenant."""
    op.create_table(
        "organizations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=256), nullable=True),
        sa.Column("is_primary", sa.Boolean(), server_default="false", nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id"),
        schema=_SCHEMA,
    )
    # "At most one primary organisation" as a database fact — a second row
    # carrying the flag would silently hand another company our internal-only
    # surfaces (A/B tests, labs).
    op.create_index(
        "uq_organizations_single_primary",
        "organizations",
        ["is_primary"],
        unique=True,
        schema=_SCHEMA,
        postgresql_where=sa.text("is_primary"),
    )

    op.create_table(
        "memberships",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("role", sa.String(length=16), nullable=False),
        sa.Column("invited_by_user_id", sa.Uuid(), nullable=True),
        sa.Column(
            "joined_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"], [f"{_SCHEMA}.organizations.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["user_id"], ["auth.users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["invited_by_user_id"], ["auth.users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        schema=_SCHEMA,
    )
    op.create_index(
        op.f("ix_organizations_memberships_organization_id"),
        "memberships",
        ["organization_id"],
        schema=_SCHEMA,
    )
    # One organisation per user, as a UNIQUE index rather than a named
    # constraint: it is what makes "the caller's organisation" a single
    # unambiguous answer on every request, and the index form is what the model
    # (`unique=True, index=True`) declares — the drift test compares the two.
    op.create_index(
        op.f("ix_organizations_memberships_user_id"),
        "memberships",
        ["user_id"],
        unique=True,
        schema=_SCHEMA,
    )
    # "At most one owner per organisation": two owners is not a richer model,
    # it is an unresolvable argument about who may remove whom.
    op.create_index(
        "uq_memberships_single_owner",
        "memberships",
        ["organization_id"],
        unique=True,
        schema=_SCHEMA,
        postgresql_where=sa.text("role = 'owner'"),
    )

    op.create_table(
        "subscriptions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("grace_days", sa.Integer(), nullable=False),
        # NULL = unlimited. Present from the start so introducing a quota later
        # is an UPDATE rather than a migration against live tenants.
        sa.Column("max_workspaces", sa.Integer(), nullable=True),
        sa.Column("max_managers", sa.Integer(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"], [f"{_SCHEMA}.organizations.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        schema=_SCHEMA,
    )
    # One subscription per organisation, as a UNIQUE index (the form the model
    # declares): a second row would make "is this company paid up?" a question
    # with two answers.
    op.create_index(
        op.f("ix_organizations_subscriptions_organization_id"),
        "subscriptions",
        ["organization_id"],
        unique=True,
        schema=_SCHEMA,
    )

    op.create_table(
        "activation_codes",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("code_hash", sa.String(length=64), nullable=False),
        sa.Column("note", sa.String(length=256), server_default="", nullable=False),
        # The term the code buys, carried on the code rather than read from
        # settings at redemption: a code sold on one price list must still
        # deliver what was sold after the default changes.
        sa.Column("subscription_days", sa.Integer(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("used_by_user_id", sa.Uuid(), nullable=True),
        sa.Column("organization_id", sa.Uuid(), nullable=True),
        sa.Column("created_by_user_id", sa.Uuid(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(["used_by_user_id"], ["auth.users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["auth.users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(
            ["organization_id"], [f"{_SCHEMA}.organizations.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
        schema=_SCHEMA,
    )
    op.create_index(
        op.f("ix_organizations_activation_codes_code_hash"),
        "activation_codes",
        ["code_hash"],
        unique=True,
        schema=_SCHEMA,
    )

    op.create_table(
        "invitations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("email", sa.String(length=320), nullable=True),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("role", sa.String(length=16), nullable=False),
        sa.Column("created_by_user_id", sa.Uuid(), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("accepted_by_user_id", sa.Uuid(), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"], [f"{_SCHEMA}.organizations.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["auth.users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["accepted_by_user_id"], ["auth.users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        schema=_SCHEMA,
    )
    op.create_index(
        op.f("ix_organizations_invitations_organization_id"),
        "invitations",
        ["organization_id"],
        schema=_SCHEMA,
    )
    op.create_index(
        op.f("ix_organizations_invitations_email"),
        "invitations",
        ["email"],
        schema=_SCHEMA,
    )
    op.create_index(
        op.f("ix_organizations_invitations_token_hash"),
        "invitations",
        ["token_hash"],
        unique=True,
        schema=_SCHEMA,
    )

    # --- workspaces.organization_id, in three steps (see the module docstring) ---
    op.add_column(
        "workspaces",
        sa.Column("organization_id", sa.Uuid(), nullable=True),
        schema="workspaces",
    )
    _adopt_existing_tenant()
    op.alter_column("workspaces", "organization_id", nullable=False, schema="workspaces")
    op.create_foreign_key(
        "fk_workspaces_organization_id",
        "workspaces",
        "organizations",
        ["organization_id"],
        ["id"],
        source_schema="workspaces",
        referent_schema=_SCHEMA,
        ondelete="CASCADE",
    )
    op.create_index(
        op.f("ix_workspaces_workspaces_organization_id"),
        "workspaces",
        ["organization_id"],
        schema="workspaces",
    )


def _adopt_existing_tenant() -> None:
    """Put whatever already exists into one primary organisation.

    A no-op on an empty database, which is what makes this migration safe to
    replay in CI and on a fresh local stack: with no workspaces there is no
    tenant to adopt, and the NOT NULL that follows has no rows to fail on.
    """
    connection = op.get_bind()

    workspace_ids = list(
        connection.execute(sa.text("SELECT id FROM workspaces.workspaces")).scalars()
    )
    users = list(
        connection.execute(
            sa.text("SELECT id, email, role FROM auth.users WHERE is_active ORDER BY created_at")
        ).mappings()
    )
    if not workspace_ids and not users:
        return

    now = datetime.now(UTC)
    organization_id = _uuid7_like()
    connection.execute(
        sa.text(
            f"INSERT INTO {_SCHEMA}.organizations (id, name, is_primary, created_at) "  # noqa: S608
            "VALUES (:id, :name, true, :now)"
        ),
        {"id": organization_id, "name": _PRIMARY_NAME, "now": now},
    )
    connection.execute(
        sa.text(
            f"INSERT INTO {_SCHEMA}.subscriptions "  # noqa: S608
            "(id, organization_id, started_at, expires_at, grace_days, created_at, updated_at) "
            "VALUES (:id, :org, :start, :end, :grace, :now, :now)"
        ),
        {
            "id": _uuid7_like(),
            "org": organization_id,
            "start": now,
            "end": now + timedelta(days=_PRIMARY_TERM_DAYS),
            "grace": _GRACE_DAYS,
            "now": now,
        },
    )

    if workspace_ids:
        connection.execute(
            sa.text("UPDATE workspaces.workspaces SET organization_id = :org"),
            {"org": organization_id},
        )

    # Everyone joins, dev included — see the module docstring: a dev without a
    # membership has no tenant to resolve a workspace in, so the role alone
    # would leave our own account unable to open any data page.
    if not users:
        return
    owner = next(
        (row for row in users if row["email"] == _OWNER_EMAIL),
        # Fallback for any deployment that is not the one this was written for:
        # the oldest account is the one most likely to have set the tenant up.
        users[0],
    )
    for row in users:
        connection.execute(
            sa.text(
                f"INSERT INTO {_SCHEMA}.memberships "  # noqa: S608
                "(id, organization_id, user_id, role, joined_at) "
                "VALUES (:id, :org, :user, :role, :now)"
            ),
            {
                "id": _uuid7_like(),
                "org": organization_id,
                "user": row["id"],
                "role": "owner" if row["id"] == owner["id"] else "manager",
                "now": now,
            },
        )


def downgrade() -> None:
    """Drop the organisation tables and the workspace column that points at them.

    The adopted rows are not restored on the way back up — a downgrade followed
    by an upgrade re-adopts from scratch, which lands in the same place because
    the adoption reads the live users and workspaces rather than anything this
    migration stored.
    """
    op.drop_index(
        op.f("ix_workspaces_workspaces_organization_id"), "workspaces", schema="workspaces"
    )
    op.drop_constraint(
        "fk_workspaces_organization_id", "workspaces", schema="workspaces", type_="foreignkey"
    )
    op.drop_column("workspaces", "organization_id", schema="workspaces")

    op.drop_table("invitations", schema=_SCHEMA)
    op.drop_table("activation_codes", schema=_SCHEMA)
    op.drop_table("subscriptions", schema=_SCHEMA)
    op.drop_table("memberships", schema=_SCHEMA)
    op.drop_table("organizations", schema=_SCHEMA)
