# Where every security control actually lives

A map, so a new route inherits the existing controls instead of growing its own. If you are
about to write a check that sounds like something below, use the thing below instead.

---

## 1. Identity, role and tenancy

| Question | Answered by | File |
| --- | --- | --- |
| Is this token valid? | `get_current_user_id` | `src/core/deps.py` |
| Which live account is this? | `get_current_user` → `CurrentUser` | `src/modules/users/deps.py` |
| What may they do, and have they paid? | `resolve_access` → `OrganizationAccess` | `src/modules/organizations/services/access.py` |
| Which workspace is this request in? | `get_current_workspace_id` → `CurrentWorkspaceId` | `src/modules/workspaces/deps.py` |
| Does this SKU belong to them? | `require_workspace_sku` → `WorkspaceSku` | `src/modules/monitoring/deps/__init__.py` |

**`OrganizationAccess` is frozen** — a guard that could mutate it is a guard that could
escalate it. Read the tenant through `access.tenant_id` (raises `PermissionDeniedError` if
absent), never `access.organization_id` behind an `assert`: asserts vanish under `python -O`.

**Role lives in two places, deliberately.** `auth.users.role` holds the *platform* role
(`dev` / `user`); `organizations.memberships.role` holds the *organisation* role (`owner` /
`manager`). `EffectiveRole` collapses them with one rule — dev outranks everything. That
split exists so "a dev who also owns a company" is representable, which is the state our own
accounts are in. Reading either column alone answers a third of the question.

**`dev` elevates a role; it does not supply a tenant.** A dev with no membership cannot open
any data page, and that is correct — the routes are tenant-scoped and there is nothing to
scope them to. Devs work inside an organisation like everyone else.

---

## 2. Database-level invariants

Three properties are enforced by PostgreSQL, not by application code, because each is cheap
to violate under concurrency and expensive to discover afterwards:

| Invariant | Mechanism |
| --- | --- |
| At most one primary organisation | partial unique index `uq_organizations_single_primary` |
| At most one owner per organisation | partial unique index `uq_memberships_single_owner` |
| One organisation per user | unique index on `memberships.user_id` |
| A workspace always has a tenant | `workspaces.organization_id NOT NULL` + FK |

When you add a rule of the form "there can only be one X", ask whether the database can say
it. Application-level uniqueness checks lose races.

### Roles and row-level security

Two SQL scripts move tenancy and privilege from a promise into PostgreSQL. They are an
ordered pair, and each file's header says what happens if the order is broken:

1. `backend/scripts/sql/least_privilege_role.sql` — the API stops connecting as the table
   owner. Its role has DML on the module schemas and nothing else: no DDL, no ownership, no
   superuser, and only `INSERT`/`SELECT` on `organizations.audit_log`. Migrations, Celery
   harvests and the backup keep the owner, because they legitimately cross workspaces.
   `tests/unit/core/test_only_the_api_uses_the_restricted_role.py` reads the compose file so
   the role cannot be rolled out to every service at once by a one-line `.env` edit.
2. `backend/scripts/sql/row_level_security.sql` — policies keyed on
   `current_setting('app.workspace_id')`. RLS does not apply to a table's owner, which is why
   the role comes first. A query with no tenant bound **raises** rather than returning zero
   rows: an empty answer looks like "this customer has no data" and invites someone to delete
   the scoping, an error does not. `src/core/observability/rls_watch.py` counts those
   refusals so the first one pages somebody.

Both are proved by applying the shipped script to a real PostgreSQL and then connecting as
the role it creates (`tests/integration/core/test_least_privilege_role.py`,
`test_row_level_security.py`). The RLS test deliberately runs naive queries with **no**
tenant predicate — a test that scoped its own SQL would pass with the policies dropped.

The `monitoring` and `finreports` schemas also refuse an unannounced `TRUNCATE` (a
statement-level trigger; opt in with `SET LOCAL app.allow_truncate = 'on'`, and every
attempt is written to the audit log).

### The diagnostic gate

