"""finreports: P&L columns on the settlement rows + seller cost prices

Widens ``finreports.logistics_transaction`` from the logistics-only subset it
carried to the whole settlement row WB publishes, so the module can produce a
for the one input WB cannot supply.

Two things worth knowing before running this:

* The table is not empty (~620k rows on production). ``ADD COLUMN ... NOT NULL``
  without a default fails outright there, so every column is added *with* a
  server default and the default is dropped immediately afterwards — the rows
  end up zero-filled, and the model keeps its Python-side default with no
  server-side drift for ``tests/integration/core/test_migrations.py`` to find.
* **Zero-filled is not the same as correct.** Existing rows carry 0 revenue, 0
  commission and 0 payout until ``scripts/backfill_pnl_columns.py`` re-fetches
  the reports from WB. Until then the P&L for historical weeks is empty rather
  than wrong-looking, and the endpoint says so.

Revision ID: be09d50ae5ff
Revises: 4aba1dcdb294
Create Date: 2026-07-29 17:41:16.360803
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "be09d50ae5ff"
down_revision: str | None = "4aba1dcdb294"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_SCHEMA = "finreports"
_TABLE = "logistics_transaction"

_MONEY = sa.Numeric(precision=14, scale=2)
_PERCENT = sa.Numeric(precision=8, scale=2)

#: ``(column, type, server default used only to backfill existing rows)``.
_NEW_COLUMNS: list[tuple[str, sa.types.TypeEngine[object], str]] = [
    # Catalogue identity WB stamps on the settlement row itself.
    ("subject_name", sa.String(length=128), "''"),
    ("brand_name", sa.String(length=128), "''"),
    ("doc_type_name", sa.String(length=64), "''"),
    ("site_country", sa.String(length=64), "''"),
    ("srv_dbs", sa.Boolean(), "false"),
    # A count, not money: with delivery_amount it splits delivery_rub into
    # forward and return logistics.
    ("return_amount", sa.Integer(), "0"),
    # Revenue.
    ("retail_price", _MONEY, "0"),
    ("retail_amount", _MONEY, "0"),
    ("retail_price_withdisc_rub", _MONEY, "0"),
    ("sale_percent", _PERCENT, "0"),
    ("commission_percent", _PERCENT, "0"),
    # WB's cut and the settled payout.
    ("ppvz_for_pay", _MONEY, "0"),
    # Wider than money on purpose — see the model's comment: WB publishes this
    # one unrounded, and rounding it to kopecks breaks the payout identity.
    ("ppvz_vw", sa.Numeric(precision=18, scale=10), "0"),
    ("ppvz_vw_nds", _MONEY, "0"),
    ("ppvz_sales_commission", _MONEY, "0"),
    ("ppvz_reward", _MONEY, "0"),
    ("ppvz_spp_prc", _PERCENT, "0"),
    ("ppvz_kvw_prc_base", _PERCENT, "0"),
    ("ppvz_kvw_prc", _PERCENT, "0"),
    ("acquiring_fee", _MONEY, "0"),
    ("acquiring_percent", _PERCENT, "0"),
    ("acquiring_bank", sa.String(length=128), "''"),
    ("payment_processing", sa.String(length=128), "''"),
    # Discounts and the agent's VAT.
    ("product_discount_for_report", _MONEY, "0"),
    ("supplier_promo", _MONEY, "0"),
    ("seller_promo_discount", _MONEY, "0"),
    ("loyalty_discount", _MONEY, "0"),
    ("installment_cofinancing_amount", _MONEY, "0"),
    ("cashback_amount", _MONEY, "0"),
    ("cashback_discount", _MONEY, "0"),
    ("cashback_commission_change", _MONEY, "0"),
    ("agency_vat", _MONEY, "0"),
]


def upgrade() -> None:
    """Apply the schema changes for this revision."""
    for name, type_, default in _NEW_COLUMNS:
        op.add_column(
            _TABLE,
            sa.Column(name, type_, nullable=False, server_default=sa.text(default)),
            schema=_SCHEMA,
        )
        # The default existed only to fill the rows already in the table; leaving
        # it behind would be schema the models do not declare.
        op.alter_column(_TABLE, name, server_default=None, schema=_SCHEMA)

    op.create_table(
        "product_cost_price",
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("nm_id", sa.BigInteger(), nullable=False),
        sa.Column("cost", _MONEY, nullable=False),
        sa.Column("currency", sa.String(length=8), nullable=False),
        sa.Column("vendor_code", sa.String(length=128), nullable=False),
        sa.Column("source", sa.String(length=16), nullable=False),
        sa.Column("note", sa.String(length=256), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("workspace_id", "nm_id", name=op.f("pk_product_cost_price")),
        schema=_SCHEMA,
    )


def downgrade() -> None:
    """Revert the schema changes for this revision."""
    op.drop_table("product_cost_price", schema=_SCHEMA)
    for name, _type, _default in reversed(_NEW_COLUMNS):
        op.drop_column(_TABLE, name, schema=_SCHEMA)
