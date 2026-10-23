"""advertising_cluster_stat_daily: keep the search-cluster labels

Revision ID: e2b9d4c71f30
Revises: d4f8a1c60e97
Create Date: 2026-08-14

``POST /adv/v1/normquery/stats`` returns one row per day x SEARCH CLUSTER, and
until now ingestion summed the clusters away into
``advertising_search_stat_daily`` (the zone split). The cluster text is the only
record of which search phrases the seller's ads actually served, so it gets its
own table at the source's natural grain — the "Search by clusters" feature reads
it by keyword.

No backfill is possible: WB serves at most a 31-day window and the harvester
would need one throttled request per (campaign, SKU) pair per window. The table
fills forward from the next harvest.
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision = "e2b9d4c71f30"
down_revision = "d4f8a1c60e97"
branch_labels = None
depends_on = None

_SCHEMA = "monitoring"
_TABLE = "advertising_cluster_stat_daily"


def upgrade() -> None:
    """Create the per-cluster daily advertising table and its read indexes."""
    op.create_table(
        _TABLE,
        sa.Column("stat_date", sa.Date(), nullable=False),
        sa.Column("campaign_id", sa.BigInteger(), nullable=False),
        sa.Column("nm_id", sa.BigInteger(), nullable=False),
        sa.Column("cluster", sa.String(length=255), nullable=False),
        sa.Column("views", sa.Integer(), nullable=False),
        sa.Column("clicks", sa.Integer(), nullable=False),
        sa.Column("add_to_cart", sa.Integer(), nullable=False),
        sa.Column("spend", sa.Numeric(14, 2), nullable=False),
        sa.Column("orders", sa.Integer(), nullable=False),
        sa.Column("avg_position", sa.Numeric(8, 2), nullable=False),
        sa.PrimaryKeyConstraint("stat_date", "campaign_id", "nm_id", "cluster"),
        schema=_SCHEMA,
    )
    op.create_index(f"ix_{_TABLE}_date_cluster", _TABLE, ["stat_date", "cluster"], schema=_SCHEMA)
    op.create_index(f"ix_{_TABLE}_cluster", _TABLE, ["cluster"], schema=_SCHEMA)
    op.create_index(f"ix_{_TABLE}_nm_id_stat_date", _TABLE, ["nm_id", "stat_date"], schema=_SCHEMA)


def downgrade() -> None:
    """Drop the per-cluster table (the zone-split aggregate survives it)."""
    op.drop_index(f"ix_{_TABLE}_nm_id_stat_date", table_name=_TABLE, schema=_SCHEMA)
    op.drop_index(f"ix_{_TABLE}_cluster", table_name=_TABLE, schema=_SCHEMA)
    op.drop_index(f"ix_{_TABLE}_date_cluster", table_name=_TABLE, schema=_SCHEMA)
    op.drop_table(_TABLE, schema=_SCHEMA)
