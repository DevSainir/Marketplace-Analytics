# One command per pyramid tier — the single entry point for running tests.
#
# This is the ONLY tooling file at the repository root, and it earns that spot
# by replacing the need to remember four different runners in three different
# directories: pytest in backend/, vitest in frontend/, Playwright and k6 in
# tests/. Each of those keeps its own config next to its own tests; this file
# just knows which one to call.
#
# The tiers are ordered by cost. `make test-fast` is what you run before every
# commit; the tiers below it need progressively more infrastructure and are the
# reason each one is a separate target rather than a single `make test`.
#
# See `.claude/skills/testing/SKILL.md` for what belongs in which tier.

# Every backend command goes through `uv run --project backend`: uv creates and
# syncs backend/.venv from uv.lock on demand, so there is no "activate the venv
# first" step and no way to run against a stale environment.
UV := uv run --project backend
# Compose resolves .env, env_file: and build contexts against the PROJECT
# directory, which it otherwise infers from the compose file's location
# (backend/docker/). Pinning it to backend/ is what makes those paths — and the
# Postgres/Redis passwords — resolve. See the header of the compose file.
# The local override is applied ONLY if it exists. Compose auto-merges
# `docker-compose.override.yml` only when it discovers the compose file itself;
# passing -f explicitly (which the --project-directory above forces) disables
# that, so it has to be named. `wildcard` is what keeps the VPS — where the file
# deliberately does not exist — on the closed base topology.
COMPOSE_OVERRIDE := $(wildcard backend/docker/docker-compose.override.yml)
COMPOSE := docker compose --project-directory backend \
	-f backend/docker/docker-compose.yml \
	$(if $(COMPOSE_OVERRIDE),-f $(COMPOSE_OVERRIDE))
# Throwaway stacks (CI's browser tier, or any host without a TLS certificate)
# add the plain-HTTP nginx overlay.
COMPOSE_E2E := $(COMPOSE) -f backend/docker/docker-compose.e2e.yml
# The observability stack (Prometheus/Alertmanager/Grafana/Loki/Alloy) is its
# OWN compose project, joined to the application's network from outside. It is
# not part of `make up`, and the deploy cannot touch it — which is the point:
# as an overlay on the app's project it was an orphan to every
# `--remove-orphans`, and every deploy deleted it. Prometheus still reaches
# `api:8000` and Alloy still reaches `loki:3100` because they share the
# network. The application is instrumented either way; nothing here is required
# to serve.
# NOT built on $(COMPOSE): the observability stack is its own compose PROJECT
# now, joined to the application's network from outside. It was an overlay on
# the app's project at first, and the deploy's `--remove-orphans` deleted the
# whole thing on every run — see the header of the file itself.
COMPOSE_OBS := docker compose --project-directory backend \
	-f backend/docker/docker-compose.observability.yml
# Its own project too, for the same --remove-orphans reason.
NPM := npm --prefix frontend
# Playwright and k6 live with the tests they run, not at the root.
TESTS_NPM := npm --prefix tests

.DEFAULT_GOAL := help
.PHONY: help test test-fast test-unit test-component test-integration test-backend \
        test-frontend test-e2e test-perf test-perf-frontend test-perf-load lint \
        format audit lock typecheck setup-test-db clean-test-db seed-e2e \
        up down stop start ps logs prune rebuild frontend-release \
        demo demo-logs demo-down \
        obs-up obs-down obs-ps obs-logs \
        backup backup-verify backup-list

