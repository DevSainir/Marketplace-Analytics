# CLAUDE.md — Project Guidelines & Commands

## 1. Strict Architectural Enforcement
You must strictly follow the rules defined in the standalone documentation files located in
the `docs/rules/` directory. BEFORE modifying or creating any code, read and comply with:
1. `docs/rules/architecture_rules.md` — For Clean Architecture boundaries, module isolation (`contract.py`), UUIDv7 primary keys, and multi-schema PostgreSQL setup.
2. `docs/rules/api_contracts.md` — For Wildberries API structures, data flattening, and the 3-step data normalization math (OOS masking, promo lift, seasonality).
3. `docs/rules/di_patterns.md` — For handling asynchronous dependency injection via `Annotated` in `src/core/deps.py` and local modules.
4. `docs/rules/frontend_architecture.md` — For Vue 3, PrimeVue integration, Axios configuration, and CORS/Docker connectivity
5. `docs/rules/design_system.md` — For UI aesthetics.
6. `docs/rules/tests_rules.md` — For the testing pyramid: tier definitions, folder layout, Arrange-Act-Assert, fixture and mocking policy, and what belongs in which tier. Read this BEFORE writing or moving any test.
7. `docs/rules/current_tests.md` — A living inventory of what is currently covered. Update it whenever you add, move, or delete a test file.

This file (`CLAUDE.md`) stays in the repository root on purpose: it is the entry point
Claude Code loads automatically, and it is what points at `docs/rules/`.

## 2. Code Style Notes
* **Imports:** Use absolute imports starting from `src.` ONLY. Relative imports are strictly forbidden.
* **Async:** All I/O, database sessions, and external API requests must be 100% asynchronous.

## 3. Test Commands
Run from the repository root:

```bash
make test-fast        # backend unit + component, frontend unit — the pre-commit gate
make test-integration # real Postgres/Redis tier (auto-skips when they are unreachable)
make test-e2e         # Playwright user flows against the running stack
make test-perf        # k6 load/spike/DDoS profiles + pytest resilience probes
```

See `docs/rules/tests_rules.md` for the full command list and tier contracts.
