"""Two partial indexes for the per-article P&L's own scans.

Not a shape change: indexes only.

The settlement aggregates come from the rollup now, but two queries on the same
page still read the detail directly, and both were measured at seconds on the
largest workspace's full history (671 k rows):

* ``sku_penalties`` — 3.4-4.2 s — splits each article's fines by WB's reason. It
  reads a column that is non-zero on **6 104 rows of 1 459 394** (0.4 %), so a
  seq scan spends all of its time on rows it discards.
* ``revenue_coverage`` — 3.8-4.7 s — counts sale rows and how many carry
  revenue, for the caveat about the one-off P&L-column backfill. Sales are
  444 920 rows, under a third of the table.

Both indexes carry their predicate's columns in ``INCLUDE``, so the queries are
answered without touching the table at all.

The sale predicate is the literal WB writes, and
``tests/unit/finreports/test_pnl_indexes.py`` fails if ``SALE_OPERS`` ever stops
matching it — a renamed operation would leave the index silently unusable and
the page silently slow again.

Revision ID: b3d7f18c05ae
Revises: e5b1c93a7d24
Create Date: 2026-09-17
"""

from __future__ import annotations

from alembic import op

revision: str = "b3d7f18c05ae"
down_revision: str | None = "e5b1c93a7d24"
branch_labels: str | None = None
depends_on: str | None = None

_TABLE = "finreports.logistics_transaction"


def upgrade() -> None:
    """Add the penalty and sale partial indexes."""
    op.execute(
        f"CREATE INDEX IF NOT EXISTS ix_logistics_txn_penalty "
        f"ON {_TABLE} (workspace_id, rr_dt) "
        "INCLUDE (nm_id, bonus_type_name, penalty) "
        "WHERE penalty <> 0"
    )
    op.execute(
        f"CREATE INDEX IF NOT EXISTS ix_logistics_txn_sale "
        f"ON {_TABLE} (workspace_id, rr_dt) "
        "INCLUDE (retail_amount) "
        "WHERE supplier_oper_name IN ('Продажа')"
    )


def downgrade() -> None:
    """Drop both."""
    op.execute("DROP INDEX IF EXISTS finreports.ix_logistics_txn_sale")
    op.execute("DROP INDEX IF EXISTS finreports.ix_logistics_txn_penalty")