The worker connects as the owner, so a script that opens its own `AsyncSessionLocal()` there
reaches every tenant. Ad-hoc probes of stored data therefore go through
`backend/scripts/diagnose.py`, which hands the probe a session that is read-only at the
transaction level and pinned to one workspace by RLS (`src/core/diagnostics.py`; tests
`tests/unit/core/test_diagnostic_gate.py`,
`tests/integration/core/test_diagnostic_gate_is_enforced.py`).

---

## 3. Query scoping

`workspace_sku_select(workspace_id)` (`src/modules/monitoring/repos/base.py`) is the semijoin
through `product_card` — the SKU → workspace registry. Every cross-SKU aggregate goes through
it. A fact row whose SKU has no card belongs to **nobody** and reaches no statement; that is
intended, not a gap.

**Every loader in `monitoring/contract.py` takes a required keyword-only `workspace_id`.**
This is enforced by a test, not by convention:
`tests/integration/monitoring/test_export_loaders_are_scoped.py` reflects over the contract
and fails the build if a loader is added without one, or given a default, or made positional.
A signature that lets a caller not say whose data it wants is how a cross-tenant read
happens without anyone forging an id.

The one deliberate cross-tenant reader is `load_workspace_token_bundles`, used only by Celery
harvest fan-out. No request path may call it.

---

## 4. Secrets

| Kind | Handling | Where |
| --- | --- | --- |
| Passwords (human-chosen) | bcrypt, cost 12, + `DUMMY_HASH` constant-time miss path | `src/core/security.py` |
| Refresh secrets, activation codes, invitation tokens (we generate) | `generate_opaque_secret` + SHA-256 via `hash_opaque_secret` | `src/core/security.py` |
| WB API tokens (third-party credentials) | Fernet `encrypt_secret` / `decrypt_secret` | `src/core/security.py` |

SHA-256 rather than bcrypt for generated secrets is correct and deliberate: bcrypt's cost
exists to slow guessing of a value a *human* chose, and these are 256 bits of
`secrets.token_urlsafe`. Lookups are **by digest** against a unique index, so no value
comparison happens and there is no timing channel.

A generated secret leaves the server exactly once, in the response that creates it. Response
DTOs (`WorkspaceTokensStatus`, `ActivationCodeRead`, `InvitationRead`) carry status, never
values — the shape is the control.

Startup refuses to boot a non-local environment carrying a placeholder secret, a short JWT
key, `DEBUG=true`, or `WB_FAKE_HARVEST=true`
(`src/core/config/assembly.py::_enforce_production_hardening`). Add new secrets to that guard.

---

## 5. Sessions

* Access token 15 min, refresh 7 days, **rotating**: each refresh consumes the presented
  token and issues a new pair.
* Replay of a consumed token revokes that **family** (RFC 9700 §4.14.2) — not the account.
  Account-wide revocation on a replay logs out every device whenever one laptop wakes from
  sleep with a stale cookie; the ambiguity between a thief and a stale-but-legitimate client
  is real, so the blast radius stays at one lineage.
* Logout and "end every session" stamp a per-family revocation watermark in Redis, so an
  access token dies at once rather than at its 15-minute expiry
  (`tests/integration/users/test_logout_ends_the_access_token.py`).
* Refresh secrets travel only as `HttpOnly; Secure; SameSite=Lax`, path-scoped to
  `/api/v1/auth`. That SameSite value is also the CSRF control for `/refresh`; every other
  mutating route authenticates with a Bearer header, which is not CSRF-able.
* Login runs bcrypt against `DUMMY_HASH` for unknown accounts and returns an identical
  message for unknown-user / wrong-password / disabled, so the endpoint is not an
  account-existence oracle.

---

## 6. Errors and logging

`AppError` subclasses carry a code and an HTTP status; `main.py`'s handler is the single
place they become responses. 4xx logs at INFO, 5xx at WARNING — severity follows the status,
not the exception class.

**Never put an upstream body in a client-facing message.** `IntegrationError(f"... {exc}")`
reaches the client as a 502 body. Log the detail, return a sentence.

The request log records method, path, status, duration and client IP — deliberately **not**
the query string, which carries filter values. If you add fields, keep secrets and PII out.

