# Observability

What this service publishes about itself, where it goes, and the decisions that
are load-bearing rather than conventional. This closes the register's **P2.1**
(metrics, exception aggregation) and the open half of **P2.2** (centralised
collection, real-time alerting).

The register's argument for leaving it unbuilt was that a `/metrics` nothing
scrapes and a Sentry client with no DSN are scaffolding pretending to be
observability. So every sink here is off until its destination exists, and
`sentry_enabled` is *derived* from whether a DSN was supplied rather than being
a flag that can disagree with one.

---

## The shape of it

```
                        ┌──────────────┐
  api, api_standby ────►│  Prometheus  │◄──── worker (:9100, its own exporter)
      (:8000/metrics)   └──────┬───────┘
                               │  scrape 15s · 15d / 2GB retention
                        ┌──────▼───────┐
  every container ─────►│   Grafana    │  127.0.0.1:3000, SSH tunnel only
   (stdout, JSON)       └──────▲───────┘
        │                      │
        │   ┌───────┐   ┌──────┴──┐
        └──►│ Alloy │──►│  Loki   │   14d retention
            └───────┘   └─────────┘

  Prometheus ──► Alertmanager ──► Telegram   (page: immediate · warn: grouped)
  Sentry  ◄──── api + worker, errors only, scrubbed before sending
  Better Stack ────► https://…/healthz   (Postgres + Redis, 200 or 503)
```

Two commands, and the separation between them is deliberate:

```bash
make up        # the service
make obs-up    # the stack that watches it
```

The application is instrumented whether or not the second ever runs. `/metrics`
and `/healthz` are in the API image and the counters cost a few hundred floats,
so turning the monitoring off costs visibility and nothing else — which is the
property you want on a 3.8 GB box the moment memory gets tight.

**Two compose projects, not one, and this was learned the hard way.** The
monitoring started as an overlay on the application's project, which put it in
reach of the deploy's `docker compose ... up -d --remove-orphans`: a service
that belongs to the project but is absent from the file compose is handed is by
definition an orphan, so **every deploy silently deleted the whole stack**,
volumes left behind, nothing said. Two deploys did exactly that on 2026-09-05
before anyone looked — the failure mode monitoring exists to catch, and the one
it structurally cannot catch about itself.

It now runs as `marketplace-observability`, joining the application's network as
`external`. `--remove-orphans` on the app's project cannot see it. Service-name
DNS still works across the boundary because Compose gives every container a
network alias equal to its service name and Docker's embedded DNS resolves those
for anything on the network, project or no project. If the application stack is
down, the monitoring refuses to start with "network not found" — the right
answer, since there would be nothing to watch.

---

## The rule that governs every design choice here

**Metrics answer "is the system healthy". Logs answer "for whom".**

No metric is labelled by tenant. `workspace_id` and `organization_id` grow with
the customer list, so either as a label multiplies every series by the number of
sellers — but the stronger reason is that `/metrics` has no tenancy check,
because it has no tenant. Per-tenant series would put one customer's volumes
where every reader of the exposition can see them.

The per-tenant question is answered by the logs, which carry `workspace_id` on
every line. `tests/unit/core/test_metric_cardinality.py` fails the build if a
tenant-shaped label appears on a metric.

The same split governs Loki: only `service`, `container` and `level` are
promoted to labels. `trace_id`, `workspace_id` and `user_id` stay *inside* the
line and are searched by content — a `trace_id` label would be one Loki stream
per request.

---

## Cardinality is a security control, not housekeeping

Two ways this codebase could produce an unbounded label, and they are different
problems:

task id is a fresh UUID for every report. Raw, one nightly harvest would add a
permanent series per workspace per night — memory that grows with our *history*.
`src/integrations/wildberries/endpoints.py` collapses them to `/{id}`.

**Ids a stranger chooses.** A request to a path with no route would otherwise be
labelled with the raw path, so anyone scanning for `/wp-admin`, `/.env`,
`/admin.php` would create one permanent series per URL they tried —
unauthenticated, from the internet, in a process sharing a box with Postgres.
That is a memory-exhaustion primitive. `should_group_untemplated=True` puts all
of them on `handler="none"`, and a component test asserts it.

---

## Logs

`structlog` owns the pipeline; stdlib `logging` stays the transport. Every line
in the process — ours, uvicorn's, Celery's, SQLAlchemy's — goes through **one**
processor chain, reached through `ProcessorFormatter` on the handler.

