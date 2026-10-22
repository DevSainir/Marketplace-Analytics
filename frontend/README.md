# Marketplace Analytics Frontend

Vue 3 (Composition API, `<script setup>`) + Vite + Pinia + Tailwind CSS + PrimeVue (unstyled mode).

## Commands

```bash
npm install          # install dependencies
npm run dev          # dev server on http://localhost:5173
npm run build        # production build into dist/
npm run lint         # ESLint incl. fatal architectural boundary rules
npm test             # Vitest suite (stores, interceptors, components)
npm run format       # Prettier over src/ and tests/
npm run types:api    # regenerate src/core/api/schema.d.ts from the backend
                     # OpenAPI schema (backend must run on localhost:8000)
```

## Configuration

The SPA needs no environment file: the project's one template is
`backend/.env.example`, and nothing in it is for the frontend.

The backend base URL is read from the environment — never hardcoded — but it
needs no configuration in either environment that exists. `src/core/api/axios.js`
falls back to the relative `/api`, which the Vite dev proxy serves in dev and
nginx serves in prod. The two optional variables:

- `VITE_API_URL` — point a *build* at a remote backend
  (e.g. `VITE_API_URL=https://staging.example.com/api npm run build`). Setting
  it to `/api` would be a no-op.
- `VITE_PROXY_TARGET` — where the dev server's `/api` proxy goes
  (default `http://localhost:8000`; see `vite.config.js`).

## Authentication

Session model: short-lived access token **in memory only** + HttpOnly refresh
cookie managed by the backend (`withCredentials: true` on the shared client).

- `src/core/api/axios.js` — attaches the Bearer header; on 401 it rotates the
  refresh cookie once (deduplicating concurrent 401s) and retries; if rotation
  fails it calls the unauthorized handler registered by the auth module.
- `src/modules/auth/` — `/login` view (sign-in and sign-up), `useAuthStore`
  (login / register / logout / `bootstrap()` silent refresh on app start) and
  `installAuthGuard(router)`, which gates `meta.requiresAuth` routes, bounces
  authenticated users off `meta.guestOnly` routes, and routes dead sessions to
  `/login?redirect=…`.
- The guard is installed from `main.js`, so `src/core` stays module-agnostic.

## Architecture

```
src/
├── core/                  # Infrastructure & shared global layer
│   ├── api/
│   │   ├── axios.js       # Base client, Bearer header, 401 refresh-retry
│   │   ├── schema.d.ts    # AUTO-GENERATED from OpenAPI — do not edit
│   │   └── types.d.ts     # Friendly aliases consumed via JSDoc
│   ├── components/        # Dumb shared UI
│   ├── router/index.js    # Aggregates module routes via Public APIs ONLY
│   ├── utils/             # formatters (ru-RU Intl), local-date helpers
│   └── views/             # Global pages (HomeView)
└── modules/               # Isolated business domains
    ├── auth/
    │   ├── api.js         # /v1/auth/* wrappers (refresh token never touched)
    │   ├── store.js       # useAuthStore — session lifecycle
    │   ├── guard.js       # installAuthGuard + safeRedirect
    │   ├── routes.js      # /login
    │   ├── views/         # LoginView
    │   └── index.js       # PUBLIC API CONTRACT
    ├── monitoring/
    │   ├── api.js         # /v1/monitoring/* endpoint wrappers
    │   ├── store.js       # useMonitoringStore — search, race-guarded fetch
    │   ├── routes.js      # /monitoring (requiresAuth)
    │   ├── use*.js        # composables: cell editing, paging, palette,
    │   │                  #   drag-reorder, assoc hover, URL sync, undo keys
    │   ├── *Model.js      # pure helpers: matrix columns, calendar grid
    │   ├── views/         # Smart views (search state synced to URL query)
    │   ├── components/    # Dumb presentational components
    │   │   └── styles/    # their stylesheets, `<style scoped src=…>`
    │   └── index.js       # PUBLIC API CONTRACT
    ├── finreports/        # P&L, cost prices, stock balance
    └── profile/           # workspace switching and token administration
```

Every component stays under 250 lines and every module exposes an `index.js`;
both are enforced by `tests/integration/architecture.spec.js`, not by review.

Boundary rules (fatal ESLint errors — see `eslint.config.js`):

1. **No horizontal imports** — modules may only use each other through
   `@/modules/<name>` (the module's `index.js`).
2. **core/ is module-agnostic** — only `core/router` may import module route
   arrays, and only via Public APIs.
3. **No parent-relative imports** — use the absolute `@/` alias.

Modules are auto-discovered by the linter: creating a folder under
`src/modules/` is enough. Register new routes in `src/core/router/index.js`.

## Testing

Colocated `*.spec.js` files run under Vitest (jsdom). Covered: the 401
refresh-retry interceptor, both Pinia stores (vendor-code resolution,
race protection, session lifecycle), redirect sanitization, and the search
bar's local-timezone date defaults.
