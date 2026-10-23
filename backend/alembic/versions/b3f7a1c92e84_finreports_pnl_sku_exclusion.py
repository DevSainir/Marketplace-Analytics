"""finreports: per-SKU "Leave out of the total" marks

Adds ``finreports.pnl_sku_exclusion`` — one row per SKU the seller marks out of
the P&L dashboard's total, keyed ``(workspace_id, nm_id)`` so the mark is
shared across a workspace's users and scoped to it. The presence of a row is the
mark; clearing it deletes the row. It shapes only the dashboard's summed KPIs,
never a settlement fact or the reconciled per-SKU rows.

Revision ID: b3f7a1c92e84
Revises: be09d50ae5ff
Create Date: 2026-07-31 10:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b3f7a1c92e84"
down_revision: str | None = "be09d50ae5ff"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_SCHEMA = "finreports"


def upgrade() -> None:
    """Apply the schema changes for this revision."""
    op.create_table(
        "pnl_sku_exclusion",
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("nm_id", sa.BigInteger(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("workspace_id", "nm_id", name=op.f("pk_pnl_sku_exclusion")),
        schema=_SCHEMA,
    )


def downgrade() -> None:
    """Revert the schema changes for this revision."""
    op.drop_table("pnl_sku_exclusion", schema=_SCHEMA)
