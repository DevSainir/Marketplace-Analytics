# Security design

Last reviewed: 2026-10-21

What protections this service has and how each one is enforced. Paths are relative to the
repository root. The standing checklist that keeps new code inside this design is the `security`
skill (`.claude/skills/security/SKILL.md`, with `references/codebase-controls.md` as the map of
where every control lives).

## Threat model

The service holds other companies' commercial data — settlement reports, cost prices, margins,
advertising spend — and the WB API tokens that authenticate against their live seller accounts.
The threats that shape the design, in order of cost:

1. **One tenant reading another tenant's data.** A tenancy bug is not a defect here, it is a
   disclosure of one seller's commercial position to another.
2. **A stolen session or credential** — a replayed refresh token, a guessed password, a WB token
   lifted from a log, a backup or an error report.
3. **A role doing more than it should** — a read-only manager changing data, a member
   administering tokens, the application itself reshaping its own database.
4. **Resource exhaustion** — large uploads, decompression bombs, unbounded labels or rows,
   request floods against the auth surface.
5. **Silent failure of a control** — a limiter that fails open without anyone knowing, a backup
   nobody can decrypt.

The governing rule: **a control that cannot be forgotten beats one that must be remembered.**
Wherever possible a protection is enforced by PostgreSQL, by a type, or by a test that walks the
real application, rather than by review.

## Tenancy

Every seller account is a *workspace*; workspaces belong to an *organisation*. Tenancy is
enforced twice, independently.

### In every query

* The workspace of a request comes from one dependency: `CurrentWorkspaceId`
  (`backend/src/modules/workspaces/deps.py`) validates the `X-Workspace-Id` header against the
  caller's own organisation; `PathWorkspaceId` does the same for routes that take the workspace
  from the URL path. `WorkspaceSku` (`backend/src/modules/monitoring/deps/__init__.py`) proves a
  path `nm_id` belongs to that workspace.
* Cross-SKU aggregates go through `workspace_sku_select(workspace_id)`
  (`backend/src/modules/monitoring/repos/base.py`), a semijoin through `product_card`. A fact row
  whose SKU has no card belongs to nobody and reaches no statement.
* Every loader in `backend/src/modules/monitoring/contract.py` takes a required keyword-only
  `workspace_id`. `backend/tests/integration/monitoring/test_export_loaders_are_scoped.py`
  reflects over the contract and fails if a loader is added without one, given a default, or made
  positional.
* Foreign resources answer **404, not 403**, so a response never confirms that another tenant's
  object exists.

### In PostgreSQL: row-level security

`backend/scripts/sql/row_level_security.sql` enables RLS on every table that carries a
`workspace_id` column and installs one `tenant_isolation` policy per table:

```sql
USING      (workspace_id = current_setting('app.workspace_id')::uuid)
WITH CHECK (workspace_id = current_setting('app.workspace_id')::uuid)
```

* `USING` limits what the role can see; `WITH CHECK` stops it writing a row into another
  workspace — a leak in the other direction that application scoping could equally forget.
* `current_setting` is called **without** `missing_ok`, so a query that reaches a covered table
  with no tenant bound **raises** instead of returning zero rows. An empty result looks like
  "this customer has no data" and invites someone to remove the scoping; an error does not.
* The tenant is bound per transaction by `set_workspace_context`
  (`backend/src/core/tenancy.py`), called only from the two workspace dependencies above, after
  validation. It uses `set_config(name, value, true)` — a bound parameter, never interpolated SQL,
  and transaction-local, so a pooled connection cannot carry one caller's tenant into the next
  caller's query. `ROW_LEVEL_SECURITY_ENABLED` turns the binding on.
* The table list is a literal, reviewed list rather than discovered by column name: a table
  gaining a `workspace_id` should be a deliberate addition. Tables scoped transitively (through
  `nm_id` or a parent id) remain protected by application scoping.
