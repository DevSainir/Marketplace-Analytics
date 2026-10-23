"""sales: add per-item sale/return records (WB Statistics API)

Adds ``monitoring.sale_record`` — one row per item operation (``S…`` buyout /
``R…`` return), dated by the SALE date. This is the sale-date attribution the
manager's "Buyouts" sum expects; the funnel's ``buyoutCount`` (order-date cohort)
stays but no longer drives the buyout metrics.

Revision ID: e7a3b9c1d2f4
Revises: d5f1a2c3b4e6
Create Date: 2026-07-13 11:00:00.000000

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "e7a3b9c1d2f4"
down_revision: str | None = "d5f1a2c3b4e6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_SCHEMA = "monitoring"


def upgrade() -> None:
    """Create the per-item sale/return record table."""
    op.create_table(
        "sale_record",
        sa.Column("sale_id", sa.String(length=64), primary_key=True),
        sa.Column("srid", sa.String(length=64), nullable=False, server_default=""),
        sa.Column("nm_id", sa.BigInteger(), nullable=False),
        sa.Column("sale_date", sa.Date(), nullable=False),
        sa.Column("is_return", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("finished_price", sa.Numeric(12, 2), nullable=False, server_default="0"),
        sa.Column("price_with_disc", sa.Numeric(12, 2), nullable=False, server_default="0"),
        sa.Column("for_pay", sa.Numeric(12, 2), nullable=False, server_default="0"),
        sa.Column("last_change_date", sa.DateTime(), nullable=False),
        schema=_SCHEMA,
    )
    op.create_index(
        "ix_sale_record_nm_id_sale_date",
        "sale_record",
        ["nm_id", "sale_date"],
        schema=_SCHEMA,
    )


def downgrade() -> None:
    """Drop the per-item sale/return record table."""
    op.drop_index("ix_sale_record_nm_id_sale_date", table_name="sale_record", schema=_SCHEMA)
    op.drop_table("sale_record", schema=_SCHEMA)
