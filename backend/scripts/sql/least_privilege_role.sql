-- A database role for the application that cannot reshape the database.
-- Register P2.4, and the thing that finishes P1.3.
--
-- TODAY the app connects as the role that OWNS every table. That means SQL
-- injection, a compromised container or a bug in our own code can do anything
-- the schema's author can: drop a table, disable a trigger, rewrite history.
-- It is also why the audit log's append-only guarantee is currently carried by
-- a trigger alone — the `REVOKE ... FROM PUBLIC` in its migration is real, but
-- an owner is not affected by it, so with one role it is documentation. Give
-- the app a role of its own and the REVOKE becomes the control it was written
-- to be.
--
-- WHAT THIS GRANTS, and the three deliberate exceptions:
--
--   * SELECT/INSERT/UPDATE/DELETE on every table in our seven schemas, and USAGE
--     on their sequences. That is the whole of what the application does.
--     (`heatmap` is the seventh, added 2026-09-28; its migration grants the same
--     set itself, so the heatmap works on deploy without waiting for a re-run.)
--   * NOT the `guide` schema, which is the eighth and is left out on purpose.
--     The capture buffer is written by Celery tasks — which connect as the
--     owner — and read by no route at all; that module has no router. A grant
--     there would be privilege the application has no use for, and the failure
--     direction without it is closed: a route or a probe that reaches those
--     tables is refused rather than served another tenant's rows. Its tables
--     already carry policies in `row_level_security.sql`, so if the buffer ever
--     gains a reader, adding the schema to the loop below is the whole change.
--   * NOT `organizations.audit_log`: INSERT and SELECT only. An audit trail the
--     application can edit is one an attacker running the application can edit.
--   * NO DDL, no ownership, no superuser. Migrations keep running as the owner,
--     which is correct — they are a deploy-time act with a diff and a review,
--     not something a request should be able to do.
--
-- HOW TO APPLY. The password is yours to choose and never appears here; pass it
-- with -v so it does not reach the file or the shell history of anyone reading
-- this later:
--
--   ssh marketplace-prod
--   docker exec -i marketplace-service-postgres-1 \
--     psql -U marketplace -d marketplace \
--          -v app_password="$(read -rs P; echo "$P")" \
--          < least_privilege_role.sql
--
-- Then point the API at it by setting `APP_POSTGRES_USER=marketplace_app` and
-- `APP_POSTGRES_PASSWORD=…` in backend/.env, and recreate the api services.
--
-- DO NOT change `POSTGRES_USER`. An earlier version of this comment said to,
-- and it was wrong: every service in docker-compose.yml shares one `.env`, so
-- that switches `migrate` — which runs `alembic upgrade head` and would lose
-- the right to — along with `worker` and `beat`, whose nightly harvests cross
-- every workspace and bind no tenant, so they would begin raising the moment
-- row_level_security.sql is applied. The compose file therefore gives the api
-- services their own two variables; unset, they fall through to the shared
-- value and nothing differs.
--
-- Re-runnable. Every statement is idempotent, because the grants have to be
-- re-applied after a migration creates a new table (see the note at the foot).

\set ON_ERROR_STOP on

-- --------------------------------------------------------------------------
-- The role
-- --------------------------------------------------------------------------
-- psql does NOT substitute `:variables` inside a dollar-quoted block — the text
-- between $$ and $$ reaches the server verbatim, so an earlier version of this
-- that built the CREATE ROLE inside a DO block failed with `syntax error at or
-- near ":"`. The password therefore has to be used OUTSIDE any dollar quoting.
--
-- `\gexec` runs whatever the query returns as SQL, so the CREATE happens only
-- when the role is absent and the whole file stays re-runnable.
SELECT 'CREATE ROLE marketplace_app LOGIN'
WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'marketplace_app')
\gexec

-- Idempotent, and the one statement that needs the variable: setting the
-- password on every run keeps the role and `.env` from drifting apart.
--
-- With `log_statement` off around it: production logs every DDL statement
-- (added 2026-09-10, after this file's first run), ALTER ROLE is DDL, and a
-- re-run would otherwise write the app's password in clear to the container
-- log and on to Loki.
SET log_statement = 'none';
ALTER ROLE marketplace_app LOGIN PASSWORD :'app_password';
RESET log_statement;

-- Explicitly not a superuser and unable to create anything, in case the role
-- already existed with more than it should.
ALTER ROLE marketplace_app NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS;

GRANT CONNECT ON DATABASE marketplace TO marketplace_app;

-- --------------------------------------------------------------------------
-- Read/write on the data, nothing on its shape
-- --------------------------------------------------------------------------
DO $$
DECLARE
    target_schema text;
BEGIN
    FOREACH target_schema IN ARRAY ARRAY[
        'auth', 'monitoring', 'workspaces', 'finreports', 'ab_tests', 'organizations',
        'heatmap'
    ]
    LOOP
        EXECUTE format('GRANT USAGE ON SCHEMA %I TO marketplace_app', target_schema);
        EXECUTE format(
            'GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA %I TO marketplace_app',
            target_schema
        );
        EXECUTE format(
            'GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA %I TO marketplace_app',
            target_schema
        );
        -- So a table added by a LATER migration is covered without anyone
        -- remembering to re-run this. Default privileges apply to objects the
        -- OWNER creates, which is exactly who migrations run as.
        EXECUTE format(
            'ALTER DEFAULT PRIVILEGES FOR ROLE marketplace IN SCHEMA %I '
            'GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO marketplace_app',
            target_schema
        );
        EXECUTE format(
            'ALTER DEFAULT PRIVILEGES FOR ROLE marketplace IN SCHEMA %I '
            'GRANT USAGE, SELECT ON SEQUENCES TO marketplace_app',
            target_schema
        );
    END LOOP;
END
$$;

-- --------------------------------------------------------------------------
-- The audit log is append-only for the application, by grant and not only by
-- trigger. Applied AFTER the loop above, which granted it the full set.
--
-- Both layers stay: the grant is what stops the application, the trigger is
-- what stops anyone who reaches the database as the owner. Neither makes the
-- other redundant.
-- --------------------------------------------------------------------------
REVOKE UPDATE, DELETE, TRUNCATE ON organizations.audit_log FROM marketplace_app;
ALTER DEFAULT PRIVILEGES FOR ROLE marketplace IN SCHEMA organizations
    REVOKE UPDATE, DELETE ON TABLES FROM marketplace_app;
-- ...but every OTHER organizations table does need the full set, so put it back
-- for the ones that exist. (Default privileges cannot be expressed per-table,
-- which is why this is a revoke-then-restore rather than a narrower grant.)
GRANT UPDATE, DELETE ON ALL TABLES IN SCHEMA organizations TO marketplace_app;
REVOKE UPDATE, DELETE, TRUNCATE ON organizations.audit_log FROM marketplace_app;

-- --------------------------------------------------------------------------
-- After a migration that creates a table in `organizations`, re-run this file:
-- the default privileges above deliberately withhold UPDATE/DELETE in that one
-- schema, so a new table there starts append-only until this restores it. That
-- is the safe direction to be wrong in — a missing UPDATE is a loud error at
-- the first write, where a missing REVOKE would be silence.
-- --------------------------------------------------------------------------

SELECT 'marketplace_app configured. Now set APP_POSTGRES_USER / APP_POSTGRES_PASSWORD in backend/.env (NOT POSTGRES_USER) and recreate the api services.' AS result;
