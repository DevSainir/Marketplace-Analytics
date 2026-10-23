"""advertising_write_off_daily: who actually paid for the advertising

Revision ID: b8d24f61ca07
Revises: a1c73e95b204
Create Date: 2026-09-15

``GET /adv/v3/fullstats`` reports the impressions a campaign served and what
they cost, and says nothing about where the money came from. WB pays part of a
seller's advertising out of a bonus pool (cashback, up to 50 % of a charge), and
those charges never reach the weekly settlement report either — a bonus
write-off carries no invoice document, so no "WB Promotion" services
deduction row is ever raised for it.

The consequence, measured on one workspace for 2026-09-01..15: WB
funded 38 % of the write-offs, and the per-SKU report counted every som of it
as the seller's own spend. One SKU read ROI -61.5 %
where the real figure was +1.6 %.

``GET /adv/v1/upd`` is the only surface that names the funding source. This
table holds it, aggregated to ``(Moscow day, campaign, paymentType, currency)``.

``currency`` is in the PRIMARY KEY on purpose: WB mixes currencies inside one
window (96 balance rows in RUB against 223 in KGS, 2026-08). WB's ``updNum`` is
deliberately absent — it is an invoice-document number and every cashback row
carries ``0``, so it identifies nothing.

Created empty. The nightly harvest fills the rolling window forward;
``scripts/backfill_history.py`` walks the history back (WB serves the feed to at
least 2024-08, one month per request).

The TRUNCATE guard of ``f4c8b1e57a29`` is attached here too. That guard is a
per-table trigger, so a table created afterwards is born unprotected — which is
what ``tests/integration/core/test_migrations.py`` fails on until this runs.
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision = "b8d24f61ca07"
down_revision = "a1c73e95b204"
branch_labels = None
depends_on = None

_SCHEMA = "monitoring"
_TABLE = "advertising_write_off_daily"

#: The guard installed by ``f4c8b1e57a29`` — see the module docstring.
_TRUNCATE_TRIGGER = "guard_against_truncate"


def upgrade() -> None:
    """Create the advertising write-off ledger and its window index."""
    op.create_table(
        _TABLE,
        sa.Column("stat_date", sa.Date(), nullable=False),
        sa.Column("campaign_id", sa.BigInteger(), nullable=False),
        sa.Column("payment_type", sa.String(length=32), nullable=False),
        sa.Column("currency", sa.String(length=8), nullable=False),
        sa.Column("amount", sa.Numeric(14, 2), nullable=False),
        sa.Column("write_offs", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint(
            "stat_date",
            "campaign_id",
            "payment_type",
            "currency",
            name=op.f(f"pk_{_TABLE}"),
        ),
        schema=_SCHEMA,
    )
    # The report reads a whole window across every campaign, so the date leads.
    op.create_index(f"ix_{_TABLE}_date", _TABLE, ["stat_date"], schema=_SCHEMA)
    # A new table in a guarded schema has no TRUNCATE trigger of its own.
    op.execute(
        f"CREATE TRIGGER {_TRUNCATE_TRIGGER} BEFORE TRUNCATE ON {_SCHEMA}.{_TABLE} "
        "FOR EACH STATEMENT EXECUTE FUNCTION organizations.guard_against_truncate()"
    )


def downgrade() -> None:
    """Drop the ledger. The per-SKU report falls back to gross ad spend."""
    op.execute(f"DROP TRIGGER IF EXISTS {_TRUNCATE_TRIGGER} ON {_SCHEMA}.{_TABLE}")
    op.drop_index(f"ix_{_TABLE}_date", table_name=_TABLE, schema=_SCHEMA)
    op.drop_table(_TABLE, schema=_SCHEMA)
