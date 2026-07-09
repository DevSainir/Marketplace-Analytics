# Marketplace Service — Backend

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
  token and issues a brand-new access + refresh pair (`services.py`).
* **Breach detection:** replaying an already-used refresh token revokes **all**
  of that user's sessions and returns HTTP 401 (`TokenReuseError`).
* **Timing-attack mitigation:** unknown-user logins still run a bcrypt verify
  against a pre-computed `DUMMY_HASH`, keeping latency constant.
* Refresh secrets are delivered only via `HttpOnly; Secure; SameSite=Lax`
  cookies; only their SHA-256 hash is stored.

### Analytics highlights (`monitoring`)

* Raw nested WB payloads are flattened into clean relational rows during
  ingestion (`services/ingestion.py`).
* "Baseline Organic Demand" normalization (`services/normalization.py`) applies
  **OOS masking → promo-lift filtering → seasonality adjustment** as pure,
  unit-testable functions.
* Data is served two ways: a compact **summary listing**
  (`GET /api/v1/monitoring/summary`) and a **detailed view**
  (`GET /api/v1/monitoring/skus/{nm_id}`), plus the cleansed funnel
  (`GET /api/v1/monitoring/funnel/{nm_id}`).

## A note on the spec (layout reconciliation)

`architecture_rules.md` draws the `monitoring` module as **package directories**
(`models/`, `repos/`, …) while `di_patterns.md` writes them as flat files and
names the DI file `dependencies.py`. This build honours the **directory tree**
as the source of truth: `monitoring` uses packages whose `__init__.py`
re-export the public classes, so the clean import paths from `di_patterns.md`
(`from src.modules.monitoring.repos import AnalyticsRepository`) still resolve.
The DI package is named `deps/` (matching the tree). The `users` module uses
flat files, which the rules permit ("And so on").

## Running locally

```bash
cp .env.example .env          # then fill secrets (JWT_SECRET_KEY, WB tokens…)
docker compose up --build     # api :8000, worker, postgres :5432, redis :6379
```

Create the initial migration once the stack is up:

```bash
docker compose exec api alembic revision --autogenerate -m "initial schemas"
docker compose exec api alembic upgrade head
```

API docs: <http://localhost:8000/docs> · Health: <http://localhost:8000/health>

## Quality gates

```bash
pip install -e ".[dev]"
ruff check .
mypy src main.py            # strict mode, zero errors
```

All 48 source modules pass `mypy --strict` and `ruff` clean.