help: ## Show this help
	@grep -hE '^[a-zA-Z0-9_-]+:.*?## ' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-22s\033[0m %s\n", $$1, $$2}'

# --------------------------------------------------------------------------- #
# Tier 1 — fast. No infrastructure. The pre-commit gate.
# --------------------------------------------------------------------------- #
test-unit: ## Backend unit tests (no I/O)
	cd backend && uv run pytest tests/unit

test-component: ## Backend component tests (real app, faked persistence)
	cd backend && uv run pytest tests/component

test-frontend: ## Frontend unit + integration specs (vitest)
	$(NPM) run test

test-fast: ## Everything that needs no database — run this before committing
	cd backend && uv run pytest tests/unit tests/component
	$(NPM) run test

# --------------------------------------------------------------------------- #
# Tier 2 — integration. Needs PostgreSQL + Redis (auto-skips without them).
# --------------------------------------------------------------------------- #
test-integration: ## Backend integration tests (real PostgreSQL/Redis)
	cd backend && uv run pytest tests/integration

test-backend: ## Every backend tier
	cd backend && uv run pytest tests

# --------------------------------------------------------------------------- #
# Tier 3 — end-to-end. Needs the whole stack plus a browser.
# --------------------------------------------------------------------------- #
test-e2e: ## Playwright user journeys against a running stack
	$(TESTS_NPM) run test:e2e

seed-e2e: ## Offline fixtures the browser tier needs (account, workspaces, the demo shop)
	cd backend && uv run python -m scripts.seed_e2e_fixtures

# --------------------------------------------------------------------------- #
# Separate layer — performance. Never point these at production.
# --------------------------------------------------------------------------- #
test-perf: ## Resource-exhaustion and race probes (pytest)
	$(UV) pytest -c tests/pytest.ini tests/performance

test-perf-frontend: ## "App loads forever" probes (Playwright)
	$(TESTS_NPM) run test:perf:frontend

test-perf-load: ## k6 load/spike/DDoS profiles (needs the k6 binary)
	k6 run tests/performance/monitoring/summary-load.js
	k6 run tests/performance/monitoring/matrix-spike.js
	k6 run tests/performance/users/auth-flood.js

# --------------------------------------------------------------------------- #
# Everything runnable without a browser or a load generator.
# --------------------------------------------------------------------------- #
test: test-fast test-integration ## Fast tiers + integration

# --------------------------------------------------------------------------- #
# Quality gates
# --------------------------------------------------------------------------- #
lint: ## Ruff + Prettier (backend + frontend + cross-stack tiers)
	# Every importable path, not just src/tests: main.py is the ASGI entrypoint,
	# alembic/ holds hand-edited migrations, and scripts/ runs against production
	# data. Leaving them out was a silent gap — drift had already reached
	# alembic/versions/ and half of finreports/.
	cd backend && uv run ruff check src tests main.py alembic scripts
	cd backend && uv run ruff format --check src tests main.py alembic scripts
	# The cross-stack pytest tier lives outside backend/, so it needs the config
	# passed explicitly or ruff would fall back to its defaults.
	$(UV) ruff check --config backend/pyproject.toml tests/performance
	$(UV) ruff format --check --config backend/pyproject.toml tests/performance
	$(NPM) run lint
	$(NPM) run format:check

format: ## Rewrite formatting in place (backend + frontend)
	cd backend && uv run ruff format src tests main.py alembic scripts
	$(UV) ruff format --config backend/pyproject.toml tests/performance
	$(NPM) run format

typecheck: ## mypy --strict on the backend source, entrypoint and scripts
	cd backend && uv run mypy src main.py scripts

audit: ## Dependency vulnerability audit (backend + frontend)
	# Audits the RUNTIME set only — what actually ships.
	cd backend && uv export --frozen --no-dev --no-emit-project \
		--format requirements-txt -o /tmp/marketplace-runtime.txt
	cd backend && uv run pip-audit --requirement /tmp/marketplace-runtime.txt \
		--strict --disable-pip
	# Production tree is the gate; the dev tree is reported but not blocking —
	# its remaining advisories have no fixed version published (see CI).
	$(NPM) audit --omit=dev --audit-level=high
	-$(NPM) audit --audit-level=high

lock: ## Re-resolve backend/uv.lock (run after changing a dependency in pyproject.toml)
	# CI (`uv sync --locked`) and the Docker build both refuse to run if the lock
	# no longer matches pyproject.toml, so this is what you run after editing deps.
	cd backend && uv lock

# --------------------------------------------------------------------------- #
# The stack
# --------------------------------------------------------------------------- #
# The frontend container serves a RELEASE DIRECTORY, not its own image: the SPA
# bundle and the nginx config live in .frontend-releases/ and the container
# follows a `current` symlink into it (frontend/docker/Dockerfile). That is what
# lets a deploy reload nginx instead of recreating the one container holding
# :443. The cost is that a release has to exist before nginx can start, so `up`
# stages one first. A deploy does the same two steps with an atomic flip, which
# this does not need because nothing is serving yet.
frontend-release: ## Stage the SPA bundle + nginx config the frontend container serves
	@mkdir -p .frontend-releases/releases
	DOCKER_BUILDKIT=1 docker build -f frontend/docker/Dockerfile --target release \
	  -o type=local,dest=.frontend-releases/releases/local frontend
	@# The exporter leaves this 0700; nginx workers are not root.
	chmod -R a+rX .frontend-releases/releases/local
	ln -sfn releases/local .frontend-releases/current

up: frontend-release ## Build and start the whole stack
	$(COMPOSE) up -d --build

down: ## Stop the stack and REMOVE its containers, keeping the Postgres/Redis volumes
	$(COMPOSE) down

# `stop`/`start` rather than `down`/`up` for the daily rhythm: `down` removes the
# containers, so the next `up` rebuilds. Parking them keeps the start to seconds.
# Neither frees the 2 GiB Docker Desktop reserves for its VM — quit the app for
# that; on an 8 GiB machine it is the difference between swapping and not.
stop: ## Park the stack, keeping the containers so `start` is instant
	$(COMPOSE) stop

start: ## Wake a parked stack — NOT a rebuild; run `up` after editing backend code
	$(COMPOSE) start

ps: ## Status of every service
	$(COMPOSE) ps

# --------------------------------------------------------------------------- #
# The demo — the whole stack on fabricated data. No WB token, no certificate.
#
# Its OWN compose project, so it never shares containers or a database with a
# `make up` stack on the same machine, and no local override: the edge on
# DEMO_HTTP_PORT is the only thing it publishes. What the overlay changes, and
# why, is in the header of backend/docker/docker-compose.demo.yml.
#
# `make demo` is safe to re-run: it rebuilds what changed and regenerates the
# demo data, re-dated so its newest day is yesterday.
# --------------------------------------------------------------------------- #
DEMO_PROJECT := marketplace-analytic-demo
DEMO_HTTP_PORT ?= 8080
DEMO_HTTPS_PORT ?= 8443
# The edge publishes "${FRONTEND_HTTP_PORT}:8080", so prefixing the port with an
# address is what keeps the demo on loopback rather than on every interface.
COMPOSE_DEMO := FRONTEND_HTTP_PORT=127.0.0.1:$(DEMO_HTTP_PORT) \
	FRONTEND_HTTPS_PORT=127.0.0.1:$(DEMO_HTTPS_PORT) \
	docker compose --project-directory backend -p $(DEMO_PROJECT) \
	-f backend/docker/docker-compose.yml -f backend/docker/docker-compose.demo.yml

demo: ## Run the app on fabricated data at http://localhost:8080 — no WB token needed
	@test -f backend/.env || { \
	  echo "backend/.env is missing. Create it from the template first:" >&2; \
	  echo "  cp backend/.env.example backend/.env" >&2; exit 1; }
	@# nginx mounts this directory; created here so Docker does not create it as root.
	@mkdir -p .frontend-releases
	$(COMPOSE_DEMO) up -d --build
	@echo "Waiting for http://localhost:$(DEMO_HTTP_PORT) to answer..."
	@for _ in $$(seq 1 60); do \
	  code=$$(curl -s -o /dev/null -w '%{http_code}' --max-time 5 http://localhost:$(DEMO_HTTP_PORT)/ || true); \
	  [ "$$code" = "200" ] && exit 0; sleep 2; \
	done; \
	echo "The demo did not start serving in time. See: make demo-logs" >&2; exit 1
	$(COMPOSE_DEMO) exec -T api python -m scripts.seed_demo
	@echo ""
	@echo "  Demo is up:  http://localhost:$(DEMO_HTTP_PORT)"
	@echo "  Log in as:   demo@example.com / demo-password"
	@echo "  Stop it:     make demo-down"
	@echo ""

demo-logs: ## Follow the demo stack's logs
	$(COMPOSE_DEMO) logs -f

demo-down: ## Stop the demo and DELETE its data (its own volumes only)
	$(COMPOSE_DEMO) down -v --remove-orphans

logs: ## Follow the logs of every service
	$(COMPOSE) logs -f

# --------------------------------------------------------------------------- #
# The observability stack — an overlay, started separately on purpose.
#
# `make up` does NOT start it, and `make obs-down` does not stop the service.
# The API and worker export /metrics and /healthz whether or not any of this is
# running, so turning it off costs visibility and nothing else — which is the
# property you want on a 3.8 GB box the moment memory gets tight.
#
# Alerts go to Telegram (the bot the backup job already uses, unless
# ALERT_TELEGRAM_* is set separately in backend/.env).
#
# Grafana is on 127.0.0.1:3000 only. Reach it with an SSH tunnel:
#     ssh -L 3000:127.0.0.1:3000 <host>
# --------------------------------------------------------------------------- #
# The renderer runs FIRST and is not optional: Alertmanager's config carries the
# Telegram bot token, so it is generated from backend/.env rather than committed.
# Starting the stack without it leaves the file absent and Alertmanager in a
# restart loop — which is the loud failure. See the template's header.
obs-up: ## Start Prometheus + Alertmanager + its Telegram relay + Grafana + Loki + Alloy alongside a running stack
	backend/scripts/observability/render_alertmanager_config.sh
	$(COMPOSE_OBS) up -d prometheus alertmanager telegram-relay grafana loki alloy

obs-down: ## Stop the observability stack, keeping its volumes (and the service up)
	$(COMPOSE_OBS) stop prometheus alertmanager telegram-relay grafana loki alloy

obs-ps: ## Status of the observability services
	$(COMPOSE_OBS) ps prometheus alertmanager telegram-relay grafana loki alloy

obs-logs: ## Follow the observability services' logs
	$(COMPOSE_OBS) logs -f prometheus alertmanager telegram-relay grafana loki alloy

# A backend rebuild writes a fresh image layer set every time; on a small host
# the accumulated build cache is what fills the disk and flips the Docker VM
# read-only (an empty-body 500 on /auth/login is the tell). `prune` reclaims it;
# `rebuild` prunes first so the build has room, then brings the stack back up.
prune: ## Reclaim the Docker build cache (run when a rebuild fills the disk)
	docker builder prune -af

rebuild: ## Prune build cache, then rebuild and start the stack
	docker builder prune -af
	$(COMPOSE) up -d --build

# --------------------------------------------------------------------------- #
# Database backups
#
# Cron runs `backup` on the VPS at 03:00 Europe/Moscow; these targets are for
# doing it by hand. See backend/scripts/backup/README.md for the gates, the
# tier rules and the restore procedure.
# --------------------------------------------------------------------------- #
backup: ## Dump, verify, encrypt and push the database to both object storages
	backend/scripts/backup/backup.sh

backup-verify: ## Full run WITHOUT uploading, including the restore rehearsal
	backend/scripts/backup/backup.sh --no-upload --force-deep-check

backup-list: ## List the backups currently held in both object storages
	backend/scripts/backup/restore.sh list

# --------------------------------------------------------------------------- #
# Test database helpers
# --------------------------------------------------------------------------- #
setup-test-db: ## Create/refresh the throwaway integration database
	cd backend && uv run pytest tests/integration/core/test_migrations.py -q

clean-test-db: ## Drop the throwaway integration database
	$(COMPOSE) exec -T postgres \
		psql -U marketplace -d postgres -c 'DROP DATABASE IF EXISTS marketplace_test WITH (FORCE)'
