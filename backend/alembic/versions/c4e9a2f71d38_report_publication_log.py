"""The publication log: when WB's API first named each report.

WB shows a report on its own site hours before ``sales-reports/list`` names it,
and nothing on file said when the API caught up — ``financial_report.harvested_at``
is when the rows were booked, which is later still. One row per report, written
once from the first list answer that named it, with the last answer before that
which did not; see :mod:`src.modules.finreports.models.report_publication`.

Row-level security is switched on here, with the same policy under the same name
and expression as ``row_level_security.sql`` creates, so the table is born
policed rather than waiting for the operator's next run of the script; the
schema's default privileges already grant it to the application role.

Revision ID: c4e9a2f71d38
Revises: d7b3e1a95c20
Create Date: 2026-10-12
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision: str = "c4e9a2f71d38"
down_revision: str | None = "d7b3e1a95c20"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    """Create ``finreports.report_publication``, guard it, and police it."""
    op.create_table(
        "report_publication",
        sa.Column("report_id", sa.BigInteger(), primary_key=True),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("period", sa.String(8), nullable=False),
        sa.Column("date_from", sa.Date(), nullable=True),
        sa.Column("date_to", sa.Date(), nullable=True),
        sa.Column("create_date", sa.Date(), nullable=True),
        sa.Column("first_listed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("prior_list_at", sa.DateTime(timezone=True), nullable=True),
        schema="finreports",
    )
    op.create_index(
        op.f("ix_finreports_report_publication_workspace_id"),
        "report_publication",
        ["workspace_id"],
        schema="finreports",
    )
    op.execute(
        "CREATE TRIGGER guard_against_truncate "
        "BEFORE TRUNCATE ON finreports.report_publication "
        "FOR EACH STATEMENT EXECUTE FUNCTION organizations.guard_against_truncate()"
    )
    op.execute("ALTER TABLE finreports.report_publication ENABLE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY tenant_isolation ON finreports.report_publication FOR ALL "
        "USING (workspace_id = current_setting('app.workspace_id')::uuid) "
        "WITH CHECK (workspace_id = current_setting('app.workspace_id')::uuid)"
    )


def downgrade() -> None:
    """Drop the table; its trigger and policy go with it."""
    op.drop_table("report_publication", schema="finreports")
