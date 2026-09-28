"""Monitoring: the currency WB states for a price snapshot.

The heatmap labelled every money figure with the кабинет's settlement currency,
which is wrong for prices: «Демо» settles in KGS, but the prices API answers
``currencyIsoCode4217: RUB`` on every card (checked live 2026-09-28), and the
settlement's own per-unit price runs ~1.1x ours before 20.08 — a conversion,
not a coincidence. So the snapshot keeps the currency WB states, and a screen
labels a price with the price's own currency.

Existing rows get ``""`` (unknown); the next price harvest fills today's.

Revision ID: f5a2d8c61e07
Revises: e3b8a1f07c52
Create Date: 2026-09-28
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision: str = "f5a2d8c61e07"
down_revision: str | None = "e3b8a1f07c52"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    """Add the column, empty for every existing snapshot."""
    op.add_column(
        "price_snapshot",
        sa.Column("currency", sa.String(8), server_default="", nullable=False),
        schema="monitoring",
    )


def downgrade() -> None:
    """Drop the column."""
    op.drop_column("price_snapshot", "currency", schema="monitoring")
