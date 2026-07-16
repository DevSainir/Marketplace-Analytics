"""pinned_sku_order_and_color: manual chip order + colour tint

Revision ID: a3d1f7b52c68
Revises: f2b0c6e8d4a3
Create Date: 2026-07-16

Pins gain a manual position and a highlight colour. Both are global, like the
pin itself — one shared watchlist, so one manager's reorder or repaint is what
the whole team sees.

``sort_order`` backfills from the existing pin order (``created_at``, then
``nm_id``) so the chip row looks identical the moment the migration lands.
``color`` is NULL for an unpainted chip; it stores ``#rrggbb``.
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision = "a3d1f7b52c68"
down_revision = "f2b0c6e8d4a3"
branch_labels = None
depends_on = None

_SCHEMA = "monitoring"


def upgrade() -> None:
    """Add ``sort_order``/``color`` and seed the order from the pin order."""
    op.add_column(
        "pinned_sku",
        sa.Column("sort_order", sa.Integer(), server_default="0", nullable=False),
        schema=_SCHEMA,
    )
    op.add_column(
        "pinned_sku",
        sa.Column("color", sa.String(length=7), nullable=True),
        schema=_SCHEMA,
    )

    # Every pre-existing row defaulted to 0; rank them by the order the chip
    # row already rendered in so the migration is visually a no-op.
    # (S608 noqa: _SCHEMA is a module constant, not user input.)
    op.execute(
        f"""
        UPDATE {_SCHEMA}.pinned_sku AS p
        SET sort_order = ranked.position
        FROM (
            SELECT nm_id,
                   (ROW_NUMBER() OVER (ORDER BY created_at, nm_id))::int - 1 AS position
            FROM {_SCHEMA}.pinned_sku
        ) AS ranked
        WHERE p.nm_id = ranked.nm_id
        """  # noqa: S608
    )


def downgrade() -> None:
    """Drop the order and colour columns."""
    op.drop_column("pinned_sku", "color", schema=_SCHEMA)
    op.drop_column("pinned_sku", "sort_order", schema=_SCHEMA)
