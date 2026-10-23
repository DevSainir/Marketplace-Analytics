"""pinned_sku: global "Pin" flags on SKUs

Revision ID: a1d7e5c2b9f8
Revises: b8c4d2e6f1a3
Create Date: 2026-07-14

Pins are global (shared by every account): one row per pinned ``nm_id``,
presence == pinned. ``created_at`` preserves the pin order for display.
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision = "a1d7e5c2b9f8"
down_revision = "b8c4d2e6f1a3"
branch_labels = None
depends_on = None

_SCHEMA = "monitoring"


def upgrade() -> None:
    """Create the ``pinned_sku`` table."""
    op.create_table(
        "pinned_sku",
        sa.Column("nm_id", sa.BigInteger(), primary_key=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        schema=_SCHEMA,
    )


def downgrade() -> None:
    """Drop the ``pinned_sku`` table."""
    op.drop_table("pinned_sku", schema=_SCHEMA)
