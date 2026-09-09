# Tier contracts — what each tier owns, and why the layout is what it is

Read this when deciding where a test goes, or when a tier's setup surprises you.

## Contents

* [Layout, and why the repo root stays bare](#layout)
* [unit](#unit) · [component](#component) · [integration](#integration)
* [Contract testing between modules](#contract-testing-between-modules)
* [end-to-end](#end-to-end) · [performance](#performance)
* [CI/CD staging](#cicd)

## Layout

Backend tests divide by **speed first, then by module** — `backend/tests/<tier>/<module>/` — so
"run everything fast" and "run everything for `monitoring`" are both one command. Cross-stack
tiers live in the top-level `tests/` (`end-to-end/`, `performance/`), each with its runner config
beside it.

**Why the root stays bare.** The only tooling file at the repository root is the `Makefile`, and
it earns that place by being the single entry point: four runners (pytest, vitest, Playwright,
k6) across three directories, one command each. Every runner's *config* lives next to the tests
it runs — `backend/pyproject.toml`, `frontend/vite.config.js`, `tests/playwright.config.js`,
`tests/pytest.ini`.

Two consequences worth knowing:

* `tests/` has its own `package.json`, so Playwright resolves from `tests/node_modules`. It is
  not a second frontend; it holds no application code.
* `tests/pytest.ini` is still found automatically, because pytest searches the ancestors of its
  arguments. Its paths resolve against `tests/`, which is why it reads `pythonpath = ../backend`.

**Why the frontend differs.** Frontend unit specs stay next to the code they test
(`store.js` → `store.spec.js`) — the project's established convention, and moving them would
break what colocation buys: you cannot edit a module without seeing its tests.
`frontend/tests/integration/` exists only for flows with **no single owning file** — a spec
spanning the axios interceptors, the store and the router belongs to none of them. If a test can
name one owning module, it goes beside that module.

**Adding a module:** create its folder in every tier it needs. An empty tier folder is fine; a
test in the wrong tier is not.

## unit

Pure. No I/O of any kind. Mock what you must and keep it small and fast.

* Business rules, calculations, parsing, validation, state machines.
* Directory = module. `tests/unit/finreports/` holds finreports' math.
* Backend markers are applied automatically from the directory — never write `@pytest.mark.unit`
  by hand.

The bcrypt work factor is lowered session-wide (`tests/conftest.py`) so the tier stays under two
seconds. The shipped value is pinned by its own test.

## component

The real FastAPI app with persistence faked out. This tier owns the **wiring**: route paths and
HTTP verbs; the dependency graph resolving; auth, tenancy and role guards; request validation and
response-model shaping; cookies; domain error → HTTP status mapping.

A component test that reaches the database fails loudly (`_TripwireSession`). If you need a
database, the test belongs in `integration/`.

## integration

Real infrastructure. Only put a test here if it **cannot** be proved cheaper:

* SQL that lives in the database — `ON CONFLICT`, `ilike`, cascades, conditional `UPDATE` and its
  `rowcount`;
* transaction semantics, connection lifecycle, concurrency;
* Redis-backed primitives, including their fail-open behaviour;
* WildBerries clients against a mock HTTP transport — never live WB: it needs seller tokens, is
  limited to ~1 request/minute, and would make the suite depend on a third party;
* Celery's task registry and beat schedule;
* Alembic migration integrity.

**Infrastructure is auto-skipped, never auto-failed.** No Postgres means the tier skips with a
message saying how to start it, so `pytest` on a fresh laptop exits 0. CI provides the services
and therefore runs everything.

**Never the dev database.** Everything runs against `marketplace_test`, created on demand. Each
test is wrapped in a transaction that is always rolled back.

## Contract testing between modules

Cross-module contracts are guarded by the FastAPI-generated `openapi.json`
(`backend/tests/integration/contracts/`).

**Current status:** the monolith has **no module-to-module HTTP calls**. Modules talk in-process
through `contract.py`, where a breaking change is caught by mypy, not by a schema. The one
contract that genuinely crosses a process boundary is **API ↔ Vue SPA**, which generates its
client types from that document, so that is what these tests guard.

When a module starts calling another over HTTP or a queue, add its consumer-driven contract in
that folder and record the split in `coverage-map.md`.

## end-to-end

The fewer the better. Currently three journeys: auth, the monitoring morning flow, and the

* **Never mock anything.** A mocked end-to-end test is a slow integration test.
* Drive the UI as a user does — `getByRole`, `getByPlaceholder`, visible text. Never a CSS class:
  styling changes must not break tests.
* Assert what the *user* observes, not internal state.
* **Flakiness is a bug.** Fix the wait, never add a `sleep`. A test that has to be re-run is a
  test nobody trusts.
* **Write selectors against the running app, not against the source.** Reading a component and
  inferring a selector is how you get a suite that has never passed. Every locator here was
  corrected after a real run.

Two constraints inherited from the product:

* **One login per test, and the login budget is finite.** `storageState` cannot be reused: every
  app bootstrap rotates the refresh cookie, so a second context presenting the same cookie is a
  replay, and breach detection correctly revokes the account's sessions. That makes the auth rate
  limiter (10 attempts / 60 s per IP) a real ceiling — roughly ten authenticated tests per
  minute. The `signedIn` fixture waits the window out and retries once rather than reporting a
  throttle as a login failure; keep the tier small enough that it rarely has to.
* **There is no persistent desktop navigation.** Nav links, the profile link and logout all live
  behind the header's burger control at every viewport, so anything navigating by menu calls
  `openMenu(page)` first.

## performance

Not part of the pass/fail gate. Run deliberately; see `tests/performance/README.md` for commands.

Tool selection: pytest or Playwright wherever the question can be asked there; **k6 only where
sustained multi-VU load is the point**.

**Intercept `**​/api/v1/**`, never `**​/api/**`.** In dev, Vite serves the app's own source over
HTTP and `/src/core/api/axios.js` matches the broader glob — blocking it stops the SPA booting at
all, which mimics the bug under test while proving nothing.

What it must assert, beyond raw latency:

* **degrades gracefully** — overload yields 429/503, never 5xx or a reset;
* **recovers** — the service returns to normal once the spike drains;
* **does not drift** — latency in the back half of a constant-load run matches the front half
  (the leak detector);
* **stays bounded** — no request may hang; an unbounded tail is what freezes the SPA behind its
  header.

Thresholds are **objectives, not observations**. A threshold copied from today's numbers passes
forever and warns nobody. Never point this tier at production or the dev database.

## CI/CD

`.github/workflows/tests.yml`, staged so the cheapest gate fails first:

```
verify (lint, mypy, eslint, unit + component, frontend, integration)
   ├── end-to-end        nightly 23:30 UTC / manual only
   └── performance       manual only
```

Rules for keeping it that way:

* **No tier may depend on developer-machine state.** Anything not creatable by the workflow must
  be skipped, not assumed.
* **Every tier is one command.** If CI needs a bespoke incantation, the tier is misconfigured.
* **Nothing shared is mutated.** Test databases are created and dropped by the run that uses them.
* **Failure artefacts are uploaded** — Playwright traces and video, container logs. A red CI run
  with nothing to inspect wastes an afternoon.
