"""Product card: the main gallery photo URL

Revision ID: d1a4f7c92b60
Revises: c4d9e6b13a72
Create Date: 2026-09-09 10:00:00.000000

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "d1a4f7c92b60"
down_revision: str | None = "c4d9e6b13a72"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add the card's main photo URL to the catalogue dimension.

    Empty for every existing row, and it stays empty until that workspace's
    next catalogue sync — the URL is only knowable from a Content API call, and
    backfilling one here would mean issuing one per workspace inside a
    migration. The screens that show it treat "" as "no thumbnail" and render
    their existing text identity, so the gap is a missing picture rather than a
    broken row.
    """
    op.add_column(
        "product_card",
        sa.Column("photo_url", sa.String(length=512), server_default="", nullable=False),
        schema="monitoring",
    )


def downgrade() -> None:
    """Drop the photo URL.

    Lossless: the value is a cache of what WB serves, and the next catalogue
    sync after a re-upgrade fills it in again.
    """
    op.drop_column("product_card", "photo_url", schema="monitoring")