That arrangement exists for the redaction processor. Libraries write lines about
the same request we do: an httpx warning carrying a proxy URL, a SQLAlchemy
error carrying a parameter, a Celery traceback carrying a task's arguments. A
scrubber wired only into our own logger would cover the call sites least likely
to leak and miss the ones most likely to.

### Redaction (`src/core/observability/scrubbing.py`)

Two independent nets, because they fail differently. **By key** catches
`password`, `token`, `authorization` — exhaustive over what it names, blind to
what it does not. **By value** catches JWTs (which is what a WB seller token
is), bcrypt digests, Fernet ciphertexts, `Bearer` headers and DSN passwords —
regardless of what the surrounding field is called, or whether there is one.
The second is the case that actually happens: nobody logs `{"token": ...}` on
purpose, they interpolate.

The same function scrubs Sentry payloads. One function, two sinks, so a pattern
added for the logs cannot be forgotten for the error reports.

**What is deliberately not redacted**: email addresses, workspace names, and the
identifiers. They are what make a line an answer rather than a fact. This hides
*credentials*, not *identity* — and the exemption list exists because the first
run of the scrubber ate `trace_id`, which is 32 hex characters and therefore
looks exactly like a digest.

### Correlation

Two identifiers, and they are not redundant:

| field | shape | scope |
|---|---|---|
| `request_id` | 12 hex | one HTTP request; returned as `X-Request-Id`, quoted by a customer |
| `trace_id` | 32 hex | spans processes; Sentry's own trace-id format |

A request that enqueues a harvest puts its `trace_id` in the Celery message
headers, and the worker binds the same value minutes later in another
container. One search returns the click and the work it caused.

Neither is accepted from the caller. A trace id arriving in a request header
would be a value chosen by whoever is being investigated.

### Rotation

Two layers, and only one of them matters for the disk:

* **Docker's `json-file` driver**, capped at `20m × 3` per service in
  `docker-compose.yml`. This is the one that protects the disk — a container's
  stdout is written by the daemon, so nothing Python does can bound it. Left at
  the default, a log grows until the partition is full, and a full partition
  takes Postgres with it.
* **`LOG_FILE`** with a `RotatingFileHandler`, for a process run *outside*
  Docker. Empty in every container.

What is rotated away has already been shipped to Loki and stays searchable for
Loki's own 14 days. What is on disk is the fallback for when Loki is the broken
thing — which is also why the Loki Docker *driver plugin* was refused: with it
installed, `docker logs` stops working, and a log pipeline whose failure mode is
"you cannot read the logs" is not one to run alone on a single box.

---

## The three health endpoints, which are not interchangeable

| endpoint | served by | what it means |
|---|---|---|
| `/healthz` on **port 80** | nginx itself | the frontend container's own Docker HEALTHCHECK. Static `ok`. |
| `/health` | the API | **liveness**. Static. Docker restarts a container that fails it — which is exactly why it must not touch a database. |
| `/healthz` on **443** | the API, via nginx | **readiness**. Pings Postgres and Redis; 200 or 503. What Better Stack polls. |

Conflating the last two is the tempting mistake and it is a bad one: a liveness
probe that fails because Postgres is down would have Docker restart every
healthy API process in the middle of a database outage.

**The scrape runs the same probe, and that is not redundancy.** `dependency_up`
used to be written only by `/healthz`, which made the `DependencyDown` alert
(`dependency_up == 0`) quietly conditional on Better Stack existing and polling:
with nobody polling, the series is absent after a restart, and an alert with no
series never fires. The rule read as covering Postgres and Redis while covering
nothing, and the dashboard was green either way. Prometheus now drives the probe
itself every 15 s, so the internal alert and the external check answer the same
question independently instead of one depending on the other.

The readiness probe never carries an exception, a host or a DSN — P0.3 removed
that class of disclosure from the API's error path, and a public probe is the
easiest place to put it back without noticing. It runs both checks concurrently
under a 2 s budget each, so the worst case is the largest timeout rather than
their sum.

`nginx.ci.conf` deliberately keeps a *static* `/healthz`: it is the frontend
container's healthcheck target there and CI's up-check, and making it depend on
Postgres would turn a slow database start into an e2e run that times out. The
divergence is commented in the file so nobody "fixes" it.

---

## What is exposed, and to whom

