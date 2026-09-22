"""Record WHICH measurement a customer price is, and its СПП when stated.

``customer_price`` had one source since it existed: the public storefront card,
read with a fixed ``dest`` — the shelf price for one region at one moment of the
morning. On 2026-09-22 that endpoint went behind WB's anti-bot challenge and the
column started coming back empty for every SKU.

The replacement is the order feed's ``finishedPrice``: what customers were
actually charged that day. It is close (median gap 5 ₽, ratio 1,0013 against the
storefront) but it is NOT the same measurement, and a user-visible figure must
not change meaning with nothing to point at. So the source travels with the
price, and ``customer_spp`` carries WB's own loyalty percent when the answering
source states it as a number instead of leaving it to be inferred.

Existing rows are all storefront; they are backfilled as such rather than left
ambiguous, because ``NULL`` would later read as "unknown" for rows that are not.

Revision ID: a1c7e93b65f2
Revises: d4f6a2b91c73
Create Date: 2026-09-22
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision: str = "a1c7e93b65f2"
down_revision: str | None = "d4f6a2b91c73"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    """Add the СПП and source columns, dating existing rows to the storefront."""
    op.add_column(
        "price_snapshot",
        sa.Column("customer_spp", sa.Numeric(5, 2), nullable=True),
        schema="monitoring",
    )
    op.add_column(
        "price_snapshot",
        sa.Column("customer_source", sa.String(16), nullable=True),
        schema="monitoring",
    )
    op.execute(
        "UPDATE monitoring.price_snapshot "
        "SET customer_source = 'storefront' "
        "WHERE customer_price IS NOT NULL"
    )


def downgrade() -> None:
    """Drop both columns."""
    op.drop_column("price_snapshot", "customer_source", schema="monitoring")
    op.drop_column("price_snapshot", "customer_spp", schema="monitoring")
