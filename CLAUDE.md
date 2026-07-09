# CLAUDE.md — Project Guidelines & Commands

## 1. Strict Architectural Enforcement
You must strictly follow the rules defined in the standalone documentation files located in the root directory. BEFORE modifying or creating any code, read and comply with:
1. `architecture_rules.md` — For Clean Architecture boundaries, module isolation (`contract.py`), UUIDv7 primary keys, and multi-schema PostgreSQL setup.
2. `api_contracts.md` — For Wildberries API structures, data flattening, and the 3-step data normalization math (OOS masking, promo lift, seasonality).
3. `di_patterns.md` — For handling asynchronous dependency injection via `Annotated` in `src/core/deps.py` and local modules.
4. `frontend_design.md` — For Vue 3, PrimeVue integration, Axios configuration, and CORS/Docker connectivity
5. `frontend_design.md` — For Vercel/Tailwind UI aesthetics.

## 2. Code Style Notes
* **Imports:** Use absolute imports starting from `src.` ONLY. Relative imports are strictly forbidden.
* **Async:** All I/O, database sessions, and external API requests must be 100% asynchronous.
