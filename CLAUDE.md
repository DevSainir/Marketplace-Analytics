# marketplace_service

Wildberries seller analytics. FastAPI + Celery backend, Vue 3 SPA, PostgreSQL + Redis,
everything in Docker. A modular monolith: `backend/src/modules/{users,workspaces,monitoring,finreports}`,
`frontend/src/modules/{auth,profile,monitoring,finreports}`.

## Repo-wide invariants

Four rules that cost more to discover from a failing test than to state here:

* **Imports are absolute from `src.`** — relative imports are not used anywhere in the backend.
* **Modules talk only through `contract.py`.** No module imports another module's internals;
  the frontend equivalent is each module's `index.js`.
* **Every I/O path is async** — DB sessions, HTTP clients, Celery task bodies.
* **500 lines is a hard ceiling per file**, 300 the point to start looking for a split.
  Split by responsibility, never `part1`/`part2`; a grown layer module becomes a package
  with the public API re-exported from `__init__.py`.

All four are machine-enforced — `backend/tests/unit/core/test_module_boundaries.py`,
`frontend/eslint.config.js`, `frontend/tests/integration/architecture.spec.js`.

## Production is somebody else's business, except one кабинет

**Only «Демо» may be looked at, unless the user asks for another кабинет themselves or
gives permission.** Every other кабинет on the box belongs to a paying customer, and reading
one is a disclosure whether or not anything is written. This holds for every test, probe,
measurement and "just checking" — there is no read-only exemption, and the permission is the
user's to give rather than yours to infer from the task.

So a probe against production is never a script with its own session: it runs through
`backend/scripts/diagnose.py`, which hands it a session that is read-only at the transaction
level and pinned to that кабинет by row-level security, and which offers no way to name a
different one (`backend/src/core/diagnostics.py`, tests in
`tests/unit/core/test_diagnostic_gate.py` and
`tests/integration/core/test_diagnostic_gate_is_enforced.py`). The worker container connects
as the table owner, so a bare `AsyncSessionLocal()` there reaches every tenant with nothing
in the way — that is how this rule came to be written.

## Where the rest lives

The project's rules are skills in `.claude/skills/` — `backend-architecture`, `wildberries-api`,
`frontend-architecture`, `design-system`, `phone-layout`, `testing`, `git-workflow`,
`security`, `production-access`. Each one's
description says when it applies, so they load themselves when the work calls for them rather than
sitting in every conversation. Read them directly (they are plain markdown) when working without
that mechanism, and put new project guidance in the relevant skill rather than here.

`docs/security/BACKUP_KEYS.md` explains the backup key scheme — why the archives are
encrypted to two `age` recipients, which of the three keys lives where, and the one
property the move away from a symmetric passphrase gave up. Read it before touching
`scripts/backup/recipients/` or either encryption key.

`docs/security/HARDENING.md` is the live weakness register — what is fixed, what blocks a
public launch, and what was decided against on purpose. Read the entry before changing
anything it names: several of them record *why* a choice was made, including the ones where
the reasoning was later found wrong and corrected rather than deleted. The `security` skill is
the standing checklist that keeps new code from adding to it, and
`docs/security/INCIDENT_RESPONSE.md` is what to reach for when something has already gone
wrong — every lever it names exists and is tested.

Two controls in that register — `backend/scripts/sql/least_privilege_role.sql` (the app stops
owning its tables) and `row_level_security.sql` (tenancy enforced by Postgres) — **were
applied to production on 2026-09-02 and verified on the box**. They are an ordered pair — the
role first, then the flag, then the policies — and each file's header says what happens if
that order is broken, which is what to re-read before applying them anywhere else.

`docs/monitoring/LIVE_POSITION.md` records the removed organic-position probe: six weeks of
measurement against WB's storefront edge, kept because the endpoint facts outlive the feature.

`docs/monitoring/OBSERVABILITY.md` is the observability stack — Prometheus, Grafana, Loki and
Sentry, plus the structlog pipeline and its redaction filter. Read it before adding a metric
or a log field: two rules there are enforced by tests rather than by review, and both are
security controls rather than housekeeping. **No metric may be labelled by tenant** (`/metrics`
has no tenancy check because it has no tenant), and **no caller-chosen string may reach a
label** (an unmatched path would otherwise let a stranger create one permanent time series per
URL they try). Metrics answer "is the system healthy"; the logs, which carry `workspace_id` on
every line, answer "for whom". The stack is a separate compose overlay — `make obs-up` — so the
service runs instrumented whether or not anything is watching it.

`docs/finreports/` holds what no skill covers: how the P&L is derived from WB's weekly
Read `PNL.md` before changing anything that touches a settlement figure — most of the ways to
get it wrong produce a plausible statement rather than an error.
`MIGRATION_TO_FINANCE_V1.md` records how the P&L moved off the settlement endpoint WB
switched off on 15.07.2026 — done 22.09.2026, all seven phases. Read it before touching
anything that paces, probes or walks the report: much of that machinery was built to
survive the dead endpoint and is now either gone or demoted to a cross-check. Its phase-2
diff (5508 rows, 61 of 63 columns identical to the value) is the evidence the cutover
rests on, and its phase-6 note holds a live 128 KGS disagreement with WB's own total that
is measured rather than fixed.

`docs/RELEASES.md` covers versioning: the version is **derived from your commit messages**, never
typed, so a `feat:`, a `feat-minor:` and a `fix:` are not interchangeable (which to use, and the
trunk-based rule that work goes straight to `main`, are in the `git-workflow` skill). Release Please keeps one open
`chore(release):` PR and merging it cuts the release; the announcement is auto-translated to
Russian for the team. Read it before editing `.github/workflows/release.yml`, the version fields
in `backend/pyproject.toml` / `frontend/package.json`, or anything under `.github/scripts/`.

## Commands

```bash
make test-fast        # backend unit + component, frontend unit — the pre-commit gate
make test-integration # real Postgres/Redis (auto-skips when unreachable)
make lint typecheck   # ruff + eslint + mypy --strict
```

`make` with no target lists every runner, including the e2e and performance tiers.

The Makefile drives pytest through `uv`, which lives in `~/.local/bin` and is **not** on a
non-interactive shell's PATH — `make test-fast` there dies with `uv: command not found`. Either
export the path first or call the venv directly:
`cd backend && .venv/bin/python -m pytest tests/unit tests/component`.
