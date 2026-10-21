"""Hand-uploaded weekly reports: ``finreports.settlement_upload`` and its row ids.

A seller can upload the weekly report WB already shows in its seller portal while the
API holds it back; its rows stand in the P&L until the API serves the same
report. See :mod:`src.modules.finreports.models.settlement_upload`.

``upload_row_seq`` supplies those rows' ``rrd_id``, negated: a real WB id is
positive, so a negative one marks a row from a file wherever it is read.

Born with the same ``tenant_isolation`` policy ``row_level_security.sql``
creates, and the truncate guard every table carries. Only the worker, the table
owner, draws from the sequence, so no grant goes with it.

Revision ID: e8b3d5a1c962
Revises: c4e9a2f71d38
Create Date: 2026-10-12
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision: str = "e8b3d5a1c962"
down_revision: str | None = "c4e9a2f71d38"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    """Create the sequence and the table, guard it, and police it."""
    op.execute("CREATE SEQUENCE finreports.upload_row_seq")
    op.create_table(
        "settlement_upload",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("uploaded_by", sa.Uuid(), nullable=False),
        sa.Column("filename", sa.String(255), nullable=False, server_default=""),
        sa.Column("report_id", sa.BigInteger(), nullable=True),
        sa.Column("date_from", sa.Date(), nullable=True),
        sa.Column("date_to", sa.Date(), nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="queued"),
        sa.Column("message", sa.Text(), nullable=False, server_default=""),
        sa.Column("rows_total", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("rows_written", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("for_pay_sum", sa.Numeric(18, 2), nullable=True),
        sa.Column("digest", sa.String(32), nullable=False, server_default=""),
        sa.Column("payload", sa.LargeBinary(), nullable=True),
        sa.Column(
            "uploaded_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        schema="finreports",
    )
    op.create_index(
        op.f("ix_finreports_settlement_upload_workspace_id"),
        "settlement_upload",
        ["workspace_id"],
        schema="finreports",
    )
    op.execute(
        "CREATE TRIGGER guard_against_truncate "
        "BEFORE TRUNCATE ON finreports.settlement_upload "
        "FOR EACH STATEMENT EXECUTE FUNCTION organizations.guard_against_truncate()"
    )
    op.execute("ALTER TABLE finreports.settlement_upload ENABLE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY tenant_isolation ON finreports.settlement_upload FOR ALL "
        "USING (workspace_id = current_setting('app.workspace_id')::uuid) "
        "WITH CHECK (workspace_id = current_setting('app.workspace_id')::uuid)"
    )


def downgrade() -> None:
    """Drop the table and the sequence; uploaded rows, if any, stay as rows."""
    op.drop_table("settlement_upload", schema="finreports")
    op.execute("DROP SEQUENCE finreports.upload_row_seq")
