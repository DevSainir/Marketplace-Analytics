# marketplace_service

Wildberries seller analytics. FastAPI + Celery backend, Vue 3 SPA, PostgreSQL + Redis,
everything in Docker. A modular monolith: `backend/src/modules/{users,workspaces,monitoring,finreports}`,
`frontend/src/modules/{auth,monitoring,finreports}`.

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

These are reference, not preamble — open the one you are about to need.

| Working on | Read |
| --- | --- |
| Backend module layout, DI, DB schemas, auth/session invariants | `docs/rules/architecture_rules.md` |
| Any WildBerries endpoint, ingestion mapping, or funnel metric | `docs/rules/api_contracts.md` |
| Vue app structure, stores, the API client | `docs/rules/frontend_architecture.md` |
| Any UI surface | `docs/rules/design_system.md` |
| Writing, moving, or deleting a test | `docs/rules/tests_rules.md` |
| Judging what is already covered, or a known gap | `docs/rules/current_tests.md` |

`api_contracts.md` in particular is a log of things verified against the live WB API that
its own documentation gets wrong — read it before writing any request by hand.

## Commands

```bash
make test-fast        # backend unit + component, frontend unit — the pre-commit gate
make test-integration # real Postgres/Redis (auto-skips when unreachable)
make lint typecheck   # ruff + eslint + mypy --strict
```

`make` with no target lists every runner, including the e2e and performance tiers.
