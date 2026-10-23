"""sku_day_action: ad campaign slots hold a campaign type, not a yes/no

Revision ID: e2a7c4f9b681
Revises: c1d5b3e8a746
Create Date: 2026-07-21

The two ad campaign questions changed from "Were unified/manual campaigns on?" (a boolean) to
"First/Second campaign" — each a campaign TYPE picked from a synced dropdown
(uni / manual_search / manual_shelves / cpc). "Price changed?" loses its "No"
option; an unmoved price is now simply left unanswered.

Existing manager rows are migrated best-effort:
* ``uni_rk_enabled = true``  -> ``first_rk_type = 'uni'`` (unified).
* ``manual_rk_enabled = true`` -> ``second_rk_type = 'manual_search'`` — the old
  flag did not say which manual placement, so it lands on the primary search
  zone; the manager can re-pick to "Manual shelves" if it was shelves.
* ``false`` flags carried no type and no budget, so they become ``NULL``.
* ``price_change = 'none'`` becomes ``NULL`` (the "No" answer no longer exists).
* Budgets are renamed and kept as-is.

Any row left entirely ``NULL`` by the above (a bare "No"/false answer) is
deleted, matching the service rule that an all-empty day carries no row.
"""

from __future__ import annotations

# ruff: noqa: S608 — the schema name in the f-string SQL is a module constant.
import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision = "e2a7c4f9b681"
down_revision = "c1d5b3e8a746"
branch_labels = None
depends_on = None

_SCHEMA = "monitoring"
_TABLE = f"{_SCHEMA}.sku_day_action"


def upgrade() -> None:
    """Add the type columns, migrate the flags into them, drop the flags."""
    op.add_column(
        "sku_day_action",
        sa.Column("first_rk_type", sa.String(16), nullable=True),
        schema=_SCHEMA,
    )
    op.add_column(
        "sku_day_action",
        sa.Column("second_rk_type", sa.String(16), nullable=True),
        schema=_SCHEMA,
    )
    op.alter_column(
        "sku_day_action", "uni_rk_budget", new_column_name="first_rk_budget", schema=_SCHEMA
    )
    op.alter_column(
        "sku_day_action", "manual_rk_budget", new_column_name="second_rk_budget", schema=_SCHEMA
    )

    op.execute(
        f"""
        UPDATE {_TABLE} SET
            first_rk_type  = CASE WHEN uni_rk_enabled    THEN 'uni' END,
            second_rk_type = CASE WHEN manual_rk_enabled THEN 'manual_search' END,
            price_change   = CASE WHEN price_change IN ('up', 'down') THEN price_change END
        """
    )

    op.drop_column("sku_day_action", "uni_rk_enabled", schema=_SCHEMA)
    op.drop_column("sku_day_action", "manual_rk_enabled", schema=_SCHEMA)

    # A row the migration emptied (a bare false / "No" answer) carries no row.
    op.execute(
        f"""
        DELETE FROM {_TABLE}
        WHERE first_rk_type IS NULL AND first_rk_budget IS NULL
          AND second_rk_type IS NULL AND second_rk_budget IS NULL
          AND price_change IS NULL AND price_change_amount IS NULL
        """
    )


def downgrade() -> None:
    """Restore the boolean flags from the type columns (best-effort)."""
    op.add_column(
        "sku_day_action",
        sa.Column("uni_rk_enabled", sa.Boolean(), nullable=True),
        schema=_SCHEMA,
    )
    op.add_column(
        "sku_day_action",
        sa.Column("manual_rk_enabled", sa.Boolean(), nullable=True),
        schema=_SCHEMA,
    )
    op.execute(
        f"""
        UPDATE {_TABLE} SET
            uni_rk_enabled    = CASE WHEN first_rk_type  IS NOT NULL THEN true END,
            manual_rk_enabled = CASE WHEN second_rk_type IS NOT NULL THEN true END
        """
    )
    op.drop_column("sku_day_action", "first_rk_type", schema=_SCHEMA)
    op.drop_column("sku_day_action", "second_rk_type", schema=_SCHEMA)
    op.alter_column(
        "sku_day_action", "first_rk_budget", new_column_name="uni_rk_budget", schema=_SCHEMA
    )
    op.alter_column(
        "sku_day_action", "second_rk_budget", new_column_name="manual_rk_budget", schema=_SCHEMA
    )
