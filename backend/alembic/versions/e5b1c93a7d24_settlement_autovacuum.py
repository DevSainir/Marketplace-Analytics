"""Keep the settlement detail's visibility map current.

Not a shape change: storage parameters only.

Every read of the P&L or «Сводка» first asks the settlement detail how many rows
each day of the window holds, and that question is answered by an index-only
scan — 16 MB against the table's 755 — which is what makes a self-verifying
cache affordable at all. «Index-only» holds only while the pages the index
points at are marked all-visible, and a harvest upserts ~100 k rows a day, which
un-marks them.

Measured on the largest workspace, one day after the last autovacuum: 268 863 heap
fetches on that scan, 105 737 dead tuples, and the check cost 4.0 s instead of
the 0.7 s it costs on a freshly vacuumed table. That difference IS the wait a
seller sees on «Вся история», because the aggregate it guards takes 14 ms.

Default `autovacuum_vacuum_scale_factor` is 0.2 — a fifth of 1.46 M rows, so
~290 k dead tuples accumulate before anything runs. 0.02 makes it ~29 k, which
this table produces in well under a day.

Revision ID: e5b1c93a7d24
Revises: a7d2f9c40b18
Create Date: 2026-09-16
"""

from __future__ import annotations

from alembic import op

revision: str = "e5b1c93a7d24"
down_revision: str | None = "a7d2f9c40b18"
branch_labels: str | None = None
depends_on: str | None = None

_TABLE = "finreports.logistics_transaction"
_SETTINGS = "autovacuum_vacuum_scale_factor = 0.02, autovacuum_analyze_scale_factor = 0.02"


def upgrade() -> None:
    """Vacuum this table on 2 % of it turning over, not 20 %."""
    op.execute(f"ALTER TABLE {_TABLE} SET ({_SETTINGS})")


def downgrade() -> None:
    """Back to the cluster-wide defaults."""
    op.execute(
        f"ALTER TABLE {_TABLE} RESET "
        "(autovacuum_vacuum_scale_factor, autovacuum_analyze_scale_factor)"
    )
