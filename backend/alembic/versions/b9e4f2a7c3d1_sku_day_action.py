"""sku_day_action: the per-day «Действия» row under the matrix comments

Revision ID: b9e4f2a7c3d1
Revises: a2f6b8d0c714
Create Date: 2026-07-20

One row per (nm_id, day) recording what the manager DID that day: whether the
unified / manual campaigns were switched on (each with its «Бюджет рекламы»)
and whether the price was changed («Повысили»/«Понизили»/«Нет» + «На сколько»).
Every field is nullable — the service deletes a row whose answers are all
cleared, so the table only holds days that were actually touched.
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision = "b9e4f2a7c3d1"
down_revision = "a2f6b8d0c714"
branch_labels = None
depends_on = None

_SCHEMA = "monitoring"


def upgrade() -> None:
    """Create ``sku_day_action``."""
    op.create_table(
        "sku_day_action",
        sa.Column("nm_id", sa.BigInteger(), primary_key=True),
        sa.Column("action_date", sa.Date(), primary_key=True),
        sa.Column("uni_rk_enabled", sa.Boolean(), nullable=True),
        sa.Column("uni_rk_budget", sa.Numeric(14, 2), nullable=True),
        sa.Column("manual_rk_enabled", sa.Boolean(), nullable=True),
        sa.Column("manual_rk_budget", sa.Numeric(14, 2), nullable=True),
        sa.Column("price_change", sa.String(8), nullable=True),
        sa.Column("price_change_amount", sa.Numeric(12, 2), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        schema=_SCHEMA,
    )


def downgrade() -> None:
    """Drop ``sku_day_action``."""
    op.drop_table("sku_day_action", schema=_SCHEMA)
