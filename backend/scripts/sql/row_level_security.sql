-- Tenancy enforced by the database, not only by every query (register P2.5).
--
-- Application-level scoping already works and is tested. Its weakness is
-- structural rather than a bug: it is a promise made by *every* query, so it
-- holds exactly as long as nobody writes a new one that forgets. That failure
-- is silent and looks like working code. These policies move the promise into
-- Postgres, where a forgotten WHERE returns nothing instead of everything.
--
-- APPLY THIS TOGETHER WITH `least_privilege_role.sql`, AND NOT BEFORE IT.
-- Row-level security does not apply to a table's OWNER. While the application
-- connects as the owner — which it does today — every policy below is inert.
-- That is not a bug in the sequencing, it is the sequencing: the same property
-- is what keeps migrations and the Celery harvests working, because they run as
-- the owner and legitimately cross workspaces.
--
--   1. least_privilege_role.sql   → the app stops being the owner
--   2. this file                  → the policies start applying to it
--
-- Applied in that order, the app is scoped and everything that must cross
-- tenants still can. Applied in the other order, nothing happens until step 1,
-- which is safe but means the control is not live when you think it is.
--
--   ssh marketplace-prod
--   docker exec -i marketplace-service-postgres-1 \
--     psql -U marketplace -d marketplace < row_level_security.sql
--
-- WHAT A MISSING TENANT DOES. The policies read
-- `current_setting('app.workspace_id')` WITHOUT `missing_ok`, so a query that
-- reaches these tables with no tenant bound RAISES rather than returning zero
-- rows. That is the harder of the two behaviours to live with and it is chosen
-- on purpose: an empty result looks like "this customer has no data" and gets
-- "fixed" by removing the scoping, whereas an error is unmissable. The
-- application binds the tenant in `src/core/tenancy.py`, from the one place
-- that has validated it.
--
-- WHAT THIS DOES NOT COVER, so nobody reads it as more than it is:
--
--   * The 24 tables that carry no tenant column and are scoped transitively —
--     `monitoring.stock_snapshot` and `sales_funnel_daily` through `nm_id`,
--     `ab_tests.ab_test_variant` through `test_id`, and so on. A policy for
--     those needs a subquery per row, which is a real cost and a separate
--     decision. They remain protected by application scoping alone.
--   * The six `organization_id` tables (memberships, invitations, activation
--     codes, subscriptions, the audit log, and the workspace list itself).
--     Same mechanism, a second GUC, and worth doing next.
--   * `monitoring.sku_day_comment`, which has no tenant column at all and is
--     shared by every account by construction. See the register's P1.13 note.
--
-- `workspaces.workspace_tokens` IS covered, but only because its routes were
-- changed to make that safe. They address a workspace by URL path rather than
-- by the `X-Workspace-Id` header, so they never passed through the choke point
-- where the tenant is bound; a policy here would have made every token read and
-- write RAISE on the owner-only screens. `PathWorkspaceId` now validates the
-- path parameter against the caller's organisation and binds it, which is what
-- earns the table its policy. That ordering is the general rule for adding any
-- table below: find the routes that reach it, and check each one binds a
-- tenant before assuming the choke point is universal.
--
-- Re-runnable, and it has to be re-run after a migration adds a table to the
-- list below — a new table starts with no policy, and the failure direction
-- there is open rather than closed.

\set ON_ERROR_STOP on

DO $$
DECLARE
    target regclass;
    -- Every table carrying `workspace_id` directly. Kept as a literal list
    -- rather than discovered by column name: a table gaining a `workspace_id`
    -- should be a deliberate addition here, reviewed, not something a policy
    -- silently starts applying to.
    targets text[] := ARRAY[
        'ab_tests.ab_test',
        'finreports.balance_pin',
        'finreports.daily_settlement_report',
        'finreports.financial_report',
        'finreports.logistics_transaction',
        'finreports.pnl_sku_exclusion',
        'finreports.product_cost_price',
        'finreports.settlement_daily_rollup',
        'monitoring.product_card',
        'workspaces.workspace_tokens'
    ];
    name text;
BEGIN
    FOREACH name IN ARRAY targets
    LOOP
        target := name::regclass;

        EXECUTE format('ALTER TABLE %s ENABLE ROW LEVEL SECURITY', target);

        -- Dropped and recreated rather than patched, so re-running this file
        -- converges on exactly what it says rather than on the union of every
        -- version of it that has ever been applied.
        EXECUTE format('DROP POLICY IF EXISTS tenant_isolation ON %s', target);

        -- USING governs what the role can SEE (select/update/delete); WITH
        -- CHECK governs what it can WRITE. Both, because a role that could
        -- insert a row into another tenant's workspace would be a leak in the
        -- other direction — one that application scoping is just as capable of
        -- forgetting.
        EXECUTE format(
            'CREATE POLICY tenant_isolation ON %s FOR ALL '
            'USING (workspace_id = current_setting(''app.workspace_id'')::uuid) '
            'WITH CHECK (workspace_id = current_setting(''app.workspace_id'')::uuid)',
            target
        );
    END LOOP;
END
$$;

SELECT
    n.nspname || '.' || c.relname AS table_name,
    c.relrowsecurity              AS rls_enabled,
    (SELECT count(*) FROM pg_policy p WHERE p.polrelid = c.oid) AS policies
FROM pg_class c
JOIN pg_namespace n ON n.oid = c.relnamespace
WHERE c.relrowsecurity
ORDER BY 1;
