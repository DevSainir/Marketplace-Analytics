"""pinned_keyword: standing phrases whose live position is re-checked on a schedule

Revision ID: a7c31f5b90d2
Revises: e2b9d4c71f30
Create Date: 2026-08-15

The position probe answers only for the moment it runs, so a phrase a seller
cares about had to be retyped every time. A pin makes the question standing: the
scheduled task re-probes every pinned phrase three times a day and writes the
result back onto the pin.

The latest result lives ON the pin rather than in a history table on purpose — a
rank is a sample for one region at one moment and WB serves nothing to reconcile
an older one against, so nothing accumulates. A trend line would be a new
time-series table keyed by ``(nm_id, keyword, date)``, not more columns here.

No workspace column: ``nm_id`` already belongs to exactly one workspace through
``product_card``, which every read joins through.
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision = "a7c31f5b90d2"
down_revision = "e2b9d4c71f30"
branch_labels = None
depends_on = None

_SCHEMA = "monitoring"
_TABLE = "pinned_keyword"


def upgrade() -> None:
    """Create the pinned-phrase table."""
    op.create_table(
        _TABLE,
        sa.Column("nm_id", sa.BigInteger(), nullable=False),
        sa.Column("keyword", sa.String(length=100), nullable=False),
        sa.Column("normalized_query", sa.String(length=100), server_default="", nullable=False),
        # Nullable on purpose: NULL with a timestamp means "checked, not inside
        # the scanned depth", which is not the same answer as "never checked"
        # (last_checked_at IS NULL). Collapsing them would tell a seller their
        # card ranks nowhere when nothing was ever asked.
        sa.Column("last_position", sa.Integer(), nullable=True),
        sa.Column("last_positions_scanned", sa.Integer(), server_default="0", nullable=False),
        sa.Column("last_total_found", sa.Integer(), server_default="0", nullable=False),
        sa.Column("last_truncated", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("last_checked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("nm_id", "keyword", name="pk_pinned_keyword"),
        schema=_SCHEMA,
    )


def downgrade() -> None:
    """Drop the pinned-phrase table."""
    op.drop_table(_TABLE, schema=_SCHEMA)
