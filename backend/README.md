# Marketplace Analytics — Backend

A **modular monolith** for automating WildBerries marketplace operations, built
on FastAPI + async SQLAlchemy 2.0 + Celery, following strict Clean Architecture
boundaries.

## Layered architecture (per feature module)

```
routers  ->  services  ->  repos  ->  models
(HTTP)       (business)     (SQL)      (ORM)
```

* **Routers** never touch a repository or DB session — they depend only on a
  service type injected from the module's `deps` package.
* **Services** contain business logic and raise semantic `AppError`s; they never
  build SQL or handle `HTTPException`.
* **Repos** are the only place SQLAlchemy statements are constructed/executed.
* **Cross-module** communication goes through a module's `contract` only —
  direct horizontal imports are forbidden.

## Modules

| Module       | Schema       | Responsibility                                            |
|--------------|--------------|-----------------------------------------------------------|
| `users`      | `auth`       | Identity, login, JWT rotation + breach detection          |
| `monitoring` | `monitoring` | WB harvesting (funnel/stocks/advertising) + analytics API |

### Security highlights (`users`)

* **Refresh Token Rotation (RTR):** every `/refresh` consumes the presented
  token and issues a brand-new access + refresh pair (`services/auth.py`).
* **Breach detection:** replaying an already-used refresh token revokes the
  whole login lineage (token family) it belongs to and returns HTTP 401
  (`TokenReuseError`); a short grace window absorbs the benign multi-tab race.
  See `docs/security/SECURITY_DESIGN.md`.
* **Timing-attack mitigation:** unknown-user logins still run a bcrypt verify
  against a pre-computed `DUMMY_HASH`, keeping latency constant.
* Refresh secrets are delivered only via `HttpOnly; Secure; SameSite=Lax`
  cookies; only their SHA-256 hash is stored.

### Analytics highlights (`monitoring`)

* Raw nested WB payloads are flattened into clean relational rows during
  ingestion (`services/ingestion/`).
* "Baseline Organic Demand" normalization (`services/normalization.py`) applies
  **OOS masking → promo-lift filtering → seasonality adjustment** as pure,
  unit-testable functions.
* Data is served two ways: a compact **summary listing**
  (`GET /api/v1/monitoring/summary`) and a **detailed view**
  (`GET /api/v1/monitoring/skus/{nm_id}`), plus the cleansed funnel
  (`GET /api/v1/monitoring/funnel/{nm_id}`).

## A note on module layout

A layer is a flat file until it outgrows the size limit, then a package whose
`__init__.py` re-exports the same public names — so `monitoring` reads
`from src.modules.monitoring.repos import AnalyticsRepository` exactly as `users`
does, and callers never learn which form they are importing from. See the
`backend-architecture` skill (`.claude/skills/backend-architecture/SKILL.md`).

## Running locally

From the repository root. The quickest look is the demo — the whole stack on
fabricated data, no WB token, at <http://localhost:8080>:

```bash
cp backend/.env.example backend/.env   # works as is for local use
make demo                              # build, start, seed; `make demo-down` removes it
```

For development against the stack, copy
`docker/docker-compose.override.yml.example` to `docker/docker-compose.override.yml`
(it publishes the api, Postgres and Redis on loopback), then:

```bash
make up                       # api :8000, worker, postgres :5432, redis :6379
```

WB tokens are not environment variables: they are stored per workspace,
encrypted, and entered in the app.

Everything docker lives in `docker/` — the Dockerfile, its `.dockerignore`, and
all three compose files. `make up`/`down`/`ps`/`logs` wrap them; for anything
else, define the invocation once in your shell:

```bash
alias mc='docker compose --project-directory backend -f backend/docker/docker-compose.yml'
```

The `--project-directory` is required, not cosmetic: Compose resolves `.env`,
`env_file:` and every build context against it, and would otherwise infer
`backend/docker/` and start Postgres and Redis with different passwords than the
api reads. The compose file's `${VAR:?...}` guards turn that mistake into an
immediate error rather than a stack that comes up broken.

Create the initial migration once the stack is up:

```bash
mc exec api alembic revision --autogenerate -m "initial schemas"
mc exec api alembic upgrade head
```

API docs: <http://localhost:8000/docs> · Health: <http://localhost:8000/health>

## Quality gates

Dependencies are managed with [uv](https://docs.astral.sh/uv/). There is no
"activate the venv" step: `uv run` syncs `.venv` from `uv.lock` on demand, so a
command can never execute against a stale environment.

```bash
uv sync                                     # create/refresh .venv from uv.lock
uv run ruff check src tests main.py alembic scripts
uv run mypy src main.py scripts             # strict mode, zero errors
uv run pytest tests                         # every backend tier
```

From the repository root, `make lint`, `make typecheck`, `make test` and
`make audit` wrap the same commands across both stacks.

After changing a dependency in `pyproject.toml`, run `make lock` (`uv lock`) and
commit `uv.lock` with it — CI installs with `uv sync --locked`, which fails
rather than silently re-resolving.
