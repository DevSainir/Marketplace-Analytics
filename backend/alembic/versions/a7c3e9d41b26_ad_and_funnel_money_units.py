"""Monitoring: the currency of ad spend, and the funnel's own money.

Two facts WB states and we used to drop, both for the same reason: a workspace
that settles in KGS holds money in more than one currency (verified
2026-09-29 on every workspace).

* ``advertising_stat_daily.currency`` — fullstats names each campaign's
  currency, and it is the campaign's own: RUB for campaigns created before WB
  moved the ad account to KGS on 2026-08-20, KGS after. Spend without it is a
  number without a unit.
* ``sales_funnel_daily.order_sum/buyout_sum/cancel_sum`` and ``currency`` —
  the funnel answers in the SETTLEMENT currency, already converted by WB at the
  Bank of Russia rate of the order day. It is the one source of order value in
  KGS that we do not have to convert ourselves.

No value is invented here: existing rows get ``""`` and NULL (unknown), and
the harvest and the backfill fill them from WB.

Revision ID: a7c3e9d41b26
Revises: f5a2d8c61e07
Create Date: 2026-09-29
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision: str = "a7c3e9d41b26"
down_revision: str | None = "f5a2d8c61e07"
branch_labels: str | None = None
depends_on: str | None = None

_FUNNEL_SUMS = ("order_sum", "buyout_sum", "cancel_sum")


def upgrade() -> None:
    """Add the columns, unknown for every existing row."""
    op.add_column(
        "advertising_stat_daily",
        sa.Column("currency", sa.String(8), server_default="", nullable=False),
        schema="monitoring",
    )
    for column in _FUNNEL_SUMS:
        op.add_column(
            "sales_funnel_daily",
            sa.Column(column, sa.Numeric(14, 2), nullable=True),
            schema="monitoring",
        )
    op.add_column(
        "sales_funnel_daily",
        sa.Column("currency", sa.String(8), server_default="", nullable=False),
        schema="monitoring",
    )


def downgrade() -> None:
    """Drop the columns."""
    op.drop_column("sales_funnel_daily", "currency", schema="monitoring")
    for column in reversed(_FUNNEL_SUMS):
        op.drop_column("sales_funnel_daily", column, schema="monitoring")
    op.drop_column("advertising_stat_daily", "currency", schema="monitoring")
