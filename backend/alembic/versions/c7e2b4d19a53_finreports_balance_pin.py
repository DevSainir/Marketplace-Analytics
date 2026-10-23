"""finreports: pinned rows and columns of the balance grid

Adds ``finreports.balance_pin`` — one row per pinned SKU or warehouse of the
"Stock balance" table, keyed ``(workspace_id, kind, value)`` so
the pin is shared across a workspace's users and scoped to it. The presence of a
row is the pin; unpinning deletes it. Pins decide only what the grid shows
first — never a quantity, a cost, or any settlement fact.

Revision ID: c7e2b4d19a53
Revises: b3f7a1c92e84
Create Date: 2026-08-04 10:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c7e2b4d19a53"
down_revision: str | None = "b3f7a1c92e84"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_SCHEMA = "finreports"


def upgrade() -> None:
    """Apply the schema changes for this revision."""
    op.create_table(
        "balance_pin",
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("value", sa.String(length=128), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("workspace_id", "kind", "value", name=op.f("pk_balance_pin")),
        schema=_SCHEMA,
    )


def downgrade() -> None:
    """Revert the schema changes for this revision."""
    op.drop_table("balance_pin", schema=_SCHEMA)
