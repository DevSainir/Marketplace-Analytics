"""sku_comment: per-SKU free-text notes

Revision ID: d5f2a8c1e0b4
Revises: c4e8f1a9d3b2
Create Date: 2026-07-15

Comments are global (shared by every account): one row per SKU that has a
note, keyed by ``nm_id``. Clearing a note deletes the row. ``updated_at``
records the last edit.
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision = "d5f2a8c1e0b4"
down_revision = "c4e8f1a9d3b2"
branch_labels = None
depends_on = None

_SCHEMA = "monitoring"


def upgrade() -> None:
    """Create the ``sku_comment`` table."""
    op.create_table(
        "sku_comment",
        sa.Column("nm_id", sa.BigInteger(), primary_key=True),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        schema=_SCHEMA,
    )


def downgrade() -> None:
    """Drop the ``sku_comment`` table."""
    op.drop_table("sku_comment", schema=_SCHEMA)
