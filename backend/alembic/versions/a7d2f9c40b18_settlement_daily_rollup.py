"""settlement daily rollup

The settlement detail is 1 459 394 rows and 870 MB against a 128 MB
``shared_buffers``, so any window covering most of it is a parallel seq scan —
714 MB off disk, ~7 s per pass. The same rows collapse to 27 857 groups on
(workspace, report, day, article): a 40-fold reduction, small enough to stay cached.

Created EMPTY. A rollup nobody has built yet is simply a cache that misses, and
the read path rebuilds what it finds missing — filling it here would mean this
migration summing three quarters of a gigabyte inside a deploy.

Revision ID: a7d2f9c40b18
Revises: c4a17e3b9f52
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "a7d2f9c40b18"
down_revision: str | None = "c4a17e3b9f52"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _money(name: str) -> sa.Column:
    """A settlement money column, at the detail's own precision."""
    return sa.Column(name, sa.Numeric(18, 2), nullable=False, server_default="0")


def upgrade() -> None:
    """Create the rollup table."""
    op.create_table(
        "settlement_daily_rollup",
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("report_id", sa.BigInteger(), nullable=False),
        sa.Column("rr_dt", sa.Date(), nullable=False),
        sa.Column("nm_id", sa.BigInteger(), nullable=False),
        sa.Column("currency", sa.String(length=8), nullable=False, server_default=""),
        sa.Column("sa_name", sa.String(length=128), nullable=False, server_default=""),
        sa.Column("subject_name", sa.String(length=128), nullable=False, server_default=""),
        sa.Column("brand_name", sa.String(length=128), nullable=False, server_default=""),
        sa.Column("sold_units", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("returned_units", sa.Integer(), nullable=False, server_default="0"),
        _money("sales_gross"),
        _money("returns_gross"),
        _money("sales_before_spp"),
        _money("returns_before_spp"),
        _money("payout_sales"),
        _money("payout_returns"),
        _money("payout_other"),
        # Ten decimals, like the column it sums: the commission line is a
        # residual over `ppvz_vw`, so rounding here moves a printed figure.
        sa.Column(
            "wb_commission_reported",
            sa.Numeric(22, 10),
            nullable=False,
            server_default="0",
        ),
        _money("wb_commission_vat"),
        _money("wb_reward"),
        _money("acquiring_withheld"),
        _money("acquiring_billed_apart"),
        _money("agency_vat"),
        _money("logistics_forward"),
        _money("logistics_return"),
        _money("logistics_unlegged"),
        _money("storage"),
        _money("acceptance"),
        _money("penalties"),
        _money("deductions"),
        _money("additional_payments"),
        _money("rebill_logistic_cost"),
        _money("advertising"),
        sa.Column("rows", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "built_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.PrimaryKeyConstraint(
            "workspace_id", "report_id", "rr_dt", "nm_id", name="pk_settlement_daily_rollup"
        ),
        schema="finreports",
    )
    # Every read is "this workspace, this window", and the primary key leads with
    # exactly that pair — so no second index earns its write cost here.

    # The truncate guard is attached per TABLE, so a new one starts unguarded.
    # This table is derived and would rebuild itself after a stray TRUNCATE, but
    # the guard exists precisely so nobody has to work out which tables are safe
    # to empty — it is checked by `tests/integration/core/test_migrations.py`.
    op.execute(
        "CREATE TRIGGER guard_against_truncate "
        "BEFORE TRUNCATE ON finreports.settlement_daily_rollup "
        "FOR EACH STATEMENT EXECUTE FUNCTION organizations.guard_against_truncate()"
    )


def downgrade() -> None:
    """Drop the rollup. Nothing is lost: it is derived, and rebuilt on demand."""
    op.drop_table("settlement_daily_rollup", schema="finreports")
