"""Workspaces: bring "Ad clusters" back, for NEVA only.

The cluster block on the SKU page was hidden for everyone on 2026-09-09. It
comes back as a per-workspace switch, ``search_clusters_enabled``, off by
default, and this revision turns it on for the one workspace that asked: NEVA.

Matched by name because that is the only handle a migration shares with every
environment; names are unique platform-wide. Both spellings are accepted, the
Latin one the code has always used and the Cyrillic one the team says.
Anywhere NEVA does not exist (a dev box, CI) the UPDATE touches nothing, and
every workspace keeps the block hidden.

Revision ID: b5d2e8f41c93
Revises: e4b8c1f07a2d
Create Date: 2026-09-26
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision: str = "b5d2e8f41c93"
down_revision: str | None = "e4b8c1f07a2d"
branch_labels: str | None = None
depends_on: str | None = None

#: The workspace the block is shown to, compared upper-cased.
_ENABLED_FOR = "NEVA"


def upgrade() -> None:
    """Add the switch, off everywhere, then turn it on for NEVA."""
    op.add_column(
        "workspaces",
        sa.Column(
            "search_clusters_enabled",
            sa.Boolean(),
            server_default=sa.false(),
            nullable=False,
        ),
        schema="workspaces",
    )
    op.execute(
        sa.text(
            "UPDATE workspaces.workspaces SET search_clusters_enabled = true "
            "WHERE upper(btrim(name)) = :name"
        ).bindparams(name=_ENABLED_FOR)
    )


def downgrade() -> None:
    """Drop the switch; the block goes back to hidden for everyone."""
    op.drop_column("workspaces", "search_clusters_enabled", schema="workspaces")
