"""drop pinned_keyword: the live-position feature is gone

Revision ID: b1e7c9d4a2f6
Revises: 865b8a783a85
Create Date: 2026-08-27

The "Search position" probe and the pinned phrases it re-checked were removed
on 2026-08-27. The table's only writer was ``monitoring.refresh_pinned_positions``
and its only reader the pinned-keyword routes; both went with it, so the rows
have nothing left to mean.

Nothing is archived first, deliberately. Every column here is a SAMPLE of a
ranking that WB recomputes within the hour, for one delivery region and one
loyalty tier — it cannot be recomputed for a past day and there is nothing to
reconcile it against, so a preserved row would be a number no one could ever
verify or use. ``docs/monitoring/LIVE_POSITION.md`` records what the feature
measured and why it was removed.

The downgrade recreates the table empty, matching ``a7c31f5b90d2``. That is the
honest inverse: the schema comes back, the samples do not, and re-pinning is one
click per phrase.
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision = "b1e7c9d4a2f6"
down_revision = "865b8a783a85"
branch_labels = None
depends_on = None

_SCHEMA = "monitoring"
_TABLE = "pinned_keyword"


def upgrade() -> None:
    """Drop the pinned-phrase table."""
    op.drop_table(_TABLE, schema=_SCHEMA)


def downgrade() -> None:
    """Recreate the pinned-phrase table, empty (see ``a7c31f5b90d2``)."""
    op.create_table(
        _TABLE,
        sa.Column("nm_id", sa.BigInteger(), nullable=False),
        sa.Column("keyword", sa.String(length=100), nullable=False),
        sa.Column("normalized_query", sa.String(length=100), server_default="", nullable=False),
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
