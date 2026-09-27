"""Workspaces: guest grants — a head reading another company's кабинет.

Adds ``workspaces.workspace_guests``: one row opens one workspace, read-only,
to one account holding the ``head`` platform role. Grants are managed by a dev
through ``/v1/workspaces/guests``; this revision also makes the first one, the
one that was asked for on 2026-09-27: NEVA opened to the owner of the primary
organisation, who becomes a ``head`` on the way.

Both matched the way the NEVA cluster switch was (``b5d2e8f41c93``): NEVA by
name in either script, the owner through the primary flag rather than by
email. Anywhere either is missing — a dev box, CI — nothing is granted and no
role changes.

Revision ID: a8e3d5f19c62
Revises: b5d2e8f41c93
Create Date: 2026-09-27
"""

from __future__ import annotations

import uuid

import sqlalchemy as sa

from alembic import op

revision: str = "a8e3d5f19c62"
down_revision: str | None = "b5d2e8f41c93"
branch_labels: str | None = None
depends_on: str | None = None

#: The кабинет opened, in both scripts, compared upper-cased.
_VIA = ("NEVA", "НЕВА")


def upgrade() -> None:
    """Create the grant table, then open NEVA to the primary owner."""
    op.create_table(
        "workspace_guests",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("granted_by_user_id", sa.Uuid(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.workspaces.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["auth.users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("workspace_id", "user_id", name="uq_workspace_guests_workspace_user"),
        schema="workspaces",
    )
    op.create_index(
        "ix_workspaces_workspace_guests_workspace_id",
        "workspace_guests",
        ["workspace_id"],
        schema="workspaces",
    )
    op.create_index(
        "ix_workspaces_workspace_guests_user_id",
        "workspace_guests",
        ["user_id"],
        schema="workspaces",
    )

    bind = op.get_bind()
    owner_id = bind.execute(
        sa.text(
            "SELECT m.user_id FROM organizations.memberships m "
            "JOIN organizations.organizations o ON o.id = m.organization_id "
            "WHERE o.is_primary AND m.role = 'owner'"
        )
    ).scalar_one_or_none()
    via = bind.execute(
        sa.text(
            "SELECT w.id FROM workspaces.workspaces w "
            "JOIN organizations.organizations o ON o.id = w.organization_id "
            "WHERE upper(btrim(w.name)) IN (:latin, :cyrillic) AND NOT o.is_primary"
        ).bindparams(latin=_VIA[0], cyrillic=_VIA[1])
    ).scalar_one_or_none()
    if owner_id is None or via is None:
        return
    # A dev keeps the wider role; only an ordinary account is promoted.
    bind.execute(
        sa.text("UPDATE auth.users SET role = 'head' WHERE id = :id AND role = 'user'").bindparams(
            id=owner_id
        )
    )
    # v4, not v7: a migration must not import application code (see c4a91f6b7d20).
    bind.execute(
        sa.text(
            "INSERT INTO workspaces.workspace_guests (id, workspace_id, user_id) "
            "VALUES (:id, :ws, :user) ON CONFLICT DO NOTHING"
        ).bindparams(id=uuid.uuid4(), ws=via, user=owner_id)
    )


def downgrade() -> None:
    """Drop every grant, and return every head to an ordinary account."""
    op.drop_index(
        "ix_workspaces_workspace_guests_user_id", table_name="workspace_guests", schema="workspaces"
    )
    op.drop_index(
        "ix_workspaces_workspace_guests_workspace_id",
        table_name="workspace_guests",
        schema="workspaces",
    )
    op.drop_table("workspace_guests", schema="workspaces")
    op.execute(sa.text("UPDATE auth.users SET role = 'user' WHERE role = 'head'"))