* Any refusal is counted at the engine (`backend/src/core/observability/rls_watch.py`, SQLSTATE
  `42501`) and raises the `RowLevelSecurityViolation` alert on the first occurrence: it means a
  code path reached tenant data without passing the choke point.

Pinned by `backend/tests/integration/core/test_row_level_security.py` (an unscoped select sees
only the bound workspace, another tenant's row is invisible even when named, no bound workspace
raises, cross-workspace writes are refused, the owner still crosses workspaces) and by
`backend/tests/unit/core/test_every_covered_route_binds_a_tenant.py`, which walks every route of
every module owning a covered table and fails if its dependency tree resolves no workspace binder.

### The application role does not own its tables

RLS does not apply to a table's owner, so the policies only mean something once the API stops
connecting as one. `backend/scripts/sql/least_privilege_role.sql` creates `marketplace_app`:

* `NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS`, no ownership, no DDL;
* `SELECT/INSERT/UPDATE/DELETE` on the application's schemas, with default privileges so tables
  created by later migrations are covered;
* `organizations.audit_log` is **INSERT and SELECT only** — an audit trail the application can
  edit is one an attacker running the application can edit;
* the password is passed with `psql -v` and set with `log_statement` switched off around the
  `ALTER ROLE`, so it never reaches the file, shell history or the database log
  (`backend/tests/unit/core/test_sql_scripts_do_not_log_passwords.py`).

The order is the role first, then the policies; each script's header explains why. Migrations,
the Celery worker and backups keep running as the owner, because they legitimately cross tenants.
Only the API services get `APP_POSTGRES_USER` — pinned by
`backend/tests/unit/core/test_only_the_api_uses_the_restricted_role.py` — and
`backend/tests/integration/core/test_least_privilege_role.py` proves the role can read and write
but cannot drop or create a table or disable the audit trigger.

### Background work and ad-hoc probes

* A Celery task has no caller, so it cannot use the access guards. Fleet-wide harvests take their
  tenants from `load_workspace_token_bundles`, which already drops organisations past their
  subscription grace window — the one deliberate cross-tenant reader, and no request path may
  call it.
* An ad-hoc look at stored data never opens its own session. `backend/scripts/diagnose.py` hands
  the probe a session from `backend/src/core/diagnostics.py` that is `SET TRANSACTION READ ONLY`,
  `SET LOCAL ROLE marketplace_app`, and bound to one fixed workspace — with no parameter to name a
  different one. Pinned by `backend/tests/unit/core/test_diagnostic_gate.py` and
  `backend/tests/integration/core/test_diagnostic_gate_is_enforced.py`.

## Access control

Authorisation is a ladder of guards in `backend/src/modules/organizations/contract.py`, each
narrower than the last: `CurrentAccess` (a valid token) → `MemberAccess` (member of an
organisation with a live subscription — also the paywall) → `WritingAccess` (a role that writes)
→ `OwnerAccess` (workspaces, WB tokens, members, billing), plus `DevAccess` and
`CodeIssuerAccess` for our own administration (guest grants, activation codes).

* `resolve_access()` (`backend/src/modules/organizations/services/access.py`) is the one place
  the platform role, the membership role and subscription state combine; the resulting
  `OrganizationAccess` is frozen, and the tenant is read through `access.tenant_id`, which raises
  rather than relying on an `assert` that vanishes under `python -O`.
* `backend/tests/unit/core/test_every_writing_route_is_guarded.py` walks the real application and
  fails if any POST/PATCH/PUT/DELETE resolves no guard at least as strong as `WritingAccess`. Its
  exemption list carries a reason per entry and is itself checked against live routes.
* Invariants that lose races in application code are stated in the database: at most one owner
  per organisation, one organisation per user, at most one primary organisation (partial unique
  indexes), and `workspaces.organization_id NOT NULL`.
* Single-use operations — consuming a refresh token, claiming an activation code or an
  invitation — are a conditional `UPDATE … WHERE <still unused>` that must affect exactly one
  row. The database picks the winner; the loser builds nothing.

