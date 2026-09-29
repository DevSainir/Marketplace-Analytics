"""Carry forward logistics legs on the settlement rollup, for the SKU «Выкуп».

The per-SKU table gains «Выкуп, %» = sold / delivered, the same measure the size
cut already shows, so an article's row equals the footer of its own sizes. The
denominator — Σ ``delivery_amount`` — was never rolled up, and the rollup proves
a day by its row count alone: an existing day would keep its count and read
zero deliveries forever. So the column is added and the rollup emptied, and every
day is rebuilt from the detail on its next read.

Revision ID: b2e6d0a93c14
Revises: a7c3e9d41b26
Create Date: 2026-09-29
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision: str = "b2e6d0a93c14"
down_revision: str | None = "a7c3e9d41b26"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    """Add the column, then drop every rolled-up day so the next read rebuilds it."""
    op.add_column(
        "settlement_daily_rollup",
        sa.Column("delivered_units", sa.Integer(), server_default="0", nullable=False),
        schema="finreports",
    )
    op.execute("DELETE FROM finreports.settlement_daily_rollup")


def downgrade() -> None:
    """Drop the column; the remaining columns stay correct as they are."""
    op.drop_column("settlement_daily_rollup", "delivered_units", schema="finreports")
