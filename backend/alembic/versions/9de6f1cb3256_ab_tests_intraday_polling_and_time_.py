"""A/B tests: per-interval windows, counter snapshots and the time trigger trigger

Revision ID: 9de6f1cb3256
Revises: d5e81c37fa90
Create Date: 2026-09-04 17:25:32.620406

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "9de6f1cb3256"
down_revision: str | None = "d5e81c37fa90"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Apply the schema changes for this revision.

    The per-day table is dropped rather than converted. Its rows recorded whole
    calendar days, and a window is a few minutes; splitting a day into windows
    would mean inventing the moments the traffic arrived. Any test running at
    deploy time keeps its variants and exposures and starts measuring again on
    the next poll — which is the same state a freshly started test is in.
    """
    op.create_table(
        "ab_test_ad_snapshot",
        sa.Column("test_id", sa.Uuid(), nullable=False),
        sa.Column("stat_date", sa.Date(), nullable=False),
        sa.Column("views", sa.BigInteger(), server_default="0", nullable=False),
        sa.Column("clicks", sa.BigInteger(), server_default="0", nullable=False),
        sa.Column("atbs", sa.BigInteger(), server_default="0", nullable=False),
        sa.Column("orders", sa.BigInteger(), server_default="0", nullable=False),
        sa.Column("spend", sa.Numeric(precision=14, scale=2), server_default="0", nullable=False),
        sa.Column("captured_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["test_id"],
            ["ab_tests.ab_test.id"],
            name=op.f("fk_ab_test_ad_snapshot_test_id_ab_test"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("test_id", "stat_date", name=op.f("pk_ab_test_ad_snapshot")),
        schema="ab_tests",
    )
    op.create_table(
        "ab_test_variant_stat_window",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("test_id", sa.Uuid(), nullable=False),
        sa.Column("variant_id", sa.Uuid(), nullable=False),
        sa.Column("window_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("window_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column("views", sa.BigInteger(), server_default="0", nullable=False),
        sa.Column("clicks", sa.BigInteger(), server_default="0", nullable=False),
        sa.Column("atbs", sa.BigInteger(), server_default="0", nullable=False),
        sa.Column("orders", sa.BigInteger(), server_default="0", nullable=False),
        sa.Column("spend", sa.Numeric(precision=14, scale=2), server_default="0", nullable=False),
        sa.Column("currency", sa.String(length=8), server_default="RUB", nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["test_id"],
            ["ab_tests.ab_test.id"],
            name=op.f("fk_ab_test_variant_stat_window_test_id_ab_test"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["variant_id"],
            ["ab_tests.ab_test_variant.id"],
            name=op.f("fk_ab_test_variant_stat_window_variant_id_ab_test_variant"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_ab_test_variant_stat_window")),
        sa.UniqueConstraint(
            "variant_id", "window_start", name="uq_ab_test_variant_stat_window_variant_start"
        ),
        schema="ab_tests",
    )
    op.create_index(
        op.f("ix_ab_tests_ab_test_variant_stat_window_test_id"),
        "ab_test_variant_stat_window",
        ["test_id"],
        unique=False,
        schema="ab_tests",
    )
    op.create_index(
        op.f("ix_ab_tests_ab_test_variant_stat_window_variant_id"),
        "ab_test_variant_stat_window",
        ["variant_id"],
        unique=False,
        schema="ab_tests",
    )
    op.drop_index(
        op.f("ix_ab_tests_ab_test_variant_stat_daily_test_id"),
        table_name="ab_test_variant_stat_daily",
        schema="ab_tests",
    )
    op.drop_table("ab_test_variant_stat_daily", schema="ab_tests")
    op.add_column(
        "ab_test",
        sa.Column(
            "trigger_mode", sa.String(length=16), server_default="impressions", nullable=False
        ),
        schema="ab_tests",
    )
    op.add_column(
        "ab_test",
        sa.Column("slot_minutes", sa.Integer(), server_default="60", nullable=False),
        schema="ab_tests",
    )


def downgrade() -> None:
    """Revert the schema changes for this revision."""
    op.drop_column("ab_test", "slot_minutes", schema="ab_tests")
    op.drop_column("ab_test", "trigger_mode", schema="ab_tests")
    op.create_table(
        "ab_test_variant_stat_daily",
        sa.Column("variant_id", sa.UUID(), autoincrement=False, nullable=False),
        sa.Column("stat_date", sa.DATE(), autoincrement=False, nullable=False),
        sa.Column("test_id", sa.UUID(), autoincrement=False, nullable=False),
        sa.Column(
            "views",
            sa.BIGINT(),
            server_default=sa.text("'0'::bigint"),
            autoincrement=False,
            nullable=False,
        ),
        sa.Column(
            "clicks",
            sa.BIGINT(),
            server_default=sa.text("'0'::bigint"),
            autoincrement=False,
            nullable=False,
        ),
        sa.Column(
            "atbs",
            sa.BIGINT(),
            server_default=sa.text("'0'::bigint"),
            autoincrement=False,
            nullable=False,
        ),
        sa.Column(
            "orders",
            sa.BIGINT(),
            server_default=sa.text("'0'::bigint"),
            autoincrement=False,
            nullable=False,
        ),
        sa.Column(
            "spend",
            sa.NUMERIC(precision=14, scale=2),
            server_default=sa.text("'0'::numeric"),
            autoincrement=False,
            nullable=False,
        ),
        sa.Column(
            "currency",
            sa.VARCHAR(length=8),
            server_default=sa.text("'RUB'::character varying"),
            autoincrement=False,
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            postgresql.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            autoincrement=False,
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["test_id"],
            ["ab_tests.ab_test.id"],
            name=op.f("fk_ab_test_variant_stat_daily_test_id_ab_test"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["variant_id"],
            ["ab_tests.ab_test_variant.id"],
            name=op.f("fk_ab_test_variant_stat_daily_variant_id_ab_test_variant"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint(
            "variant_id", "stat_date", name=op.f("pk_ab_test_variant_stat_daily")
        ),
        schema="ab_tests",
    )
    op.create_index(
        op.f("ix_ab_tests_ab_test_variant_stat_daily_test_id"),
        "ab_test_variant_stat_daily",
        ["test_id"],
        unique=False,
        schema="ab_tests",
    )
    op.drop_index(
        op.f("ix_ab_tests_ab_test_variant_stat_window_variant_id"),
        table_name="ab_test_variant_stat_window",
        schema="ab_tests",
    )
    op.drop_index(
        op.f("ix_ab_tests_ab_test_variant_stat_window_test_id"),
        table_name="ab_test_variant_stat_window",
        schema="ab_tests",
    )
    op.drop_table("ab_test_variant_stat_window", schema="ab_tests")
    op.drop_table("ab_test_ad_snapshot", schema="ab_tests")
