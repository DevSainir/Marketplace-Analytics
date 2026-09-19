---
name: frontend-architecture
description: How the Vue 3 SPA in frontend/ is structured — the core/ vs modules/ split, each module's index.js public API, the linted import boundaries, where fetching and state are allowed to live, and how the Axios client carries auth cookies and the workspace header. Use this whenever you add or edit anything under frontend/src — a view, component, Pinia store, route, or API call — or when you are deciding where a new piece of frontend code belongs. For colors, spacing, typography and page chrome, use the design-system skill instead (a new page usually needs both).
---

# Frontend architecture

Vue 3 with `<script setup>`, Vite, Pinia, Tailwind, Axios. Options API is not used anywhere;
neither is `this`.

## Shape

`src/core/` is the infrastructure layer — the Axios client and its interceptors, shared dumb
components, the router that aggregates module routes, global views, utils. `src/modules/<name>/`
is a business domain (`auth`, `profile`, `monitoring`, `finreports`): `api.js`, `store.js`,
`routes.js`, `views/`, `components/`, and an `index.js`.

## Boundaries — fatal, and linted

* **`index.js` is a module's only door.** It exports the routes, stores and functions the outside
  world may use; everything else is internal.
* **No horizontal imports.** `@/modules/monitoring` is allowed from another module;
  `@/modules/monitoring/views/Something.vue` is not.
* **`core/` stays domain-agnostic** — it must not import from `modules/`. The one exception is
  the main router collecting route arrays.
* **No parent-relative paths.** `../` anywhere is an error; use the `@/` alias.

All four are error-level rules in `frontend/eslint.config.js`, which auto-discovers modules from
the directory listing, so a new module needs no config change. Two rules ESLint cannot express
are asserted in `frontend/tests/integration/architecture.spec.js` instead: every module has an
`index.js`, and no `.vue` file exceeds **250 lines**. (`MetricsTable.vue` reached 1327 before
anyone noticed; that is why the test exists.)

## Where logic lives

Components under `components/` are dumb: props in, events out, never an Axios call. Fetching
belongs to the module's `api.js` and its Pinia store; `views/` compose the two. A child never
mutates a prop, and props are not destructured — `toRefs` when it is unavoidable.

## Talking to the backend

* One Axios instance, from `core/api/`. `baseURL` comes from `import.meta.env.VITE_API_URL` —
  never a hardcoded `localhost:8000`.
* `withCredentials: true` always, or the `HttpOnly` refresh cookie never makes the round trip.
* The workspace is a header: `X-Workspace-Id`, set by the interceptor from the selected workspace
  in `localStorage`.
* The auth surface has its own short timeout and retry ladder (`AUTH_TIMEOUT_MS`), separate from
  the long timeout report downloads need. They shared one 15 s timeout once, and a hanging
  backend turned into a ~50 s white screen; the measured budgets are in the `testing` skill's
  coverage map.

## House style

* Every component, composable and store carries a block comment saying *why* it exists — the part
  the code cannot state. **In English**, like every comment, JSDoc and test name in the repo.
* **Russian is for what a user reads**: labels, headings, placeholders, empty states, error text.
  English identifiers behind a Russian UI is how this codebase works — see `design-system` for the
  vocabulary those strings use, and `git-workflow` for the same boundary on commit messages.

## Running it

Dev is Vite on `:5173` proxying to Uvicorn on `:8000`; the backend's CORS middleware allows that
origin. Production builds to static `dist/` served by Nginx, which also reverse-proxies
`/api/v1/*` to FastAPI — so production has no cross-origin requests at all.

Locally the Vite server runs under pm2 (`frontend/ecosystem.config.cjs`); check `pm2 list` before
starting another one.
