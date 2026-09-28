"""Monitoring: the card's buyer rating — the storefront's stars — on the catalogue card.

The SKU header shows it beside the vendor code. WB serves it as
``product.feedbackRating`` on ``sales-funnel/products``, the aggregate the
nightly cohort pass already calls, so that pass keeps it here; it matched the
storefront's ``reviewRating`` to the decimal on every card checked (2026-09-26).

Nullable, no default: a card with no reviews has no rating, and a card the
pass has not reached yet has none known. Existing rows are filled by the next
cohort pass (07:00 MSK).

Revision ID: e3b8a1f07c52
Revises: d7f2c9e04b16
Create Date: 2026-09-28
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision: str = "e3b8a1f07c52"
down_revision: str | None = "d7f2c9e04b16"
branch_labels: str | None = None
depends_on: str | None = None

_SCHEMA = "monitoring"


def upgrade() -> None:
    """Add the rating column, unknown for every existing card."""
    op.add_column(
        "product_card",
        sa.Column("feedback_rating", sa.Numeric(2, 1), nullable=True),
        schema=_SCHEMA,
    )


def downgrade() -> None:
    """Drop the column."""
    op.drop_column("product_card", "feedback_rating", schema=_SCHEMA)
