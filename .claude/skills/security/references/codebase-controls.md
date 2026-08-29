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
Four of them leaked precisely because their signatures let a caller not say whose data it
wanted.

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
  Account-wide revocation on a replay caused a team-wide outage on 2026-07-27 when a laptop
  woke from sleep; the ambiguity between a thief and a stale-but-legitimate client is real.
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
* WB calls pass a shared Redis token bucket (`src/integrations/wildberries/rate_limit.py`)
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
