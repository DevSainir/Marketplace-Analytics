"""warehouse_mark: per-SKU "Ship" flags on warehouses

Managers mark the warehouses they ship a SKU to; the stock table sorts marked
warehouses first. A mark is scoped to one SKU — the natural key is
``(nm_id, warehouse_name)``. Presence of a row == marked; unmarking deletes it.

Revision ID: b8c4d2e6f1a3
Revises: e7a3b9c1d2f4
Create Date: 2026-07-13 17:00:00.000000

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b8c4d2e6f1a3"
down_revision: str | None = "e7a3b9c1d2f4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_SCHEMA = "monitoring"


def upgrade() -> None:
    """Create the ``warehouse_mark`` table."""
    op.create_table(
        "warehouse_mark",
        sa.Column("nm_id", sa.BigInteger(), nullable=False),
        sa.Column("warehouse_name", sa.String(length=128), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("nm_id", "warehouse_name"),
        schema=_SCHEMA,
    )


def downgrade() -> None:
    """Drop the ``warehouse_mark`` table."""
    op.drop_table("warehouse_mark", schema=_SCHEMA)
