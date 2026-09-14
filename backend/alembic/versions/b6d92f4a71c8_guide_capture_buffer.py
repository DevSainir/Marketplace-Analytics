"""guide: the capture buffer for WB data nobody uses yet

Revision ID: b6d92f4a71c8
Revises: a3f81c2e57d4
Create Date: 2026-09-12

Two tables in a new ``guide`` schema. ``guide_record`` is
``(source, workspace, key) -> jsonb``: WB's answer stored verbatim, because the
feeds it holds are captured before anyone has decided what to ask of them, and
typing them now would mean inventing their shape twice. ``guide_run`` is one
watermark row per source and tenant, so a walk resumes where it stopped and a
failed walk does not step over its own gap.

Both get the truncate guard. That is not boilerplate: the whole reason this
module exists is that WB deletes these feeds on a schedule — the return claims
after fourteen days, the orders feed after a hundred and eighty-eight — so a
stray TRUNCATE here destroys rows that cannot be re-fetched from anywhere, which
is exactly the class of loss the guard was written for on 2026-09-10.
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b6d92f4a71c8"
down_revision: str | None = "a3f81c2e57d4"
branch_labels: None = None
depends_on: None = None

_SCHEMA = "guide"
_TABLES = ("guide_record", "guide_run")
_TRIGGER = "guard_against_truncate"


def upgrade() -> None:
    """Create the schema, the two tables and their truncate guards."""
    op.execute(f"CREATE SCHEMA IF NOT EXISTS {_SCHEMA}")

    op.create_table(
        "guide_record",
        sa.Column("source", sa.String(length=32), nullable=False),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("record_key", sa.String(length=160), nullable=False),
        sa.Column("recorded_for", sa.Date(), nullable=True),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "captured_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("source", "workspace_id", "record_key", name="pk_guide_record"),
        schema=_SCHEMA,
    )
    op.create_index(
        "ix_guide_record_source_workspace_day",
        "guide_record",
        ["source", "workspace_id", "recorded_for"],
        schema=_SCHEMA,
    )

    op.create_table(
        "guide_run",
        sa.Column("source", sa.String(length=32), nullable=False),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("cursor", sa.String(length=64), nullable=True),
        sa.Column("captured_through", sa.Date(), nullable=True),
        sa.Column("last_status", sa.String(length=16), nullable=False),
        sa.Column("rows", sa.Integer(), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column(
            "last_run_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("source", "workspace_id", name="pk_guide_run"),
        schema=_SCHEMA,
    )

    # The guard function itself was created by f4c8b1e57a29; this only attaches
    # it. A statement-level trigger, because TRUNCATE fires no row-level one.
    for table in _TABLES:
        op.execute(
            f"CREATE TRIGGER {_TRIGGER} BEFORE TRUNCATE ON {_SCHEMA}.{table} "
            f"FOR EACH STATEMENT EXECUTE FUNCTION organizations.guard_against_truncate()"
        )


def downgrade() -> None:
    """Drop both tables and the schema."""
    for table in _TABLES:
        op.execute(f"DROP TRIGGER IF EXISTS {_TRIGGER} ON {_SCHEMA}.{table}")
    op.drop_index("ix_guide_record_source_workspace_day", table_name="guide_record", schema=_SCHEMA)
    op.drop_table("guide_run", schema=_SCHEMA)
    op.drop_table("guide_record", schema=_SCHEMA)
    op.execute(f"DROP SCHEMA IF EXISTS {_SCHEMA}")