**Redaction is a net, not a licence.** `src/core/observability/scrubbing.py` scrubs every log
line and every Sentry event for the value shapes this codebase produces — JWTs (a WB token is
one), bcrypt digests, Fernet ciphertexts, DSN and proxy-URL passwords — whether they arrive as a
named field or loose inside a sentence. `tests/unit/core/test_log_redaction.py` pins both
failure directions: a credential surviving, and a correlation id (`trace_id` is 32 hex
characters, like a digest) being eaten. Do not rely on it; it is there for the `%s` nobody
noticed.

**The client address** a per-IP control keys on comes from `src/core/client_ip.py`: the
header the reverse proxy overwrites, never `request.client`, which a forged
`X-Forwarded-For` can choose (`tests/unit/core/test_client_ip.py`,
`tests/component/users/test_auth_rate_limit_spoofing.py`).

**The audit log** (`organizations.audit_log`) is append-only twice over — by grant and by
trigger — and records security-relevant events (membership and role changes, credential
rotations, subscription changes) with actor, tenant and target, never a secret
(`tests/integration/organizations/test_audit_log_is_append_only.py`,
`test_audit_events_are_recorded.py`).

---

## 7. Transport and browser

`frontend/docker/snippets/security-headers.conf` carries CSP, `X-Content-Type-Options`,
`Referrer-Policy` and `X-Frame-Options: DENY`; `tls-headers.conf` adds HSTS.

**nginx `add_header` is not additive across levels** — a `location` declaring any
`add_header` of its own discards every inherited one. That is why the snippet is *included*
in each such location rather than set once on the server. Adding a location with its own
cache header means including the snippet too, or that path silently loses every security
header.

Adding an external host to the app means adding it to the CSP or the browser blocks it. The
Vite dev server sends no CSP at all, so a blocking directive is invisible locally and only
appears in CI or production.

---

## 8. Background work

* Celery is JSON-serialised (`task_serializer`, `result_serializer`, `accept_content`) — the
  broker is Redis and pickle would be remote code execution.
* Task bodies must go through `run_task` (`src/core/tasks.py`), never their own
  `asyncio.run`: it drains the SQLAlchemy and Redis pools at the task boundary, and a leaked
  connection kills the *next* task. Pinned by
  `tests/unit/core/test_task_loop_hygiene.py`.
* Scheduled jobs that walk a rate-limited API take `single_flight` (`src/core/locks.py`) —
  a heartbeat-renewed Redis lock, not a long TTL.
* WB calls pass a shared Redis token bucket (`src/integrations/wildberries/rate_limit/`)
  because WB meters the IP that the api and worker processes share.

---

## 9. Tests that enforce architecture

| Property | Test |
| --- | --- |
| No horizontal module imports; contracts resolve; 500-line ceiling | `tests/unit/core/test_module_boundaries.py` |
| Migrations produce exactly the model schema | `tests/integration/core/test_migrations.py` |
| Every contract loader demands a tenant | `tests/integration/monitoring/test_export_loaders_are_scoped.py` |
| Tasks do not strand event loops | `tests/unit/core/test_task_loop_hygiene.py` |
| Component tests never touch the database | component-tier `execute` guard in `tests/component/conftest.py` |

When you close a security gap, prefer a test that makes the *class* of bug impossible over
one that pins the single instance you just fixed. The loader-signature guard immediately
caught a fifth leaking loader nobody had noticed.

---

## 10. Verifying a new route is wired correctly

```bash
# Every router should declare a guard; find one that does not.
grep -rn "APIRouter(" backend/src/modules/*/routers/ | grep -v dependencies

# Tenant-scoped routes must take the workspace from the dependency, never the body.
grep -rn "workspace_id" backend/src/modules/*/routers/ | grep -i "body\|payload\|Query("

# Queries that filter on an id with no tenant beside it.
grep -rn "\.where(" backend/src/modules/*/repos/ | grep -v "workspace_id\|organization_id\|nm_id.in_"

# Uploads: the size check must precede the read.
grep -rn -B3 "await file.read()" backend/src/modules/*/routers/
```

In the component tier, `login_as(role=..., subscription=..., is_primary_org=...)` sets who
the caller is for one test. It replaces `get_current_access` only — **authentication still
runs**, so "a bad token is a 401" tests stay honest.
