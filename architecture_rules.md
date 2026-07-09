# System Architecture, Security & Development Guidelines

## 1. Project Type & Stack
* **Architecture:** Modular Monolith (Monorepo with isolated Backend and Frontend structures).
* **Layered Pattern (Clean Architecture):** Strict isolation of layers within each feature module: presentation layer (`routers.py`) -> business logic layer (`services.py`) -> data access layer (`repos.py`) -> database models (`models.py`). Database layers or raw SQL entities MUST NEVER intersect with routers or application services directly.
* **Backend:** Python 3.12+, FastAPI, Async SQLAlchemy 2.0 (asyncpg), Alembic, Celery + Redis (Task Queue & Broker).
* **Frontend:** Vue 3 (Composition API, `<script setup>`), Vite, Tailwind CSS.
* **Infrastructure:** Docker, Docker Compose (multi-container environment: api, worker, postgres, redis).
* **Code Quality:** Ruff (linter/formatter), Mypy (`strict = true`).
* **Documentation:** Explicit Python docstrings are MANDATORY for all classes, methods, and functions. All FastAPI routers must have explicit HTTP status code definitions.

## 2. Monorepo Directory Structure
```text
marketplace_service/
├── backend/
│   ├── docker/
│   │   ├── app.Dockerfile
│   │   └── celery.Dockerfile
│   ├── src/
│   │   ├── core/          # Global infrastructure (DB engine, global config, security)
│   │   │   ├── config.py
│   │   │   ├── logging.py
│   │   │   ├── database.py
│   │   │   ├── deps.py    # ALL global and shared dependencies (e.g., DbSession)
│   │   │   └── security.py
│   │   ├── integrations/  # External HTTP/SDK clients (S3, Twilio, low-level WB API clients)
│   │   ├── modules/       # Isolated business domains (users, wb_analytics, wb_advertising)
│   │   │   ├── monitoring/
│   │   │   │   ├── models/
│   │   │   │   ├── schemas/
│   │   │   │   ├── repos/
│   │   │   │   ├── services/
│   │   │   │   ├── contracts/
│   │   │   │   ├── deps/
│   │   │   │   └── routers/
│   │   │   └── users/     # And so on
│   ├── docker-compose.yml
│   ├── pyproject.toml
│   └── main.py
└── frontend/              # Vue 3 SPA. We will build it later.
```

## 3. Strict Dependency & Import Rules (The "Contract" Pattern)
* **Vertical Imports (Allowed):** Any module inside src/modules/ can import infrastructure from src/core/ and low-level clients from src/integrations/.

* **Horizontal Imports (STRICTLY FORBIDDEN):** Direct cross-module imports are forbidden. Every business module must expose its public programming interface via a contract.py file. Cross-module communication can ONLY happen via: from src.modules.module_b.contract import ....

## 4. Database Isolation & Schemas
* **Logical Schemas:** Do not use the public schema. Map tables to explicit schemas using SQLAlchemy __table_args__ = {"schema": "schema_name"}.

* * **users module -> schema:** auth

* * **monitoring module -> schema:** monitoring

* **Primary Keys**: Use UUIDv7 (time-ordered) for all unique entity IDs to ensure optimal B-Tree index performance in PostgreSQL and protect against enumeration attacks. Composite keys (date + nm_id) are allowed for time-series aggregation tables.

## 5. Security & Token Rotation Standards
* **Authentication**: JWT-based access tokens (15-minute lifespan) and refresh tokens (7-day lifespan).

* **Refresh Token Rotation (RTR):** Every time a new access token is requested using a refresh token, the current refresh token is invalidated, and a BRAND NEW pair of access + refresh tokens is generated.

* **Breach Detection Flow:** Refresh tokens must be tracked in the database (auth.refresh_tokens) with states: token_id, user_id, parent_id (token family tree), is_used, and is_revoked. If a token with is_used == true is presented, a breach is detected. The system MUST instantly revoke all active tokens/sessions belonging to that user family tree, forcing a complete log-out across all devices.

* **Cookie Storage:** Refresh tokens must be transmitted strictly via HttpOnly, Secure, SameSite=Lax cookies.

* **Timing Attack Mitigation:** The authorization service must use a dummy_hash fallback execution during user lookup to keep verification timelines identical whether the user account exists or not.
