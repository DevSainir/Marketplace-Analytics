"""Ordered item lines from the WB Statistics API.

`monitoring.sales_funnel_daily` only goes back as far as the day this service
started harvesting a кабинет — 17.07.2025 for the oldest one, against
settlements from 2024. `supplier/orders` answers from any `dateFrom`, so the
whole ordering history is reachable; this is where it lands.

Keyed by `srid`, WB's order-line id: the feed paginates on `lastChangeDate` with
an inclusive bound, so consecutive pages overlap and the key is what makes a
re-read idempotent.

Revision ID: c9e4a1f37b52
Revises: b3d7f18c05ae
Create Date: 2026-09-17
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision: str = "c9e4a1f37b52"
down_revision: str | None = "b3d7f18c05ae"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    """Create the table, its read index and the truncate guard."""
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
    # Every read is «this кабинет's SKUs over a window», and the кабинет arrives
    # as a semijoin on `product_card` — so the index that matters is (nm_id, day).
    op.create_index(
        "ix_order_record_nm_id_order_date",
        "order_record",
        ["nm_id", "order_date"],
        schema="monitoring",
    )
    # Attached per TABLE, so a new one starts unguarded — and this one holds
    # history WB will not serve twice as cheaply. `test_migrations.py` fails on
    # a table in this schema without it.
    op.execute(
        "CREATE TRIGGER guard_against_truncate "
        "BEFORE TRUNCATE ON monitoring.order_record "
        "FOR EACH STATEMENT EXECUTE FUNCTION organizations.guard_against_truncate()"
    )


def downgrade() -> None:
    """Drop the table. The history is re-walkable, at ~1 request/minute."""
    op.drop_index(
        "ix_order_record_nm_id_order_date", table_name="order_record", schema="monitoring"
    )
    op.drop_table("order_record", schema="monitoring")
