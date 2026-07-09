"""funnel: add buyout_sum (buyout revenue)

Adds ``monitoring.sales_funnel_daily.buyout_sum`` — WB returns ``buyoutSum``
(buyout value in rubles) on the sales-funnel history feed, which the ingestion
previously dropped via the raw model's ``extra="ignore"``.

Revision ID: b7d2e1f4c8a9
Revises: a4a8b4e96418
Create Date: 2026-07-08 12:10:00.000000

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b7d2e1f4c8a9"
down_revision: str | None = "a4a8b4e96418"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add the ``buyout_sum`` column with a zero default for existing rows."""
    op.add_column(
        "sales_funnel_daily",
        sa.Column(
            "buyout_sum",
            sa.Numeric(precision=14, scale=2),
            nullable=False,
            server_default="0",
        ),
        schema="monitoring",
    )
    # Drop the server default now that existing rows are backfilled — new rows
    # always supply the value explicitly via the ingestion upsert.
    op.alter_column(
        "sales_funnel_daily",
        "buyout_sum",
        server_default=None,
        schema="monitoring",
    )


def downgrade() -> None:
    """Drop the ``buyout_sum`` column."""
    op.drop_column("sales_funnel_daily", "buyout_sum", schema="monitoring")
