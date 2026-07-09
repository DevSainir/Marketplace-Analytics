"""product_card and product_size dimensions

Adds the ``monitoring.product_card`` (nm_id -> vendor_code/title) and
``monitoring.product_size`` (chrt_id -> tech_size/wb_size) dimension tables,
sourced from the WB Content API ``cards/list``. These carry the human-readable
"Артикул продавца" and "Размер вещи" labels the funnel/stock feeds omit; the
size table joins onto ``stock_snapshot`` by ``chrt_id``.

Revision ID: da396076273a
Revises: b7d2e1f4c8a9
Create Date: 2026-07-08 14:01:33.451867

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "da396076273a"
down_revision: str | None = "b7d2e1f4c8a9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create the product_card and product_size dimension tables."""
    op.create_table(
        "product_card",
        sa.Column("nm_id", sa.BigInteger(), nullable=False),
        sa.Column("vendor_code", sa.String(length=256), nullable=False),
        sa.Column("title", sa.String(length=512), nullable=False),
        sa.Column(
            "synced_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.PrimaryKeyConstraint("nm_id", name=op.f("pk_product_card")),
        schema="monitoring",
    )
    op.create_table(
        "product_size",
        sa.Column("chrt_id", sa.BigInteger(), nullable=False),
        sa.Column("nm_id", sa.BigInteger(), nullable=False),
        sa.Column("tech_size", sa.String(length=64), nullable=False),
        sa.Column("wb_size", sa.String(length=64), nullable=False),
        sa.Column(
            "synced_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.PrimaryKeyConstraint("chrt_id", name=op.f("pk_product_size")),
        schema="monitoring",
    )
    op.create_index(
        op.f("ix_monitoring_product_size_nm_id"),
        "product_size",
        ["nm_id"],
        unique=False,
        schema="monitoring",
    )


def downgrade() -> None:
    """Drop the product_size and product_card dimension tables."""
    op.drop_index(
        op.f("ix_monitoring_product_size_nm_id"), table_name="product_size", schema="monitoring"
    )
    op.drop_table("product_size", schema="monitoring")
    op.drop_table("product_card", schema="monitoring")
