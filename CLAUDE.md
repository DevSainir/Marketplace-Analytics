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

## Where the rest lives

The project's rules are skills in `.claude/skills/` — `backend-architecture`,
`wildberries-api`, `frontend-architecture`, `design-system`, `testing`. Each one's description
says when it applies, so they load themselves when the work calls for them rather than sitting
in every conversation. Read them directly (they are plain markdown) when working without that
mechanism, and put new project guidance in the relevant skill rather than here.

`docs/finreports/` holds what no skill covers: how the P&L is derived from WB's weekly
Read `PNL.md` before changing anything that touches a settlement figure — most of the ways to
get it wrong produce a plausible statement rather than an error.

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
