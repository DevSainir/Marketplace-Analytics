"""prices: add price_snapshot, drop funnel order_sum/buyout_sum

Adds ``monitoring.price_snapshot`` (daily seller/customer price per SKU) and
removes the stored ₽ volumes from ``sales_funnel_daily``: «Заказы, ₽»/«Выкупы, ₽»
are now DERIVED as ``count x seller_price`` from the price snapshot, no longer
taken from or stored for the WB funnel feed.

Revision ID: d5f1a2c3b4e6
Revises: a1c7e2f9b304
Create Date: 2026-07-11 15:00:00.000000

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "d5f1a2c3b4e6"
down_revision: str | None = "a1c7e2f9b304"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_SCHEMA = "monitoring"


def upgrade() -> None:
    """Create ``price_snapshot`` and drop the funnel's stored ₽ volumes."""
    op.create_table(
        "price_snapshot",
        sa.Column("stat_date", sa.Date(), nullable=False),
        sa.Column("nm_id", sa.BigInteger(), nullable=False),
        sa.Column("seller_price", sa.Numeric(precision=12, scale=2), nullable=True),
        sa.Column("customer_price", sa.Numeric(precision=12, scale=2), nullable=True),
        sa.PrimaryKeyConstraint("stat_date", "nm_id"),
        schema=_SCHEMA,
    )
    op.create_index(
        "ix_price_snapshot_nm_id_stat_date",
        "price_snapshot",
        ["nm_id", "stat_date"],
        schema=_SCHEMA,
    )
    op.drop_column("sales_funnel_daily", "order_sum", schema=_SCHEMA)
    op.drop_column("sales_funnel_daily", "buyout_sum", schema=_SCHEMA)


def downgrade() -> None:
    """Restore the funnel ₽ columns and drop ``price_snapshot``."""
    for column in ("order_sum", "buyout_sum"):
        op.add_column(
            "sales_funnel_daily",
            sa.Column(
                column,
                sa.Numeric(precision=14, scale=2),
                nullable=False,
                server_default="0",
            ),
            schema=_SCHEMA,
        )
        op.alter_column("sales_funnel_daily", column, server_default=None, schema=_SCHEMA)
    op.drop_index("ix_price_snapshot_nm_id_stat_date", table_name="price_snapshot", schema=_SCHEMA)
    op.drop_table("price_snapshot", schema=_SCHEMA)
