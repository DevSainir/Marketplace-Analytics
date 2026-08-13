"""monitoring: store each size's barcode for FBS stock lookups

Revision ID: d4f8a1c60e97
Revises: c7e2b4d19a53
Create Date: 2026-08-13

FBS (seller-warehouse) stock is the one WB surface that identifies a size by
**barcode** rather than ``chrt_id`` — ``POST /api/v3/stocks/{warehouseId}``
takes ``{"skus": [barcode, ...]}``. The Content API has always returned the
barcodes in ``sizes[].skus``; we simply never kept them.

Backfilled by the next catalogue sync, so the column starts blank rather than
being reconstructed here: the settlement tables hold barcodes too, but they are
``finreports``-owned and reach only SKUs that have already sold.
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision = "d4f8a1c60e97"
down_revision = "c7e2b4d19a53"
branch_labels = None
depends_on = None

_SCHEMA = "monitoring"


def upgrade() -> None:
    """Add the blank-defaulted ``barcode`` column to ``product_size``."""
    op.add_column(
        "product_size",
        sa.Column("barcode", sa.String(length=32), nullable=False, server_default=""),
        schema=_SCHEMA,
    )


def downgrade() -> None:
    """Drop the ``barcode`` column."""
    op.drop_column("product_size", "barcode", schema=_SCHEMA)