## Authentication and sessions

Configured in `backend/src/core/config/security.py`; implemented in
`backend/src/modules/users/` and `backend/src/core/security.py`.

* **Passwords**: bcrypt, cost 12, with a 72-byte ceiling enforced rather than silently
  truncated. Unknown accounts still run a verify against `DUMMY_HASH`, and unknown user, wrong
  password and disabled account all get the same message, so login is neither a timing nor a
  message oracle. New passwords are checked against Have I Been Pwned by k-anonymity — only the
  first five characters of the SHA-1 leave the process (`backend/src/integrations/pwned.py`).
* **Access token**: a short-lived JWT (15 minutes), held by the SPA **in memory only**.
* **Refresh token**: an opaque 256-bit secret, stored only as a SHA-256 digest and looked up by
  digest against a unique index. Every `/refresh` consumes the presented token and issues a new
  pair (rotation). Rotation re-checks that the account is still active.
* **Session limits**: the refresh window is 7 days and slides with rotation, but a login lineage
  (token *family*) can never outlive an absolute 30-day ceiling from first login.
* **Replay detection**: presenting an already-consumed refresh token revokes that token's
  **family** (RFC 9700 §4.14.2), not every session of the account — a replay is ambiguous between
  a thief and a client resuming with a stale token. A 30-second grace window
  (`backend/src/modules/users/refresh_grace.py`) serves the already-issued child to a late
  presenter of the same parent, so several tabs sharing one cookie jar converge on one token
  instead of tripping breach detection. The child is kept Fernet-encrypted for those seconds only;
  setting the window to 0 restores strict rotation.
* **Revocation reaches live access tokens**: Redis watermarks per user and per family
  (`backend/src/core/redis.py`) are checked by `backend/src/core/deps.py`, so «выйти отовсюду», a
  completed password reset and ending one session from the sessions list take effect
  immediately, not when the access token expires.
* **Per-account backoff** (`backend/src/modules/users/services/lockout.py`): failed logins grow
  an exponential, capped delay keyed on a hash of the account — the shape that answers
  credential stuffing from many addresses. It blocks new logins only; open sessions are
  untouched.
* **Email codes** (`backend/src/modules/users/services/verification.py`): six digits, stored as
  SHA-256, 15-minute expiry, capped attempts after which the code is dead, and a new code
  supersedes the previous one. Password-reset requests answer identically for known and unknown
  addresses.

Covered by, among others, `backend/tests/integration/users/test_breach_detection.py`,
`test_concurrent_tab_refresh.py`, `test_logout_ends_the_access_token.py`,
`test_session_revocation_lever.py`, `test_password_reset_flow.py` and
`backend/tests/unit/users/test_login_backoff.py`.

## Cookies, CSRF and the browser

* The refresh cookie is `HttpOnly; Secure; SameSite=Lax`, path-scoped to `/api/v1/auth`, so
  scripts cannot read it and the browser sends it nowhere else.
* **CSRF**: every mutating route except the auth endpoints authenticates with an
  `Authorization: Bearer` header, which a cross-site page cannot attach. For the
  cookie-authenticated auth endpoints (`/refresh`, `/logout`), `SameSite=Lax` is the CSRF
  control: the browser does not attach the cookie to a cross-site POST, and with CORS off a
  foreign page cannot read the tokens a refresh returns.
* **CORS** is off on every deployed environment: the SPA and API are same-origin behind nginx,
  and startup refuses `CORS_ENABLED=true` outside `local`.
* **Headers** (`frontend/docker/snippets/security-headers.conf`, `tls-headers.conf`): a strict
  CSP (`script-src 'self'`, `frame-ancestors 'none'`, `object-src 'none'`),
  `X-Frame-Options: DENY`, `nosniff`, `strict-origin-when-cross-origin`, and HSTS. Because nginx's
  `add_header` is not inherited into a location that declares its own, the snippet is included in
  each such location; `frontend/tests/integration/csp.spec.js` and `hsts.spec.js` pin the result.