**Nothing new is published to the internet.** The base topology's rule — one
published port, 443, serving the SPA — is unchanged.

* `/metrics` on the API is **not proxied by nginx**. Prometheus reaches
  `api:8000` on the internal Docker network. `METRICS_TOKEN` is a second lock
  for the day that topology is loosened; it is compared in constant time and
  answers **404**, not 401, so the route is not confirmed to exist.
* The worker's exporter binds `:9100` inside the network only.
* **Grafana binds `127.0.0.1:3000`.** Reach it over an SSH tunnel:

  ```bash
  ssh -L 3000:127.0.0.1:3000 <the production alias>
  ```

  That is the whole access model, chosen over an nginx location with basic auth
  because Grafana holds a read view of every metric this service produces, and a
  second authenticated ingress is a second thing to get right.
* Prometheus, Loki and Alloy publish nothing at all.
* Alloy's Docker socket mount is **read-only** — a writable one is root on the
  host, and it only needs to list containers and read their output.

---

## Sentry

Initialised in **both** runtimes. The worker is the half that matters more: an
exception in a request is answered with a 500 somebody sees, an exception in the
06:00 harvest is a night of missing data that surfaces as a customer asking why
a number is stale.

`send_default_pii` is **off**, and that is a security decision rather than a
privacy preference: with it on, Sentry attaches request bodies, headers and
cookies — and on this API those carry passwords, reset codes, refresh cookies
and WB seller tokens. Its own scrubbing is a denylist maintained by somebody
else, applied to data we should not have transmitted in the first place.

What replaces it is small and deliberate: the log context — trace id, tenant,
workspace, account, route — as indexed tags, so a report answers "whose, and
during what" without carrying anything a caller submitted.

---

## Alerts

`docker/observability/alerts.yml`, 16 rules in five groups. Two conventions:
`for:` is never zero (an alert that fires on one bad scrape fires on a deploy,
and an alert that fires on a deploy gets muted), and every annotation says what
to *do*, because the person reading it at 03:00 is not the person who wrote it.

Three are worth calling out:

**`RowLevelSecurityViolation`** — `for: 0m`, one occurrence is the alert. It
should read zero forever. RLS fails closed, so an increment means no data
crossed a boundary and the control worked; what it means is that a code path is
reaching tenant data without passing the tenancy choke point, which is the exact
defect the policies were installed to catch (P2.5).

**`HarvestProducingNoRows`** — the alert that would have caught the 2026-07-30
incident on day one. The second clause is what makes it meaningful: the harvest
*ran* and wrote nothing, which is a different event from "the harvest did not
run". For days, every `harvest_sku_window` reported SUCCESS with
`funnel_rows: 0` while «Обновить» users watched unchanged numbers. No
task-level success metric can see that.

**`SecurityControlDegraded`** — binds to the P1.2 ledger. Two of these at once
is the correlated failure that ledger was built to surface.

### Delivery

Alertmanager routes to **Telegram** — the bot the backup job has alerted with
since it was written, because an alert delivered somewhere nobody reads is
indistinguishable from no alert. Set `ALERT_TELEGRAM_BOT_TOKEN` /
`ALERT_TELEGRAM_CHAT_ID` in `backend/.env` to split monitoring onto its own bot;
left empty it falls back to `BACKUP_ALERT_TELEGRAM_*`.

`severity: page` skips the grouping delay (`group_wait: 0s`, repeat hourly);
`severity: warn` groups for 30 s and repeats every four hours. An inhibit rule
stops `ApiDown` firing alongside `BothApiInstancesDown` — the specific fact
should not arrive buried between two general ones.

**The config is rendered, not committed.** Alertmanager has no environment-
variable substitution and no `chat_id_file` to pair with its `bot_token_file`,
so a working config either carries a live bot token or is generated.
`scripts/observability/render_alertmanager_config.sh` renders
`alertmanager.yml.template` into a gitignored `alertmanager.yml`, and `make
obs-up` runs it first. Start Alertmanager without it and the file is absent and
the container restart-loops — the loud failure, chosen over an empty config that
would start cleanly and alert nobody.

The rendered file is handed to uid 65534 at 0600 — the unprivileged user the
Alertmanager image runs as — rather than left root-owned. A root-owned 0600
config is unreadable to the container, and Alertmanager restart-loops with
`permission denied`; that is how this first reached production. On a host where
`chown` is not available the renderer widens to 0644 and says so, rather than
failing.

