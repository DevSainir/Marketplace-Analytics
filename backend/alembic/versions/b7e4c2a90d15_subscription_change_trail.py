"""subscription_change_trail: every change to a subscription term is audited

Revision ID: b7e4c2a90d15
Revises: a6d3f08c2e71
Create Date: 2026-10-06

A customer's term ended on 05.10 although it had been extended once by
hand: the extension was an ``UPDATE`` in psql, which bypassed the ORM's
``updated_at`` and wrote no audit row, so nothing in the database showed it
had happened. This trigger records every UPDATE and DELETE of
``organizations.subscriptions`` in ``organizations.audit_log`` as
``SUBSCRIPTION_CHANGED``, with the term before and after, and keeps
``updated_at`` honest for raw SQL too. Rationale in
``src/modules/organizations/models/subscription.py``, which issues the same DDL
for ``create_all``.
"""

from __future__ import annotations

from alembic import op

revision: str = "b7e4c2a90d15"
down_revision: str | None = "a6d3f08c2e71"
branch_labels: str | None = None
depends_on: str | None = None

_FUNCTION = """
CREATE OR REPLACE FUNCTION organizations.record_subscription_change()
RETURNS trigger
LANGUAGE plpgsql
AS $$
DECLARE
    actor text := nullif(current_setting('app.audit_actor', true), '');
    after_term jsonb := '{}'::jsonb;
BEGIN
    IF TG_OP = 'UPDATE' THEN
        IF NEW.expires_at IS NOT DISTINCT FROM OLD.expires_at
           AND NEW.started_at IS NOT DISTINCT FROM OLD.started_at
           AND NEW.grace_days IS NOT DISTINCT FROM OLD.grace_days
           AND NEW.max_workspaces IS NOT DISTINCT FROM OLD.max_workspaces
           AND NEW.max_managers IS NOT DISTINCT FROM OLD.max_managers THEN
            RETURN NEW;
        END IF;
        NEW.updated_at := now();
        after_term := jsonb_build_object(
            'expires_at', NEW.expires_at,
            'grace_days', NEW.grace_days,
            'max_workspaces', NEW.max_workspaces,
            'max_managers', NEW.max_managers
        );
    END IF;

    INSERT INTO organizations.audit_log (
        id, occurred_at, event, actor_email, organization_id,
        target_type, target_id, metadata
    )
    VALUES (
        gen_random_uuid(),
        now(),
        'SUBSCRIPTION_CHANGED',
        actor,
        OLD.organization_id,
        'subscription',
        OLD.id::text,
        after_term || jsonb_build_object(
            'operation', lower(TG_OP),
            'previous_expires_at', OLD.expires_at,
            'previous_grace_days', OLD.grace_days,
            'previous_max_workspaces', OLD.max_workspaces,
            'previous_max_managers', OLD.max_managers,
            'source', CASE WHEN actor IS NULL THEN 'sql' ELSE 'tool' END,
            'db_user', session_user,
            'application_name', current_setting('application_name', true)
        )
    );

    IF TG_OP = 'DELETE' THEN
        RETURN OLD;
    END IF;
    RETURN NEW;
END;
$$;
"""

_TRIGGER = (
    "CREATE TRIGGER subscription_change_trail "
    "BEFORE UPDATE OR DELETE ON organizations.subscriptions "
    "FOR EACH ROW EXECUTE FUNCTION organizations.record_subscription_change()"
)


def upgrade() -> None:
    """Install the trail function and attach it to the subscriptions table."""
    op.execute(_FUNCTION)
    op.execute(_TRIGGER)


def downgrade() -> None:
    """Detach the trail and drop its function."""
    op.execute("DROP TRIGGER IF EXISTS subscription_change_trail ON organizations.subscriptions")
    op.execute("DROP FUNCTION IF EXISTS organizations.record_subscription_change()")
