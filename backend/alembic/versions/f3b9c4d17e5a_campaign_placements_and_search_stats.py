"""campaigns: bid type + placements; advertising: order_sum + search facts

Three additions backing the monitoring matrix's "Traffic type" /
"Placements" columns:

* ``monitoring.campaigns`` gains the adverts-v2 settings — ``bid_type``
  (unified/manual), the ``placement_search``/``placement_recommendations`` zone
  toggles, plus ``name`` and ``payment_type`` (all nullable: unfilled until the
  first adverts-v2 sync).
* ``monitoring.advertising_stat_daily`` gains ``order_sum`` — WB fullstats
  ``sum_price`` (ad-attributed order revenue), previously dropped by the raw
  model's ``extra="ignore"``.
* New ``monitoring.advertising_search_stat_daily`` fact table — the daily
  SEARCH-zone slice per (date, campaign, SKU) from ``/adv/v1/normquery/stats``,
  which lets the analytics layer split unified-bid campaigns into
  search / shelves (shelves = fullstats - search).

Revision ID: f3b9c4d17e5a
Revises: c9e3a7b1d5f2
Create Date: 2026-07-10 12:00:00.000000

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "f3b9c4d17e5a"
down_revision: str | None = "c9e3a7b1d5f2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_SCHEMA = "monitoring"


def upgrade() -> None:
    """Add campaign settings columns, ad revenue, and the search fact table."""
    op.add_column(
        "campaigns",
        sa.Column("bid_type", sa.String(length=16), nullable=True),
        schema=_SCHEMA,
    )
    op.add_column(
        "campaigns",
        sa.Column("placement_search", sa.Boolean(), nullable=True),
        schema=_SCHEMA,
    )
    op.add_column(
        "campaigns",
        sa.Column("placement_recommendations", sa.Boolean(), nullable=True),
        schema=_SCHEMA,
    )
    op.add_column(
        "campaigns",
        sa.Column("name", sa.String(length=512), nullable=True),
        schema=_SCHEMA,
    )
    op.add_column(
        "campaigns",
        sa.Column("payment_type", sa.String(length=8), nullable=True),
        schema=_SCHEMA,
    )

    op.add_column(
        "advertising_stat_daily",
        sa.Column(
            "order_sum",
            sa.Numeric(precision=14, scale=2),
            nullable=False,
            server_default="0",
        ),
        schema=_SCHEMA,
    )
    # Drop the server default now that existing rows are backfilled — new rows
    # always supply the value explicitly via the ingestion upsert.
    op.alter_column(
        "advertising_stat_daily",
        "order_sum",
        server_default=None,
        schema=_SCHEMA,
    )

    op.create_table(
        "advertising_search_stat_daily",
        sa.Column("stat_date", sa.Date(), nullable=False),
        sa.Column("campaign_id", sa.BigInteger(), nullable=False),
        sa.Column("nm_id", sa.BigInteger(), nullable=False),
        sa.Column("views", sa.Integer(), nullable=False),
        sa.Column("clicks", sa.Integer(), nullable=False),
        sa.Column("add_to_cart", sa.Integer(), nullable=False),
        sa.Column("spend", sa.Numeric(precision=14, scale=2), nullable=False),
        sa.Column("orders", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("stat_date", "campaign_id", "nm_id"),
        schema=_SCHEMA,
    )
    op.create_index(
        "ix_advertising_search_stat_daily_nm_id_stat_date",
        "advertising_search_stat_daily",
        ["nm_id", "stat_date"],
        schema=_SCHEMA,
    )


def downgrade() -> None:
    """Drop the search fact table, ad revenue, and campaign settings columns."""
    op.drop_index(
        "ix_advertising_search_stat_daily_nm_id_stat_date",
        table_name="advertising_search_stat_daily",
        schema=_SCHEMA,
    )
    op.drop_table("advertising_search_stat_daily", schema=_SCHEMA)
    op.drop_column("advertising_stat_daily", "order_sum", schema=_SCHEMA)
    op.drop_column("campaigns", "payment_type", schema=_SCHEMA)
    op.drop_column("campaigns", "name", schema=_SCHEMA)
    op.drop_column("campaigns", "placement_recommendations", schema=_SCHEMA)
    op.drop_column("campaigns", "placement_search", schema=_SCHEMA)
    op.drop_column("campaigns", "bid_type", schema=_SCHEMA)
