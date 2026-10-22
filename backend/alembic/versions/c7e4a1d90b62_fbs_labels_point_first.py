"""monitoring: rename FBS warehouse labels to "<point> - <city> (FBS)"

Revision ID: c7e4a1d90b62
Revises: b4f1e7c92d05
Create Date: 2026-08-20

The labels were written city-first — "Moscow (Vnukovo) (FBS)", "Moscow (Belaya
Dacha) (FBS)". "Stock by warehouse" truncates a header to its first letters, so
the moment the account ran two Moscow warehouses both columns read "Moscow (…"
and the only way to tell them apart was to hover. Leading with the warehouse's
own name fixes that at the source, in the one place a header can be fixed.

Editing ``Settings.wb_fbs_warehouse_labels`` does NOT do this. That map is only
consulted the first time a warehouse is seen; the label actually in force is
the frozen copy in ``monitoring.fbs_warehouse``, and it is also a primary-key
value in ``monitoring.stock_snapshot`` and the join key of every "Ship"
mark. So a rename is this: all three tables, one transaction, or the warehouse
loses its stock history and its marks.

Only the three labels whose text changes are listed. "Bishkek (FBS)" and the two
test stubs already read name-first and are left exactly as they are — renaming
a label costs history and buys nothing when the text is unchanged.
"""

from __future__ import annotations

# ruff: noqa: S608 — the schema and column names in the f-string SQL are module
# constants; every value is a bound parameter.
import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision = "c7e4a1d90b62"
down_revision = "b4f1e7c92d05"
branch_labels = None
depends_on = None

_SCHEMA = "monitoring"

#: ``(warehouse_id, old label, new label)``. The id addresses the directory row;
#: the old text is the only key the other two tables have.
_RENAMES: tuple[tuple[int, str, str], ...] = (
    (9945803, "Moscow (Vnukovo) (FBS)", "Vnukovo - Moscow (FBS)"),
    (9990254, "Moscow (Belaya Dacha) (FBS)", "Belaya Dacha - Moscow (FBS)"),
    (9830567, "Bishkek EDBS (FBS)", "EDBS - Bishkek (FBS)"),
)

#: Every table that stores the label, as ``(table, column)``.
_STORED_IN: tuple[tuple[str, str], ...] = (
    ("stock_snapshot", "warehouse_name"),
    ("warehouse_mark", "warehouse_name"),
)


def _apply(renames: tuple[tuple[int, str, str], ...]) -> None:
    """Move each label, and everything filed under it, to its new text.

    The directory row is matched by ``warehouse_id`` — the stable key — while
    the stock and mark rows can only be matched on the text they carry. A label
    that is not present anywhere makes every statement a no-op, which is what a
    database that never discovered that warehouse should get.
    """
    for warehouse_id, old, new in renames:
        op.execute(
            sa.text(
                f"UPDATE {_SCHEMA}.fbs_warehouse SET label = :new WHERE warehouse_id = :id"
            ).bindparams(new=new, id=warehouse_id)
        )
        for table, column in _STORED_IN:
            op.execute(
                sa.text(
                    f"UPDATE {_SCHEMA}.{table} SET {column} = :new WHERE {column} = :old"
                ).bindparams(new=new, old=old)
            )


def upgrade() -> None:
    """Rename to name-first labels, carrying stock history and marks along."""
    _apply(_RENAMES)


def downgrade() -> None:
    """Put the city-first labels back, history and marks with them."""
    _apply(tuple((warehouse_id, new, old) for warehouse_id, old, new in _RENAMES))
