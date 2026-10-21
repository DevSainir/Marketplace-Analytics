# marketplace_service

Analytics for sellers on the Wildberries (WB) marketplace. FastAPI + Celery backend, Vue 3 SPA,
PostgreSQL + Redis, everything in Docker. A modular monolith:
`backend/src/modules/{users,organizations,workspaces,monitoring,finreports,advertising,heatmap,summary,ab_tests,guide}`,
`frontend/src/modules/{auth,profile,monitoring,finreports,advertising,heatmap,summary,abTests,labs}`.

The interface is in Russian; everything written for a developer — code, comments, docs, commit
messages — is in English.

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

**Trunk-based.** Work is committed and pushed straight to `main` in small commits — no feature
branches, no worktrees, no PRs for ordinary work. Two hooks in `.claude/settings.json` hold the
line: `.claude/hooks/no_branching.py` refuses branch-creating commands and pushes to anything but
`main`, and `.claude/hooks/trunk_check.py` moves a session that starts on a stray branch back to
`main`. The details are in the `git-workflow` skill.

## One workspace at a time

Every seller account («кабинет» in the UI, `workspace` in the code) is a tenant, and reading one
that is not yours is a disclosure whether or not anything is written. Tenancy is enforced twice:
by every query (`workspace_sku_select`, the `CurrentWorkspaceId` dependency) and by PostgreSQL
row-level security (`backend/scripts/sql/row_level_security.sql`, applied together with the
least-privilege application role in `least_privilege_role.sql` — the role first, then the
policies; each file's header says why the order matters).

An ad-hoc look at stored data is never a script with its own session. It runs through
`backend/scripts/diagnose.py`, which hands the probe a session that is read-only at the
transaction level and pinned to one workspace by row-level security, with no way to name a
different one (`backend/src/core/diagnostics.py`; tests in
`tests/unit/core/test_diagnostic_gate.py` and
`tests/integration/core/test_diagnostic_gate_is_enforced.py`). The worker connects as the table
owner, so a bare `AsyncSessionLocal()` there reaches every tenant with nothing in the way — which
is why the gate exists.

## Where the rest lives

The project's rules are skills in `.claude/skills/` — `backend-architecture`,
`frontend-architecture`, `design-system`, `phone-layout`, `testing`, `git-workflow`, `security`.
Each one's description says when it applies, so they load themselves when the work calls for
them rather than sitting in every conversation. Read them directly (they are plain markdown) when
working without that mechanism, and put new project guidance in the relevant skill rather than
here.

`docs/JOURNAL.md` is the record of finished work, one row per task; how a row is written is in the
`git-workflow` skill.

`docs/security/SECURITY_DESIGN.md` is the security design — the threat model and the controls that
answer it. The `security` skill is the standing checklist that keeps new code inside that design.
`docs/security/BACKUP_KEYS.md` explains the backup key scheme — why the archives are encrypted to
two `age` recipients and what the move away from a symmetric passphrase gave up. Read it before
touching `backend/scripts/backup/recipients/` or either encryption key.

`docs/monitoring/OBSERVABILITY.md` is the observability stack — Prometheus, Grafana, Loki and
Sentry, plus the structlog pipeline and its redaction filter. Read it before adding a metric
or a log field: two rules there are enforced by tests rather than by review, and both are
security controls rather than housekeeping. **No metric may be labelled by tenant** (`/metrics`
has no tenancy check because it has no tenant), and **no caller-chosen string may reach a
label** (an unmatched path would otherwise let a stranger create one permanent time series per
URL they try). Metrics answer "is the system healthy"; the logs, which carry `workspace_id` on
every line, answer "for whom". The stack is a separate compose overlay — `make obs-up` — so the
service runs instrumented whether or not anything is watching it.

`docs/monitoring/LIVE_POSITION.md` records the removed organic-position probe: weeks of
measurement against WB's storefront edge, kept because the endpoint facts outlive the feature.

`docs/finreports/` holds what no skill covers: how the P&L is derived from WB's settlement
detail and why each line is what it is (`PNL.md`). Read `PNL.md` before changing anything that
touches a settlement figure — most of the ways to get it wrong produce a plausible statement
rather than an error. `MIGRATION_TO_FINANCE_V1.md` records how the P&L moved off the settlement endpoint WB
switched off, and why much of the machinery that paced, probed and walked the old report is gone.
The payout's sign comes from `doc_type_name`, not the operation; every booked report is checked
against WB's own `forPaySum` with an alert (`PNL.md`).

`docs/RELEASES.md` covers versioning: the version is **derived from your commit messages**, never
typed, so a `feat:`, a `feat-minor:` and a `fix:` are not interchangeable (which to use is in the
`git-workflow` skill). Release Please keeps one open `chore(release):` PR, and merging it cuts the
release. Read it before editing `.github/workflows/release.yml` or the version fields in
`backend/pyproject.toml` / `frontend/package.json`.

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
