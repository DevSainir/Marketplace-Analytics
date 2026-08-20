"""A/B tests: rotations, photo variants, exposures and attributed ad days

Revision ID: 865b8a783a85
Revises: b4f1e7c92d05
Create Date: 2026-08-20 10:54:09.786142

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "865b8a783a85"
down_revision: str | None = "b4f1e7c92d05"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Apply the schema changes for this revision."""
    op.create_table(
        "ab_test",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("nm_id", sa.BigInteger(), nullable=False),
        sa.Column("vendor_code", sa.String(length=255), server_default="", nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("status", sa.String(length=16), server_default="draft", nullable=False),
        sa.Column("impression_budget", sa.Integer(), server_default="10000", nullable=False),
        sa.Column("active_variant_id", sa.Uuid(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.workspaces.id"],
            name=op.f("fk_ab_test_workspace_id_workspaces"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_ab_test")),
        schema="ab_tests",
    )
    op.create_index(
        op.f("ix_ab_tests_ab_test_nm_id"), "ab_test", ["nm_id"], unique=False, schema="ab_tests"
    )
    op.create_index(
        op.f("ix_ab_tests_ab_test_status"), "ab_test", ["status"], unique=False, schema="ab_tests"
    )
    op.create_index(
        op.f("ix_ab_tests_ab_test_workspace_id"),
        "ab_test",
        ["workspace_id"],
        unique=False,
        schema="ab_tests",
    )
    op.create_table(
        "ab_test_variant",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("test_id", sa.Uuid(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("image_path", sa.String(length=512), nullable=False),
        sa.Column("image_sha256", sa.String(length=64), nullable=False),
        sa.Column(
            "content_type", sa.String(length=64), server_default="image/jpeg", nullable=False
        ),
        sa.Column("original_filename", sa.String(length=255), server_default="", nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["test_id"],
            ["ab_tests.ab_test.id"],
            name=op.f("fk_ab_test_variant_test_id_ab_test"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_ab_test_variant")),
        sa.UniqueConstraint("test_id", "position", name="uq_ab_test_variant_test_position"),
        schema="ab_tests",
    )
    op.create_index(
        op.f("ix_ab_tests_ab_test_variant_test_id"),
        "ab_test_variant",
        ["test_id"],
        unique=False,
        schema="ab_tests",
    )
    # Added only now: ab_test and ab_test_variant reference each other, so the
    # constraint cannot exist while the second table is still missing.
    op.create_foreign_key(
        op.f("fk_ab_test_active_variant_id_ab_test_variant"),
        "ab_test",
        "ab_test_variant",
        ["active_variant_id"],
        ["id"],
        source_schema="ab_tests",
        referent_schema="ab_tests",
        ondelete="SET NULL",
    )
    op.create_table(
        "ab_test_variant_exposure",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("test_id", sa.Uuid(), nullable=False),
        sa.Column("variant_id", sa.Uuid(), nullable=False),
        sa.Column("activated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deactivated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("wb_photo_number", sa.Integer(), server_default="1", nullable=False),
        sa.ForeignKeyConstraint(
            ["test_id"],
            ["ab_tests.ab_test.id"],
            name=op.f("fk_ab_test_variant_exposure_test_id_ab_test"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["variant_id"],
            ["ab_tests.ab_test_variant.id"],
            name=op.f("fk_ab_test_variant_exposure_variant_id_ab_test_variant"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_ab_test_variant_exposure")),
        schema="ab_tests",
    )
    op.create_index(
        op.f("ix_ab_tests_ab_test_variant_exposure_test_id"),
        "ab_test_variant_exposure",
        ["test_id"],
        unique=False,
        schema="ab_tests",
    )
    op.create_index(
        op.f("ix_ab_tests_ab_test_variant_exposure_variant_id"),
        "ab_test_variant_exposure",
        ["variant_id"],
        unique=False,
        schema="ab_tests",
    )
    op.create_table(
        "ab_test_variant_stat_daily",
        sa.Column("variant_id", sa.Uuid(), nullable=False),
        sa.Column("stat_date", sa.Date(), nullable=False),
        sa.Column("test_id", sa.Uuid(), nullable=False),
        sa.Column("views", sa.BigInteger(), server_default="0", nullable=False),
        sa.Column("clicks", sa.BigInteger(), server_default="0", nullable=False),
        sa.Column("atbs", sa.BigInteger(), server_default="0", nullable=False),
        sa.Column("orders", sa.BigInteger(), server_default="0", nullable=False),
        sa.Column("spend", sa.Numeric(precision=14, scale=2), server_default="0", nullable=False),
        sa.Column("currency", sa.String(length=8), server_default="RUB", nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
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


def downgrade() -> None:
    """Revert the schema changes for this revision."""
    op.drop_index(
        op.f("ix_ab_tests_ab_test_variant_stat_daily_test_id"),
        table_name="ab_test_variant_stat_daily",
        schema="ab_tests",
    )
    op.drop_table("ab_test_variant_stat_daily", schema="ab_tests")
    op.drop_index(
        op.f("ix_ab_tests_ab_test_variant_exposure_variant_id"),
        table_name="ab_test_variant_exposure",
        schema="ab_tests",
    )
    op.drop_index(
        op.f("ix_ab_tests_ab_test_variant_exposure_test_id"),
        table_name="ab_test_variant_exposure",
        schema="ab_tests",
    )
    op.drop_table("ab_test_variant_exposure", schema="ab_tests")
    op.drop_constraint(
        op.f("fk_ab_test_active_variant_id_ab_test_variant"),
        "ab_test",
        schema="ab_tests",
        type_="foreignkey",
    )
    op.drop_index(
        op.f("ix_ab_tests_ab_test_variant_test_id"), table_name="ab_test_variant", schema="ab_tests"
    )
    op.drop_table("ab_test_variant", schema="ab_tests")
    op.drop_index(op.f("ix_ab_tests_ab_test_workspace_id"), table_name="ab_test", schema="ab_tests")
    op.drop_index(op.f("ix_ab_tests_ab_test_status"), table_name="ab_test", schema="ab_tests")
    op.drop_index(op.f("ix_ab_tests_ab_test_nm_id"), table_name="ab_test", schema="ab_tests")
    op.drop_table("ab_test", schema="ab_tests")
