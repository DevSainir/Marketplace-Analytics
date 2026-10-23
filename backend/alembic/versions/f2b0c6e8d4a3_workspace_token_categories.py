# ruff: noqa: S608 — schema names in the f-string SQL are module constants.

"""workspaces: per-category tokens for the primary workspace

Revision ID: f2b0c6e8d4a3
Revises: e1a9c5d7b3f2
Create Date: 2026-07-16

WB tokens are category-scoped (13 categories). The primary workspace ("Ivanov
Shop") now stores one token per category; every other workspace stores
a single ``unified`` token reused for all categories.

* ``workspaces.workspaces.is_primary`` (default false); the seed workspace is
  marked primary.
* The legacy token kind ``advertising`` is renamed to ``promotion`` to match
  WB's promotion category slug.
"""

from __future__ import annotations

import uuid

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision = "f2b0c6e8d4a3"
down_revision = "e1a9c5d7b3f2"
branch_labels = None
depends_on = None

_WS_SCHEMA = "workspaces"

#: The seeded primary workspace (see the previous migration).
_SEED_WORKSPACE_ID = uuid.UUID("019f657a-a70c-780a-ac98-f010a1916615")


def upgrade() -> None:
    """Add ``is_primary`` (seed = true) and rename ``advertising`` -> ``promotion``."""
    op.add_column(
        "workspaces",
        sa.Column("is_primary", sa.Boolean(), nullable=False, server_default=sa.false()),
        schema=_WS_SCHEMA,
    )
    op.execute(
        sa.text(
            f'UPDATE "{_WS_SCHEMA}".workspaces SET is_primary = true WHERE id = :id'
        ).bindparams(id=_SEED_WORKSPACE_ID)
    )
    op.execute(
        f"UPDATE \"{_WS_SCHEMA}\".workspace_tokens SET kind = 'promotion' "
        "WHERE kind = 'advertising'"
    )


def downgrade() -> None:
    """Revert the kind rename and drop ``is_primary``."""
    op.execute(
        f"UPDATE \"{_WS_SCHEMA}\".workspace_tokens SET kind = 'advertising' "
        "WHERE kind = 'promotion'"
    )
    op.drop_column("workspaces", "is_primary", schema=_WS_SCHEMA)
