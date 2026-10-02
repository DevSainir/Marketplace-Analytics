---
name: backend-architecture
description: How the FastAPI backend of this repo is put together — module layers, the contract.py boundary between modules, one Postgres schema per module, UUIDv7 keys, DI wiring in deps/, and the refresh-token rotation model. Use this whenever you touch anything under backend/src — adding or moving a route, service, repository, model or migration, wiring a dependency, splitting a file that grew too big, or working on auth and sessions (tenancy and access guards are the security skill) — and also when you are only reading the backend and need to know why it is shaped this way. Cheap to consult and expensive to skip, because most of these rules are enforced by tests that fail late.
---

# Backend architecture

What the layout means and which parts are load-bearing. The stack is in `backend/pyproject.toml`
and the tree is whatever `ls backend/src` shows — this skill is for the decisions neither of
those explains.

## Layers

`routers/` → `services/` → `repos/` → `models/`, each arrow one-way. A router never reaches a
repository or an ORM model, and no SQL is written above `repos/`. Pydantic `schemas/` are what
cross the HTTP boundary in both directions; ORM models never leave `repos/`.

A module is those layers plus `deps/` (its DI wiring), `tasks/` (Celery entry points) and
`contract.py`. Small modules keep a layer as one file (`users/services.py`), large ones as a
package (`monitoring/services/analytics/`) — a size question, not an architectural one, and
invisible to callers because the package re-exports the same names from `__init__.py`.

**500 lines is a hard ceiling per file**, 300 the point to start looking for a split. Split by
responsibility, never `part1`/`part2`. When a layer module outgrows it, convert it to a package
and re-export the public API from `__init__.py`; callers must not have to change an import.
Composition of the split units goes in its own orchestrator module rather than in one of them.
`src/modules/monitoring/services/` is the canonical example.

## The contract boundary

Vertical imports are free: any module may import `src.core.*` (engine, config, security, Redis)
and `src.integrations.*` (WB HTTP clients, S3).

Horizontal imports are forbidden. `src.modules.a` reaches `src.modules.b` only through
`src.modules.b.contract`, which re-exports a deliberately small surface via `__all__`. That is
what leaves a module's internals free to move. Modules call each other in-process, so there is
no schema between them to version — a breaking change surfaces as a `mypy --strict` error, and
that only holds while the contract stays the single door.

Imports are absolute from `src.` everywhere; the backend has no relative imports.

`backend/tests/unit/core/test_module_boundaries.py` fails the build on a violation of any of
this, including the line limit.

## Database

* **One logical schema per module**, named after it — `monitoring`, `workspaces`, `finreports`.
  The exception is `users`, whose schema is `auth`. Nothing lives in `public`; every model
  declares `__table_args__ = {"schema": ...}`.
* **UUIDv7 for entity primary keys** — time-ordered, so B-tree inserts stay in the hot leaf
  pages, and unguessable, so an ID is not an enumeration oracle. Time-series tables use their
  natural composite key instead (`date` + `nm_id`).
* **Migrations own the shape.** An integration test replays them onto an empty database and
  diffs the result against the models; drift fails the run. Change a model, write the migration
  in the same commit.

## Dependency injection

`src/core/deps.py` holds infrastructure only — the request-scoped `AsyncSession`, the
authenticated principal, integration clients. Everything domain-specific lives in the module's
own `deps/`, so a router imports one `Annotated` alias and knows nothing about repositories.

`src/core/deps.py` and `src/modules/monitoring/deps/` are the canonical pair to read. The chain
is always `DbSession → get_x_repo → XRepoDep → get_x_service → XServiceDep`.

One thing in `get_db` that looks removable and is not: the commit-and-close runs under
`asyncio.shield`. A client disconnect cancels the handler mid-teardown, and an unshielded
cleanup leaks `idle in transaction` connections until the pool is exhausted and the SPA hangs
behind its header. Do not simplify it back.

**Redis has one accessor: `get_redis()`.** The client is a module global in
`src/core/redis.py`, and callers reach it by *calling* the accessor rather than holding a
reference from import time — which is what makes one swap of `src.core.redis._redis` redirect
every Redis-backed control in the process at once. Reach past it (`await _redis.set(...)` in a
helper, or a second `Redis.from_url`) and that code path silently opts out of the swap: it then
reaches a **live** Redis from a tier that forbids one, and reports it as `Event loop is closed`
from a second event loop rather than as anything resembling the cause. That cost real debugging
time twice before `tests/unit/core/test_redis_single_accessor.py` was written to fail the build
instead. Taking the client as an argument (`single_flight(..., redis: Redis)`) is equally fine and
often better — importing the *type* is not the violation, constructing a *client* is. The two
Celery tasks that build a deliberate **sync** client are a documented exception; their reasoning
is in the code.

Every I/O path is async — DB sessions, HTTP clients, Celery task bodies. A Celery task must
never call `asyncio.run` itself; it strands pooled asyncpg connections on a dead loop and kills
the *next* scheduled task. Use the project's `run_task` helper (pinned by
`tests/unit/core/test_task_loop_hygiene.py`).

## Auth and sessions

The security model, because it is spread across `core/security.py`, `users/services.py` and
Redis:

* Access tokens live 15 minutes, refresh tokens 7 days, and refresh tokens **rotate**: every
  refresh invalidates the presented token and issues a fresh pair.
* Rotation is what makes **replay detectable**. Refresh tokens are rows in `auth.refresh_tokens`
  carrying a parent link, so a session is a family tree. Presenting an already-used token means
  the token leaked: the whole family is revoked and every session for that user ends. This is
  deliberate, it is scoped to the one family, and it is why the e2e tier cannot reuse
  `storageState`.
* Refresh tokens travel only as `HttpOnly; Secure; SameSite=Lax` cookies.
* Login hashes a dummy password when the account does not exist, so timing does not disclose
  which emails are real. The failure message is identical on both paths for the same reason.

## House style

* Docstrings on modules, classes and public functions carry the *why* — the part no reader can
  recover from the code.
* **Everything written for a developer is in English**: docstrings, comments, test names, commit
  messages. This line used to say Russian was fine in a docstring and it was wrong — the codebase
  is English-identified throughout, so a Russian sentence explaining an English name reads as two
  halves of different files, and the same rule has a mechanical edge on the commit side
  (`git-workflow`).
* **Everything written for a user stays Russian**: UI copy, exception messages, alert text. That is
  not a leftover, it is enforced — `backend/tests/unit/core/test_messages_are_russian.py` fails on
  an English one. `allowed-confusables` in `backend/pyproject.toml` keeps RUF001-003 off the
  Latin-lookalike letters those strings are built from; the list is per LETTER and not per context,
  so a Russian word outside it (a «б», say) trips the check wherever it is written.
* Routes declare their status code and their documented failure responses explicitly.
* `make lint typecheck` (ruff, eslint, `mypy --strict`) is a gate, not a suggestion.

Tests have their own skill (`testing`); WB request/response shapes have theirs
(`wildberries-api`).
