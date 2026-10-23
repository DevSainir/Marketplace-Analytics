"""Drop the ordered-lines table: the feed behind it is not used.

`supplier/orders` was added to give "Orders" a history deeper than the analytics
funnel's. Measured against the funnel on the same days, it reports 10-15 % fewer
orders — stable, not explained by cancellations, timezone, FBS/FBO, baskets or
attribution — so the two cannot be mixed in one line, and the funnel is the one
every other screen already shows. Its archive also turned out to be ~180 days,
shallower than the funnel's 365, so it was not the deep history it looked like.

The table is dropped rather than left to fill: nothing reads it, and a table
nobody reads is a table nobody notices is wrong.

Revision ID: d4f6a2b91c73
Revises: c9e4a1f37b52
Create Date: 2026-09-22
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision: str = "d4f6a2b91c73"
down_revision: str | None = "c9e4a1f37b52"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    """Drop the table and its index."""
    op.drop_index(
        "ix_order_record_nm_id_order_date", table_name="order_record", schema="monitoring"
    )
    op.drop_table("order_record", schema="monitoring")


def downgrade() -> None:
    """Recreate it empty — the walk that filled it is gone with the feed."""
    op.create_table(
        "order_record",
        sa.Column("srid", sa.String(length=128), nullable=False),
        sa.Column("nm_id", sa.BigInteger(), nullable=False),
        sa.Column("order_date", sa.Date(), nullable=False),
        sa.Column("is_cancel", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("price_with_disc", sa.Numeric(12, 2), nullable=False, server_default="0"),
        sa.Column("finished_price", sa.Numeric(12, 2), nullable=False, server_default="0"),
        sa.Column("last_change_date", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("srid", name="pk_order_record"),
        schema="monitoring",
    )
    op.create_index(
        "ix_order_record_nm_id_order_date",
        "order_record",
        ["nm_id", "order_date"],
        schema="monitoring",
    )