* Grafana runs on its own subdomain so a flaw there cannot share an origin with seller sessions;
  see `docs/monitoring/OBSERVABILITY.md`.

## Rate limiting and resource bounds

* **Per-IP fixed windows** (`backend/src/core/ratelimit.py`, Redis-backed, shared across API
  replicas): login and register share one budget, `/refresh` has its own looser one, and the
  recovery endpoints a tighter one (wired in `backend/src/modules/users/routers/common.py`).
* **The client address is the one nginx wrote.** `resolve_client_ip`
  (`backend/src/core/client_ip.py`) reads `X-Real-IP`, which nginx replaces rather than appends,
  never the client-controlled `X-Forwarded-For` that uvicorn would trust. Pinned by
  `backend/tests/component/users/test_auth_rate_limit_spoofing.py` and
  `backend/tests/unit/core/test_client_ip.py`.
* **Per-tenant budgets**: re-harvest requests («Обновить») are limited per workspace, because the
  queue and the WB rate budget are spent per tenant; per-workspace row ceilings bound A/B tests,
  SKU groups and cost-price rows (`backend/tests/unit/core/test_tenant_resource_bounds.py`).
* **Uploads**: nginx `client_max_body_size` per route, then `read_capped`
  (`backend/src/core/uploads.py`) reads in chunks and stops at the ceiling before the body is in
  memory. Spreadsheet parsers check the declared uncompressed size and the compression ratio of
  the `.xlsx` archive before parsing and cap rows during iteration
  (`backend/src/modules/finreports/services/cost_upload_parser.py`). Pinned by
  `backend/tests/unit/core/test_upload_caps.py`.
* **Celery** is JSON-only (`task_serializer`, `accept_content`) — pickle over a Redis broker
  would be remote code execution — and every task carries soft and hard time limits
  (`backend/tests/unit/core/test_task_time_limits.py`).
* **Metrics**: no tenant-shaped label and no caller-chosen string can become a label, so a
  stranger cannot mint unbounded series (`backend/tests/unit/core/test_metric_cardinality.py`).

## Failing closed, and reporting when a control cannot

Unknowns resolve toward less access: a missing subscription row is read-only, a missing tenant
raises. The Redis-backed controls — the auth rate limit, login backoff and session revocation —
deliberately fail **open** on a Redis outage, because locking every user out is the worse
failure. That trade is made visible rather than silent: each reports to the degradation ledger
(`backend/src/core/degradation.py`) with `report_degraded` / `report_healthy`, which logs one
event per outage instead of one per request, raises `SECURITY_CONTROLS_DEGRADED_TOGETHER` when two
controls are down at once, and feeds the `SecurityControlDegraded` alert
(`backend/tests/unit/core/test_degradation_alerting.py`).

## Errors never carry secrets

* `AppError` subclasses become responses in one handler in `backend/main.py`. Upstream bodies
  are logged, never returned.
* The 422 handler drops the submitted value: FastAPI's default would echo a rejected password
  back in the response body.
* Response DTOs for WB tokens, activation codes and invitations carry status, never values; a
  generated secret leaves the server once, in the response that creates it.
* `/docs`, `/redoc` and `/openapi.json` are unmounted outside `local` — all three together, since
  the schema alone is the full route inventory.
* The readiness probe reports up or down, never an exception, host or DSN.

## Log and error-report redaction

`backend/src/core/observability/scrubbing.py` is one processor for every log line in the
process — ours, uvicorn's, Celery's, SQLAlchemy's — and for Sentry events.

* **By key**: fields named like `password`, `token`, `authorization`, `secret`.
* **By value**: JWTs (a WB token is one), bcrypt digests, Fernet ciphertexts, `Bearer` headers
  and DSN passwords, whatever the field is called — because secrets leak by interpolation, not by
  a field called `token`.
* It never raises; the worst case is an over-redacted line, never a lost one. Identifiers and
  email addresses are deliberately kept: it hides credentials, not identity.
