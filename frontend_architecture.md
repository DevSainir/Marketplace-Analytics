# Frontend Architecture & Development Guidelines

## 1. Tech Stack
* **Framework:** Vue 3.
* **API Style:** STRICTLY Composition API with `<script setup>`. Options API is strictly forbidden.
* **Build Tool:** Vite.
* **Styling:** Tailwind CSS (Utility-first approach).
* **State Management:** Pinia.
* **HTTP Client:** Axios.

## 2. Directory Structure
```text
frontend/src/
├── core/                  # Infrastructure & Shared Global Layer
│   ├── api/               # Base Axios client & interceptors
│   ├── components/        # Dumb shared UI (BaseButton, Layouts)
│   ├── router/            # Centralized router aggregating module routes
│   └── views/             # Global pages (e.g., HomeView)
│
└── modules/               # Isolated Business Domain Features
    ├── auth/
    │   ├── api.js, store.js, routes.js, views/
    │   └── index.js       # PUBLIC API CONTRACT
    │
    └── monitoring/
        ├── api.js, store.js, routes.js, views/, components/
        └── index.js       # PUBLIC API CONTRACT
```

## 3. Strict Coding Rules (Composition API)
* **Reactivity:** Use ref for primitives and reactive for objects. ALWAYS use .value when accessing or mutating ref inside the "script setup" block

* **Destructuring:** Never destructure props directly as it breaks reactivity. Use toRefs(props) if destructuring is absolutely necessary.

* **No this Keyword:** The codebase must not contain this. references.

* **Props Mutation:** Child components MUST NOT mutate props. Use defineEmits to send events back to the parent component for any state modifications.

* **Component Size:** Components must be kept small and modular. If a view exceeds 250 lines, abstract the UI elements into smaller components inside the components/ directory.

## 4. Strict Architectural Rules (The "Contract" System)
* **Public API (index.js):** Every directory inside src/modules/ MUST have a root index.js file. This file acts as the module's Public API Facade. It explicitly exports only the functions, stores, or routes that are allowed to be used by the outside world (e.g., export { analyticsRoutes } from './routes').

* **No Horizontal Imports:** A module (e.g., monitoring) is STRICTLY FORBIDDEN from importing deep internal files from another module (e.g., import X from '@/modules/auth/views/Login.vue'). If cross-module interaction is needed, it must ONLY go through the target module's index.js Public API.

* **Core vs Modules:** Modules can freely import from src/core/. However, src/core/ should remain agnostic and avoid importing business logic from src/modules/, except for the main router compiling the route arrays.

## 5. Separation of Concerns
* **UI vs Logic:** Components in the components/ folder should be "dumb" — they only receive props and emit events. They should NEVER make direct Axios calls.

* **Data Fetching:** All API requests should be handled either inside Pinia stores/ or dedicated service files within the api/ directory, which are then called by the smart views/.

## 6. Frontend-Backend Integration (The Connection Layer)
* **API Client:** Use `Axios` exclusively.
* **Base URL Management:** The frontend must NEVER hardcode `localhost:8000`. Axios must use an environment variable: `baseURL: import.meta.env.VITE_API_URL`.
* **CORS (Backend Requirement):** The FastAPI backend MUST be explicitly configured with `CORSMiddleware` to allow requests from the Vite development server (typically `http://localhost:5173`) and the future production domain.
* **Credentials:** Axios instances must be configured with `withCredentials: true` by default to ensure HttpOnly refresh cookies are successfully transmitted back and forth.

## 7. Runtime & Docker Orchestration
* **Development Mode:** Backend runs on `localhost:8000` (Uvicorn). Frontend runs on `localhost:5173` (Vite).
* **Docker Networking:** Inside `docker-compose.yml`, the frontend and backend must be on the same internal Docker network.
* **Production Build:** The Vite frontend should be built into static files (`dist`) and served via an Nginx container, which will also act as a reverse proxy, routing `/api/v1/*` traffic directly to the FastAPI container, avoiding CORS entirely in production.

## 8. Automated Linting (Boundary Enforcement)
* **ESLint Configuration:** The project MUST utilize ESLint configured with `@feature-sliced/eslint-plugin` (or strict `eslint-plugin-import` boundary rules).
* **Fatal Architectural Errors:** The linter config must explicitly throw an error (not a warning) if:
  1. Horizontal Import Violation: A file in `src/modules/A/` imports from `src/modules/B/` without using `src/modules/B/index.js`.
  2. Downward Import Violation: A file in `src/core/` imports business logic from `src/modules/` (except the main router importing route arrays).
  3. Relative Path Abuse: Deep relative imports (e.g., `../../../`) are used instead of absolute aliases (`@/`).
