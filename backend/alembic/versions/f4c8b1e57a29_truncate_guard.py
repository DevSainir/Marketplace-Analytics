"""truncate_guard: the data schemas refuse an unannounced TRUNCATE

Revision ID: f4c8b1e57a29
Revises: d1a4f7c92b60
Create Date: 2026-09-10

On 2026-09-10 at 01:30 UTC the nightly end-to-end tier — which runs on the
production host's own runner — called ``backend/scripts/load_seed.sh``, and that
script reached for a postgres container by NAME. The name it defaulted to was
production's. Every table in ``monitoring`` was truncated and replaced with the
browser-tier seed fixture; the pins, the per-day comments and actions, and
seven weeks of harvested history went with it.

The script has been fixed. This is the layer underneath it, for the next caller
that has not been: the data schemas now refuse TRUNCATE outright unless the
session says, in that same transaction, that it means it:

    SET LOCAL app.allow_truncate = 'on';

Nothing in the application truncates anything, so there is no legitimate caller
to break — the fixture loader is the one, and it opts in explicitly. **Every
attempt is written to organizations.audit_log first**, allowed or refused,
because the second half of that morning was spent proving from filenode
timestamps and tuple counters what one audit row would have said outright.

The trigger is statement-level: TRUNCATE fires no row-level trigger. It is
attached to every table in ``monitoring`` and ``finreports`` that exists today;
a table added later gets its own guard from
``tests/integration/test_truncate_guard.py``, which fails until it does.
"""

from __future__ import annotations

from alembic import op

# revision identifiers, used by Alembic.
revision = "f4c8b1e57a29"
down_revision = "d1a4f7c92b60"
branch_labels = None
depends_on = None

#: The schemas holding harvested and derived data — the ones whose loss is not
#: recoverable from WB. `workspaces`, `users` and `organizations` are left out
#: deliberately: audit_log already refuses truncation, and the rest are small,
#: written by hand and restored from a dump in minutes.
_GUARDED_SCHEMAS: tuple[str, ...] = ("monitoring", "finreports")

_TRIGGER = "guard_against_truncate"

# `current_setting(..., true)` returns NULL rather than raising when the GUC was
# never set, which is the normal case and must not itself be an error.
#
# The INSERT runs before the RAISE, and a raise rolls the whole statement back —
# including this row. That is deliberate: a refused truncate leaves the postgres
# log entry (RAISE writes there whatever happens to the transaction) while an
# ALLOWED one leaves the durable audit row, which is the case worth keeping.
_GUARD_FUNCTION = """
CREATE OR REPLACE FUNCTION organizations.guard_against_truncate()
RETURNS trigger
LANGUAGE plpgsql
AS $$
DECLARE
    allowed boolean := coalesce(current_setting('app.allow_truncate', true), '') = 'on';
BEGIN
    INSERT INTO organizations.audit_log (
        id, occurred_at, event, actor_email, target_type, target_id,
        ip_address, metadata
    )
    VALUES (
        gen_random_uuid(),
        now(),
        'db.truncate',
        current_user,
        'table',
        TG_TABLE_SCHEMA || '.' || TG_TABLE_NAME,
        host(coalesce(inet_client_addr(), '127.0.0.1'::inet)),
        jsonb_build_object(
            'allowed', allowed,
            'application_name', current_setting('application_name', true),
            'backend_pid', pg_backend_pid(),
            'session_user', session_user
        )
    );

    IF NOT allowed THEN
        RAISE EXCEPTION
            'TRUNCATE on %.% is blocked. This table holds harvested data that '
            'cannot be re-fetched from WB. A caller that means it says '
            '`SET LOCAL app.allow_truncate = ''on''` in the same transaction.',
            TG_TABLE_SCHEMA, TG_TABLE_NAME
        USING ERRCODE = 'insufficient_privilege';
    END IF;

    RAISE WARNING 'TRUNCATE allowed on %.% by % (pid %, application %)',
        TG_TABLE_SCHEMA, TG_TABLE_NAME, current_user, pg_backend_pid(),
        current_setting('application_name', true);

    RETURN NULL;
END;
$$
"""

_ATTACH = """
DO $$
DECLARE
    target record;
BEGIN
    FOR target IN
        SELECT schemaname, tablename FROM pg_tables WHERE schemaname = ANY(%s)
    LOOP
        EXECUTE format('DROP TRIGGER IF EXISTS %s ON %%I.%%I',
                       target.schemaname, target.tablename);
        EXECUTE format(
            'CREATE TRIGGER %s BEFORE TRUNCATE ON %%I.%%I '
            'FOR EACH STATEMENT EXECUTE FUNCTION organizations.guard_against_truncate()',
            target.schemaname, target.tablename);
    END LOOP;
END $$
"""

_DETACH = """
DO $$
DECLARE
    target record;
BEGIN
    FOR target IN
        SELECT schemaname, tablename FROM pg_tables WHERE schemaname = ANY(%s)
    LOOP
        EXECUTE format('DROP TRIGGER IF EXISTS %s ON %%I.%%I',
                       target.schemaname, target.tablename);
    END LOOP;
END $$
"""


def _schema_array() -> str:
    """Render the guarded schemas as a SQL text[] literal."""
    return "ARRAY[" + ", ".join(f"'{schema}'" for schema in _GUARDED_SCHEMAS) + "]"


def upgrade() -> None:
    """Install the guard function and attach it to every data table."""
    op.execute(_GUARD_FUNCTION)
    op.execute(_ATTACH % (_schema_array(), _TRIGGER, _TRIGGER))


def downgrade() -> None:
    """Detach the guard from every data table and drop the function."""
    op.execute(_DETACH % (_schema_array(), _TRIGGER))
    op.execute("DROP FUNCTION IF EXISTS organizations.guard_against_truncate()")