* Sentry runs with `send_default_pii` off, so request bodies, headers and cookies are never sent.
* The request log records method, path, status, duration and client IP — not the query string.

Pinned by `backend/tests/unit/core/test_log_redaction.py` and
`test_structured_logging.py`.

## Secrets handling

* **Third-party credentials** (WB API tokens) are encrypted at rest with Fernet
  (`encrypt_secret` / `decrypt_secret` in `backend/src/core/security.py`), one set per workspace.
  The Fernet key lives only in the environment.
* **Secrets we generate** (refresh secrets, activation codes, invitation tokens) come from
  `secrets.token_urlsafe` and are stored as SHA-256 digests; bcrypt is reserved for
  human-chosen passwords. Token comparisons use `secrets.compare_digest`.
* **Startup refuses an unsafe configuration** outside `local`
  (`_enforce_production_hardening` in `backend/src/core/config/assembly.py`): placeholder or
  short JWT key, placeholder Postgres or Redis password, missing Fernet key, `DEBUG=true`,
  CORS enabled, a non-`Secure` refresh cookie, synthetic WB harvesting, or contradictory mail
  settings. Pinned by `backend/tests/unit/core/test_config_hardening.py`.
* **Nothing secret is committed.** Configuration is documented in `.env.example` files; the
  Alertmanager config, which would otherwise hold a bot token, is rendered from `.env` into a
  gitignored file (`backend/scripts/observability/render_alertmanager_config.sh`). The backup
  scripts parse `.env` rather than sourcing it.
* `/metrics` is not proxied to the internet and additionally requires `METRICS_TOKEN`, compared
  in constant time and answered with 404 when wrong.

## Integrity and auditability

* `organizations.audit_log` records security-relevant events — membership and role changes,
  credential rotations, subscription changes, workspace deletions — with who, which
  organisation, from which address and when. It is append-only twice over: by grant for the
  application role and by trigger for anyone else
  (`backend/tests/integration/organizations/test_audit_log_is_append_only.py`).
* The data schemas refuse `TRUNCATE` unless the same transaction opts in with
  `SET LOCAL app.allow_truncate = 'on'`, and every attempt, allowed or refused, is written to the
  audit log first (migration `backend/alembic/versions/f4c8b1e57a29_truncate_guard.py`, checked
  in `backend/tests/integration/core/test_migrations.py`).

## Backups

Nightly encrypted dumps (`backend/scripts/backup/`), described in its README and, for the key
scheme, in [BACKUP_KEYS.md](BACKUP_KEYS.md):

* encrypted with `age` to two public recipients — an online key that lets the job verify and
  rehearse a restore unattended, and an offline key that has never been on a server;
* the secrets bundle (`.env`) is encrypted separately to a third, offline-only key, so the
  database archives and the Fernet key that unlocks the WB tokens inside them never share a key;
* the recipient list is public and pinned by
  `backend/tests/unit/core/test_backup_encryption_recipients.py`, and every artifact must carry one
  recipient stanza per recipient before it is uploaded;
* because a public recipient lets anyone forge an artifact, provenance is recorded outside the
  buckets: a local sha256 ledger checked by `restore.sh fetch`, and the checksum in the weekly
  report (`backend/tests/unit/core/test_backup_artifact_provenance.py`);
* a weekly rehearsal restores the encrypted artifact into a scratch PostgreSQL on
  `--network none`.

## Supply chain

* Dependencies are locked (`backend/uv.lock`, `frontend/package-lock.json`) and installed with
  `uv sync --locked`; `make audit` runs `pip-audit` and `npm audit`.
* GitHub Actions are pinned by commit SHA, not by tag.
* Base images are pinned by digest; `.github/workflows/base-image-freshness.yml` checks weekly
  whether each pinned tag has moved and scans the running images with Trivy.
* WB responses are outside the trust boundary and are validated with Pydantic models before
  use; all upstream base URLs come from settings, never from user input.
