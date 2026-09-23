"""Keep WB's own totals next to every report we hold.

``sales-reports/list`` carries WB's own sums per report — ``forPaySum``,
``retailAmountSum``, ``bankPaymentSum`` and the rest — and until now they were
parsed and thrown away. Storing three of them buys two different things.

**A free change screen.** Whether WB revises a report after serving it is the
open question the daily tail was built to answer, and answering it used to mean
re-reading the whole report: one detail request per report per day. The listed
totals answer it for nothing — one list request covers every report in the
window at once, and only a report whose totals MOVED needs its rows re-read.
The comparison is WB's figure against WB's earlier figure, so our own
classification of operations never enters it: `record_publication_spread` shows
why that matters, since our reconstruction of ``forPaySum`` is knowingly 128.26
KGS out on report 989286628 and the reason is how we bucket «Коррекция продаж»,
not the data.

**A standing oracle.** `docs/finreports/PNL.md` warns that most ways to get a
settlement figure wrong produce a plausible statement rather than an error.
These are WB's own answer for the same report, on file rather than observed once
in passing, so the statement can be checked against them at any time instead of
only in the seconds after a harvest.

Nullable, with no backfill: a report already on file was booked before the
totals were kept, and inventing them from our own rows would defeat the point of
having an independent figure.

Revision ID: c5e9d2a814f7
Revises: f3c8a71b06d2
Create Date: 2026-09-23
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision: str = "c5e9d2a814f7"
down_revision: str | None = "f3c8a71b06d2"
branch_labels: str | None = None
depends_on: str | None = None

#: The three totals, on both report tables. Money is `Numeric(18, 2)` like every
#: other settlement figure in the schema — WB serves these as strings, and a
#: float between the wire and the column is what `PNL.md` warns about.
_COLUMNS: tuple[str, ...] = (
    "wb_for_pay_sum",
    "wb_retail_amount_sum",
    "wb_bank_payment_sum",
)

_TABLES: tuple[str, ...] = ("financial_report", "daily_settlement_report")


def upgrade() -> None:
    """Add WB's listed totals to both report tables."""
    for table in _TABLES:
        for column in _COLUMNS:
            op.add_column(
                table,
                sa.Column(column, sa.Numeric(18, 2), nullable=True),
                schema="finreports",
            )


def downgrade() -> None:
    """Drop them. Nothing derives from them that cannot be re-listed."""
    for table in _TABLES:
        for column in _COLUMNS:
            op.drop_column(table, column, schema="finreports")