The message template uses **HTML, not Markdown**, and that is not cosmetic:
Telegram's Markdown parser rejects the whole message when underscores or
asterisks do not pair up, and metric names like `wb_api_requests_total` are full
of them. A monitoring system whose alerts fail to send because of a metric name
is worse than one with no formatting.

---

## Verified, not assumed

Run against the local stack on 2026-09-04, with the API and worker rebuilt from
this code:

* `/healthz` answered 200 from the real container with live Postgres (2.65 ms)
  and Redis (0.18 ms) latencies.
* Prometheus scraped `api` and `worker` — the worker's exporter aggregating
  `celery_tasks_total` and `celery_task_duration_seconds` **across prefork
  children** through `prometheus_client`'s multiprocess mode.
* All 16 alert rules loaded and evaluated with no errors. The only alert firing
  was `ApiDown{instance="api_standby"}`, which genuinely is not running locally.
* Grafana provisioned both datasources (`OK` on each health check) and the
  dashboard, from files.
* **The Telegram notification path**, exercised against a local capture server
  standing in for `api.telegram.org` rather than against the real chat: a
  `severity: page` alert rendered correctly through the HTML template, routed
  with no grouping delay, and arrived as a `sendMessage` call with the right
  chat id. `amtool check-config` validates the file but does **not** execute the
  message template, so a broken template would otherwise have failed at the
  first real alert.
* **The full log round trip**: a request served by a JSON-logging API container
  → Alloy → Loki, retrieved by querying Loki for its `trace_id`, with `level`
  promoted to a label and `trace_id`, `request_id`, `path` and `client_ip`
  inside the line.

Two things that first run surfaced and that are now fixed rather than noted:
the scrubber redacting `trace_id`, and Loki's `reject_old_samples_max_age`
being shorter than its own retention (which made the agent retry an
unsatisfiable batch on first start).

---

## Cost on the box

The VPS is 2 vCPU / 3.8 GB with no swap, and it hosts more than this stack. The
base topology already commits ~2.4 GB of ceilings. This adds **896m**:

| | ceiling |
|---|---|
| prometheus | 320m |
| grafana | 224m |
| loki | 192m |
| alloy | 96m |
| alertmanager | 64m |

That is ~3.3 GB of *ceiling* against 3.8 GB. Ceilings are not reservations —
nothing is set aside, measured steady state for the five is roughly 250–350 MB
together — so the over-subscription is intended, exactly as it already is for
the base stack.

**The honest reading is: this fits, and it is the last thing that fits.** Two
consequences are load-bearing rather than advisory:

* Prometheus retention is bounded by **size** (2 GB) as well as time. Time alone
  bounds how far back you can look; it does not bound the disk, because the disk
  is retention *multiplied by* series count — and series count grows when
  somebody adds a label.
* Loki's ingestion limits are set low (8 MB/s, 16 MB burst). A retry loop
  logging in a tight cycle is the realistic way a log store fills a disk, and
  taking Postgres down to keep every line of a runaway would be a poor trade.

If the box gains co-tenants or the customer list grows, **the first thing to
move off is Grafana** — it is the only one of the four that is idle unless
somebody is looking at it, and pointing a hosted Grafana at this Prometheus and
Loki costs nothing here.

---

## Where things live

| | |
|---|---|
| `src/core/observability/scrubbing.py` | redaction, shared by logs and Sentry |
| `src/core/observability/metrics.py` | every metric, defined in one place |
| `src/core/observability/collectors.py` | gauges sampled at scrape time |
| `src/core/observability/instrument.py` | HTTP metrics, `/metrics`, `/healthz` |
| `src/core/observability/celery_runtime.py` | worker exporter, task context, trace propagation |
| `src/core/observability/rls_watch.py` | counting tenancy refusals at the engine |
| `src/core/observability/sentry.py` | error reporting for both runtimes |
| `src/core/observability/health.py` | the readiness checks |
| `src/core/logging.py` | the structlog pipeline |
| `src/core/logcontext.py` | trace/request/actor/tenant/workspace binding |
| `docker/observability/` | Prometheus, alerts, Alertmanager, Loki, Alloy, Grafana provisioning |
| `scripts/observability/render_alertmanager_config.sh` | renders the Alertmanager config from `.env` |
| `docker/docker-compose.observability.yml` | the overlay |
