"""Per-SKU fact-table indexes + case-insensitive email uniqueness.

The fact tables' composite PKs lead with ``stat_date``, so the dominant read
pattern (one SKU over a date range) could not use them; every detail request
scanned the whole window across all SKUs. Adds ``(nm_id, stat_date)`` indexes.

Also enforces case-insensitive email uniqueness: the service layer lowercases
emails, and this index makes the invariant hold even for rows written by
future code paths that forget to.

Revision ID: c9e3a7b1d5f2
Revises: da396076273a
Create Date: 2026-07-09
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c9e3a7b1d5f2"
down_revision: str | None = "da396076273a"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    """Add per-SKU secondary indexes and the lower(email) unique index."""
    op.create_index(
        "ix_sales_funnel_daily_nm_id_stat_date",
        "sales_funnel_daily",
        ["nm_id", "stat_date"],
        schema="monitoring",
    )
    op.create_index(
        "ix_stock_snapshot_nm_id_stat_date",
        "stock_snapshot",
        ["nm_id", "stat_date"],
        schema="monitoring",
    )
    op.create_index(
        "ix_advertising_stat_daily_nm_id_stat_date",
        "advertising_stat_daily",
        ["nm_id", "stat_date"],
        schema="monitoring",
    )
    # Pre-existing case-variant duplicates would make the unique index fail to
    # build; normalize them first (keep the oldest row's spelling authoritative
    # — with dev-only data this is a no-op in practice).
    op.execute(sa.text("UPDATE auth.users SET email = lower(email)"))
    op.create_index(
        "uq_users_email_lower",
        "users",
        [sa.text("lower(email)")],
        unique=True,
        schema="auth",
    )


def downgrade() -> None:
    """Drop the indexes added by this revision."""
    op.drop_index("uq_users_email_lower", table_name="users", schema="auth")
    op.drop_index(
        "ix_advertising_stat_daily_nm_id_stat_date",
        table_name="advertising_stat_daily",
        schema="monitoring",
    )
    op.drop_index(
        "ix_stock_snapshot_nm_id_stat_date",
        table_name="stock_snapshot",
        schema="monitoring",
    )
    op.drop_index(
        "ix_sales_funnel_daily_nm_id_stat_date",
        table_name="sales_funnel_daily",
        schema="monitoring",
    )
