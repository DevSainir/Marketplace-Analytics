"""Remove "Ship" and "Pin": drop warehouse_mark, retire the pin kinds

Both features were taken off the two stock tables. What that leaves behind is
one whole table and two rows' worth of dead ``kind`` values:

* ``monitoring.warehouse_mark`` — the per-SKU "Ship" flag, dropped. It was
  keyed ``(nm_id, warehouse_name)`` with no ``workspace_id`` at all, which is
  why it never appears in ``scripts/sql/row_level_security.sql``: it was the
  last monitoring table that could not carry a tenancy policy. Dropping it
  closes that gap rather than working around it.

* ``finreports.balance_pin`` — KEPT. The same table still stores "Don't count"
  (``warehouse_uncounted`` / ``sku_uncounted``), which stays on the balance
  grid. Only the two "Pin" kinds are retired, and this deletes their
  rows. ``kind`` is a plain ``varchar(32)``, not a PG enum, so retiring a value
  is a ``DELETE`` and not a type rewrite.

Irreversible in substance: ``downgrade`` puts the table back empty and cannot
recover the marks, which is the honest shape — the rows are the feature, and
the feature is gone.

Revision ID: a3f81c2e57d4
Revises: c9d4e1b70f38
Create Date: 2026-09-11 13:10:00.000000

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a3f81c2e57d4"
down_revision: str | None = "c9d4e1b70f38"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Drop the warehouse marks, and delete the retired balance-pin rows."""
    op.drop_table("warehouse_mark", schema="monitoring")
    op.execute(sa.text("DELETE FROM finreports.balance_pin WHERE kind IN ('sku', 'warehouse')"))


def downgrade() -> None:
    """Recreate ``warehouse_mark``, empty.

    The pin rows are not restored: nothing records which they were, and a
    downgrade that invented them would be worse than one that admits the loss.
    """
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
        schema="monitoring",
    )
