"""finreports: the settlement walk gets its own watermark

Revision ID: c3f8a1d20e47
Revises: b7e4a2f19c30
Create Date: 2026-09-08

The harvest used to read "how far am I settled" from `max(financial_report.date_to)`
— the period WB *states* on the report header. That header is written from the
first page that lands and already claims the whole stated week, so a week walked
only in part still advanced the mark to its end; the freshness gate then probed
the day after and skipped the week for good.

The new table records what the walk *finished* instead. Seeded from the old
figure on purpose: it keeps the deploy behaviour-neutral (a NULL watermark reads
as "never harvested" and would send every workspace into a full 28-day backfill,
four paced windows each, all at once). The seed therefore inherits whatever holes
exist at deploy time — which is why the affected week is backfilled BEFORE this
ships, not after.
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision = "c3f8a1d20e47"
down_revision = "b7e4a2f19c30"
branch_labels = None
depends_on = None

_SCHEMA = "finreports"

_SEED = sa.text(
    """
    INSERT INTO finreports.settlement_watermark (workspace_id, settled_through)
    SELECT workspace_id, MAX(date_to)
    FROM finreports.financial_report
    WHERE date_to IS NOT NULL
    GROUP BY workspace_id
    ON CONFLICT (workspace_id) DO NOTHING
    """
)


def upgrade() -> None:
    """Create ``settlement_watermark`` and seed it from the reports on file."""
    op.create_table(
        "settlement_watermark",
        sa.Column("workspace_id", sa.Uuid(), primary_key=True),
        sa.Column("settled_through", sa.Date(), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        schema=_SCHEMA,
    )
    op.execute(_SEED)


def downgrade() -> None:
    """Drop the watermark table; the harvest falls back to the report headers."""
    op.drop_table("settlement_watermark", schema=_SCHEMA)
