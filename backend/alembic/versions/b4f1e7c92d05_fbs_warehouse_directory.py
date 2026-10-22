"""monitoring.fbs_warehouse: the discovered FBS warehouse directory

Revision ID: b4f1e7c92d05
Revises: a7c31f5b90d2
Create Date: 2026-08-19

FBS stock used to come from ONE warehouse named in configuration. The harvest
now discovers every warehouse the seller owns and reads them all, so the set
lives in the database instead — and with it the label each warehouse's stock is
filed under, which has to be frozen on first sight because
``stock_snapshot.warehouse_name`` is a primary-key column and WB's own warehouse
names are seller-editable working notes.

The row for the previously configured warehouse is seeded here under exactly
the label it has been writing all along, so its stock history stays addressable.
"""

from __future__ import annotations

# ruff: noqa: S608 — the schema name in the f-string SQL is a module constant;
# the seeded values are bound parameters.
import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision = "b4f1e7c92d05"
down_revision = "a7c31f5b90d2"
branch_labels = None
depends_on = None

_SCHEMA = "monitoring"
#: The single warehouse the old ``wb_fbs_warehouse_id``/``_label`` pair enabled.
_SEEDED_WAREHOUSE_ID = 9945803
_SEEDED_LABEL = "Moscow (Vnukovo) (FBS)"


def upgrade() -> None:
    """Create the directory and seed the warehouse already in use."""
    op.create_table(
        "fbs_warehouse",
        sa.Column("warehouse_id", sa.BigInteger(), primary_key=True),
        sa.Column("label", sa.String(128), nullable=False),
        sa.Column("wb_name", sa.String(256), server_default="", nullable=False),
        sa.Column(
            "discovered_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "last_seen_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        schema=_SCHEMA,
    )
    # Seeded rather than left to discovery: the first run after this migration
    # would otherwise derive a label from WB's own name for a warehouse that
    # already has months of stock history under the configured one.
    op.execute(
        sa.text(
            f"INSERT INTO {_SCHEMA}.fbs_warehouse (warehouse_id, label) "
            "VALUES (:warehouse_id, :label) ON CONFLICT DO NOTHING"
        ).bindparams(warehouse_id=_SEEDED_WAREHOUSE_ID, label=_SEEDED_LABEL)
    )


def downgrade() -> None:
    """Drop the directory (the configured single warehouse takes over again)."""
    op.drop_table("fbs_warehouse", schema=_SCHEMA)
