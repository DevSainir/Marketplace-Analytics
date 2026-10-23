# Observability

What this service publishes about itself, where it goes, and the decisions that
are load-bearing rather than conventional: metrics, exception aggregation,
centralised log collection and real-time alerting.

The argument against building any of it early was that a `/metrics` nothing
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
  every container ─────►│   Grafana    │  grafana.example.com (nginx)
   (stdout, JSON)       └──────▲───────┘
        │                      │
        │   ┌───────┐   ┌──────┴──┐
        └──►│ Alloy │──►│  Loki   │   14d retention
            └───────┘   └─────────┘

  Prometheus ──► Alertmanager ──► telegram-relay ──► Telegram   (IPv6 + IPv4, host network)
  Sentry  ◄──── api + worker, errors only, scrubbed before sending
  external uptime monitor ────► https://…/healthz          (Postgres + Redis, 200 or 503)
  external uptime monitor ────► https://…/healthz/alerts   (is Watchdog firing: alerts-ok / alerts-down)
```

Two commands, and the separation between them is deliberate:

```bash
make up        # the service
make obs-up    # the stack that watches it
```

The application is instrumented whether or not the second ever runs. `/metrics`
and `/healthz` are in the API image and the counters cost a few hundred floats,
so turning the monitoring off costs visibility and nothing else — which is the
property you want on a small host the moment memory gets tight.

**Two compose projects, not one, and this was learned the hard way.** The
monitoring started as an overlay on the application's project, which put it in
reach of `docker compose ... up -d --remove-orphans` on the application: a
service that belongs to the project but is absent from the file compose is
handed is by definition an orphan, so **every such `up` silently deleted the
whole stack**, volumes left behind, nothing said — the failure mode monitoring
exists to catch, and the one it structurally cannot catch about itself.

It now runs as `marketplace-analytics-observability`, joining the application's network as
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

**Ids we put in a path.** Several WB paths interpolate an identifier, and the
settlement detail path (`sales-reports/detailed/{id}`) carries a new report id
every week. Raw, the harvest would add a permanent series per workspace per
report — memory that grows with our *history*.
`src/integrations/wildberries/endpoints.py` collapses them to `/{id}`.

**Ids a stranger chooses.** A request to a path with no route would otherwise be
labelled with the raw path, so anyone scanning for `/wp-admin`, `/.env`,
`/admin.php` would create one permanent series per URL they tried —
unauthenticated, from the internet, in a process sharing a host with Postgres.
That is a memory-exhaustion primitive. `should_group_untemplated=True` puts all
of them on `handler="none"`, and a component test asserts it.

**`status="499"` is an abandoned read, not an error.** When the browser aborts
a GET mid-computation (a period switched, a page left), `src/core/disconnect.py`
cancels the handler — and with it the statement in PostgreSQL — and answers
nginx's 499 to nobody. The request log writes `request served` with that status
and the time it ran before the client left. It is a fixed code, so it adds one
series per route at most; it is outside every `5..` alert on purpose. A rising
499 rate on one route says the route is slower than the people opening it are
patient.

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
"you cannot read the logs" is not one to run alone on a single host.

---

## The health endpoints, which are not interchangeable

| endpoint | served by | what it means |
|---|---|---|
| `/healthz` on **port 8081** | nginx itself | each nginx's Docker HEALTHCHECK, and the edge proxy's (HAProxy) check of where to route. Static `ok`. The one nginx listener without PROXY protocol, since neither checker sends it; not published. |
| `/health` | the API | **liveness**. Static. Docker restarts a container that fails it — which is exactly why it must not touch a database. |
| `/healthz` on **443** | the API, via nginx | **readiness**. Pings Postgres and Redis; 200 or 503. What the external uptime monitor polls. |
| `/healthz/alerts` on **443** | the API, via nginx | **whether alerts get out**. Asks Alertmanager if `Watchdog` is active; 200 `alerts-ok` or 503 `alerts-down`. Watched externally as a keyword monitor on `alerts-ok`. See «Delivery». |

Conflating the liveness and readiness probes is the tempting mistake and it is a
bad one: a liveness probe that fails because Postgres is down would have Docker
restart every healthy API process in the middle of a database outage.

**The scrape runs the same probe, and that is not redundancy.** `dependency_up`
used to be written only by `/healthz`, which made the `DependencyDown` alert
(`dependency_up == 0`) quietly conditional on an external monitor existing and
polling: with nobody polling, the series is absent after a restart, and an alert
with no series never fires. The rule read as covering Postgres and Redis while
covering nothing, and the dashboard was green either way. Prometheus now drives
the probe itself every 15 s, so the internal alert and the external check answer
the same question independently instead of one depending on the other.

The readiness probe never carries an exception, a host or a DSN — the API's
error path does not disclose those, and a public probe is the easiest place to
put that class of disclosure back without noticing. It runs both checks
concurrently under a 2 s budget each, so the worst case is the largest timeout
rather than their sum.

`nginx.ci.conf` deliberately keeps a *static* `/healthz` on its public port: it is
CI's up-check (the container's own healthcheck moved to :8081 together with the
main config's), and making it depend on Postgres would turn a slow database start
into an e2e run that times out. The divergence is commented in the file so nobody
"fixes" it.

---

## What is exposed, and to whom

**Nothing new is published to the internet.** The base topology's rule — one
published port, 443, serving the SPA — is unchanged.

* `/metrics` on the API is **not proxied by nginx**. Prometheus reaches
  `api:8000` on the internal Docker network. `METRICS_TOKEN` is a second lock
  for the day that topology is loosened; it is compared in constant time and
  answers **404**, not 401, so the route is not confirmed to exist.
* The worker's exporter binds `:9100` inside the network only.
* **Grafana is served on its own host**, `https://grafana.example.com`,
  proxied by the app's nginx over the shared Docker network.

  A **subdomain rather than a path**, and the reason is the cookie jar. As
  `example.com/grafana/` it would share a browser origin with the
  customer-facing SPA — so a flaw in Grafana would sit inside the same origin as
  the sessions that authenticate sellers, and the app's CSP
  (`script-src 'self'`) would have to be loosened to let Grafana's own bundle
  run at all. A separate host costs one DNS record and one name on the existing
  certificate, and buys a boundary the browser enforces.

  In front of it: TLS, `Secure`/`SameSite=lax` session cookies, HSTS, no
  sign-up, no anonymous access, and an nginx rate limit of 1 r/s with a burst of
  5 on `/login` answering **429**. The limit is on `/login` alone — on `/` it
  would throttle a signed-in session refreshing panels every 30 s. Grafana emits
  its own CSP; nginx deliberately does not apply the app's, because the tempting
  shortcut when the page comes up blank is to loosen the *shared* snippet, which
  weakens the customer site to make a dashboard load.

  Grafana also publishes `127.0.0.1:3000` on the host's loopback, which is the
  way in when nginx itself is the broken thing. That port must never lose its
  `127.0.0.1:` prefix — it is the bypass around the TLS, the headers and the
  rate limit.

* **The certificate must cover all three names and renew by `webroot`.**
  Written as a requirement, not a description. A `standalone` authenticator asks
  certbot to bind port 80 while nginx holds it, so every automatic renewal fails
  — and nothing reports it; the symptom, a month later, is the whole site
  becoming unreachable.

  `backend/scripts/tls/issue_certificate.sh` sets the method, adds the name,
  installs the deploy hook and reloads nginx in one run — see the procedure
  below. The webroot is a host directory bind-mounted into the frontend
  container read-only: certbot writes on the host, nginx reads in the container;
  a webroot inside the image is one certbot could never reach.

  The pairing is guarded by `frontend/tests/integration/tls-domains.spec.js`,
  which asserts every name in the script's `DOMAINS` is answerable by the
  port-80 server and that the ACME location is not swept into the HTTPS
  redirect.

### Bringing a public subdomain up, in order

The order is not a preference. Each step is a precondition for the next, and
the middle of it is a window in which the name is **hard down** rather than
degraded — HSTS `includeSubDomains` is already promised for the apex, so a
browser will not offer a click-through on the certificate mismatch and will not
fall back to plain HTTP.

1. **DNS first.** An `A` record for the subdomain pointing at the host. HTTP-01
   validation reaches the host by resolving the name, so the certificate cannot
   be requested before this exists — `issue_certificate.sh` checks with
   `getent hosts` and refuses rather than half-rewriting the renewal config.
2. **Certificate second**, on the host as root:
   `bash backend/scripts/tls/issue_certificate.sh`. It expands the existing
   lineage (`--cert-name`, so the paths nginx references do not move), switches
   renewal to `webroot`, installs the reload hook, and reloads nginx.
3. **Verify on the wire**, not on disk. A renewed file and a served certificate
   are different facts — that gap is what the reload hook exists to close.

Nothing in nginx or Grafana's compose config needs editing for a subdomain that
is already configured: the server block, the login rate limit, `GF_SERVER_ROOT_URL`
and the secure-cookie settings are all in place.

* Prometheus, Loki, Alertmanager and Alloy publish nothing at all.
* Alloy's Docker socket mount is **read-only** — a writable one is root on the
  host, and it only needs to list containers and read their output.

---

## Sentry

Initialised in **both** runtimes. The worker is the half that matters more: an
exception in a request is answered with a 500 somebody sees, an exception in the
nightly harvest is a night of missing data that surfaces as a customer asking why
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

`docker/observability/alerts.yml`, 35 rules in seven groups. Two conventions:
`for:` is zero only where a single occurrence is itself the event (an alert on a
level that fires on one bad scrape fires on every restart, and an alert that
fires on every restart gets muted), and every annotation says what to *do*,
because the person reading it at 03:00 is not the person who wrote it.

Some are worth calling out:

**`RowLevelSecurityViolation`** — `for: 0m`, one occurrence is the alert. It
should read zero forever. RLS fails closed, so an increment means no data
crossed a boundary and the control worked; what it means is that a code path is
reaching tenant data without passing the tenancy choke point, which is the exact
defect the policies were installed to catch (see
`docs/security/SECURITY_DESIGN.md`).

**`HarvestProducingNoRows`** — the second clause is what makes it meaningful:
the harvest *ran* and wrote nothing, which is a different event from "the
harvest did not run". A harvest can report SUCCESS with `funnel_rows: 0` for days
while users pressing "Refresh" watch unchanged numbers. No task-level success
metric can see that.

**`SecurityControlDegraded`** — binds to the degradation ledger
(`src/core/degradation.py`). Two of these at once is the correlated failure that
ledger was built to surface.

**`WorkerKilled` and `WorkerMemoryNearLimit`** — added after prefork children
were OOM-killed with no trace in Prometheus at all. Both gaps were structural
rather than an oversight. The worker publishes no
`process_resident_memory_bytes`, because multiprocess mode drops
`prometheus_client`'s default process collector — so the two API containers
reported a resident set and the one container whose working set is driven by
data volume reported none. And a killed child's task lands in
`celery_tasks_total{state="failure"}`, where three events in half a day is
0.00007/s against `TaskFailureRate`'s threshold of 0.05.

So the memory figure comes from a **collector reading the cgroup**
(`CgroupMemoryCollector`, registered on the worker's registry because the worker
has no exposition route to sample from), publishing
`celery_worker_memory_bytes` against `celery_worker_memory_limit_bytes` — the
kernel's own two numbers, the pair it compares before sending the signal. And
`celery_worker_lost_total` counts the abandonment separately from the failure,
because it is a different event: nothing unwound, nothing was logged by the
task, and `acks_on_failure_or_timeout` acknowledges the message on the way past,
so the work is not retried. Note the ratio's shape: a cgroup with no limit
publishes no ceiling at all rather than a zero, which leaves the alert's
expression undefined instead of confidently wrong.

**`WorkerMetricsDirFilling`** — added after `WorkerKilled` fired for hours about
something that was not memory. The worker's counters live in mmap files on a
32 MB tmpfs (`/tmp/prometheus-multiproc`), and a write past its last page is
**SIGBUS**: every task, and the healthcheck, died on start until the worker was
restarted. What filled it was the healthcheck itself — `celery inspect ping`
imports the app, and each import in multiprocess mode left a `counter_<pid>.db`
and a `histogram_<pid>.db` that `mark_process_dead` keeps by design; the earlier
sweep only ever removed gauges. The ping now runs with
`PROMETHEUS_MULTIPROC_DIR=` (empty means absent, so it counts in memory), and
`MetricsDirCollector` publishes `celery_worker_metrics_dir_bytes` against
`celery_worker_metrics_dir_size_bytes` from `statvfs`, so the next leak is a
warning at 70% rather than an outage. `WorkerKilled`'s text now says to read the
signal first: 9 is memory, 7 is this.

Two rules came out of it, both enforced by tests rather than by remembering:

* **A process that is not a prefork child leaves no metric file behind.**
  Importing `src.core.observability.metrics` arms an exit hook
  (`metrics/lifecycle.py`) that deletes every `*_<pid>.db` of that process, so
  a new script, shell or entry point cannot leak however it is started. Children
  are exempt — their counters are the harvest's — by pid, not by luck.
  `test_worker_metrics_dir.py` runs each entry point in a fresh interpreter, and
  fails if a metric is ever defined outside the `metrics` package, where nothing
  would arm the hook.
* **A worker that keeps failing its healthcheck restarts itself.** Docker never
  restarts an `unhealthy` container, which is why that outage lasted hours.
  `docker/worker_healthcheck.sh` counts failures in a row on its own tmpfs and
  sends PID 1 SIGTERM (warm shutdown) at six — three minutes — and SIGQUIT at
  twelve; the restart policy does the rest, and the restart empties both tmpfs
  mounts. `test_worker_healthcheck.py` runs that script against a stand-in.

**`PostgresCrashRecovered`** — added after OOM kills inside the postgres
container left no trace in Prometheus. None could: the postmaster survives a
killed backend and reinitialises in about two seconds, well inside one 15 s
scrape, so `dependency_up` never read 0. What outlasts the recovery is
`pg_stat_bgwriter.stats_reset` — PostgreSQL discards its statistics after a crash
and at no other time a running system chooses by itself — so the API publishes
it at scrape time as `postgres_stats_reset_timestamp_seconds`, and the rule
fires when it moves. It also explains a symptom that looks unrelated: after
each kill, every `pg_stat_*` counter restarts from zero, so `n_live_tup` can read
wildly low.

The kills themselves were bulk writes, not the backup. In the kernel reports two
or three backends held 40-90 MB of anonymous memory against ~5 MB for the rest;
reproduced on PostgreSQL 16, a multi-row `INSERT … VALUES … ON CONFLICT` at
30 000 parameters left 25 MB on its connection after one batch and 58 MB after
four sizes, through a rollback, because asyncpg prepares and caches every
statement and each batch size was a new one. `src/core/upsert.py` now sends one
row-wide statement through `executemany` — 2 MB, and eight times faster. The
large virtual size of those backends is JIT's LLVM mapping, not memory:
measured, loading it moves `VmSize` by ~190 MB and `RssAnon` by a few.

**`WbRateBlockEscalating`** — it exists because the quantity it watches had no
metric at all. The three metrics next to it describe WB's limiter as a *level*:
`wb_rate_limit_quota_remaining` is a gauge nothing decays (its own comment
explains why it cannot be alerted on), and `wb_rate_limit_wait_seconds_total`
counts how long we queued. A penalty block is neither — it is an **event with a
magnitude**, and what matters is the magnitude growing from one event to the
next.

`wb_rate_limit_block_seconds` is therefore a histogram, observed once per block
with the wait WB itself demanded in `X-Ratelimit-Retry`, with buckets running
from a minute to a week. The span is not defensive: WB has been observed to
escalate consecutive penalty blocks on one endpoint from about nine hours to over
a hundred, and buckets stopping at an hour would have recorded all of them as
`+Inf`. That escalation was found by reading logs, which is the failure this
rule is meant to replace.

It records what WB **demanded**, not the longer block we then serve. The margin
in `penalise` is our policy (`_BLOCK_MARGIN`, 1.25) and folding it in would make
the series describe us rather than WB.

*Retired: `settlement_publication_spread_hours` and `record_publication_spread`
are deleted, because the question was answered — WB publishes a settlement
period to all sellers at once, and the spread we recorded was our own sequential
loop. The note below is kept as the reasoning that built it.*

The metric was added to answer a design question and then, most likely, to be
deleted. On the day WB forms a settlement report every seller spends its own
quarter-hourly requests asking the same thing — «are you serving it yet» — and
one answer could serve the whole fleet, which at fifty sellers is the difference
between a ceiling of twenty-three per egress address and ninety-one. That is only
true if WB publishes to everyone at once, and nothing we held said whether it
does. The histogram recorded how long after the first seller each one received
the same period.

Read as an **upper bound** on WB's own spread, never as a measurement of it: our
probe cadence, our rate budget and any tick a seller missed are all inside the
figure. A distribution piled into the bottom bucket is conclusive — WB published
simultaneously and we watched it. A wide one is ambiguous, and the logs, which
carry `workspace_id`, are where it gets interpreted. The usual split: the metric
says whether the fleet saw it together, the logs say who was late.

**`settlement_payout_divergence`** is the absolute gap, per booked settlement
report, between WB's own `forPaySum` from `sales-reports/list` and our Σ
`ppvz_for_pay` with every refund document negated. It is observed the moment
a report is booked, when rows and total come from the same fetch, so a gap is
ours rather than a later restatement by WB. `SettlementPayoutDisagreesWithWb`
fires on any report a rouble or more out. The log line («totals … here against
WB's») carries the report id and the difference.

**`monitoring_funnel_gap_days`** is the funnel's twin of the settlement gap: days
older than the nightly cohort pass's window, still inside WB's 365-day reach,
where an article sold and the row still lacks WB's own `orderSum` or its matured
cohort. The failure it covers: the backfill lane leaves a day to a pass that, the
next night, no longer reads it, and that day's order sums stay missing with every
run green. The cohort pass now re-reads up to two such days per workspace per
night (`monitoring/tasks/funnel_gaps.py`) and sets the gauge to what is left;
`FunnelHistoryHasGaps` fires when it stays above zero for 26 hours. Idle rows (no
orders) never count — WB's aggregate omits them, so their cohort stays empty for
good. The log line («has N funnel day(s)») names the workspace and the days.

### The backfill group, and why it alerts on an absence

A new organisation's history arrives as four lanes of self-enqueueing ticks —
catalogue, funnel, advertising, P&L. The chain has exactly one thread of
continuation: a tick does one bounded step and enqueues the next. So a tick that
dies before reaching its re-enqueue ends the whole walk, and **nothing reports
it**. No exception reaches a caller, no work-done counter moves, the lane simply
stays where it stopped. A P&L lane that died on its first tick once sat there for
eleven hours, and was found only because a person happened to look.

Every metric the harvest already had measures what a run DID, and this failure
is the absence of a run. So the signal is a gauge of what is *stuck*:

| Series | What it answers |
| --- | --- |
| `backfill_lanes_stalled` | Is anybody's history not arriving right now? |
| `backfill_lane_restarts_total{lane}` | Is the watchdog trying to fix it? |
| `backfill_lane_failures_total{lane}` | Are ticks dying, and how often? |

The three alerts read them as a set, because the pairs mean different things.
`NewOrgBackfillStalled` is a lane nothing has revived. `NewOrgBackfillRestartLoop`
is restarts happening *and* the stall persisting — the watchdog working and not
helping, which is a poisoned cursor or a rejected token rather than weather.
`NewOrgBackfillFailing` fires on the deaths themselves, which move at the
exception rather than 45 minutes later, so it is the one that arrives with a
cause attached.

**None of them names a workspace, and cannot.** `/metrics` has no tenancy check
because it has no tenant. The alert says a lane is stuck; the *logs* say whose —
`workspace_id` is on every line, and the annotation carries the Loki query. The
Grafana dashboard's first block pairs them: the gauge and the counters on the
left, the matching log stream on the right.

A fourth rule, `BackfillWatchdogNotRunning`, watches the watchdog. Every other
rule in the group reads a gauge that only the sweep writes, so a dead beat would
take the whole group quiet at the moment it started mattering — a gauge that is
never written never crosses a threshold. `absent()` covers the "never ran once"
case that an `increase() == 0` alone would miss.

The recovery itself is `workspaces.sweep_stalled_backfills`, on beat every
fifteen minutes: it restarts any lane that claims to be running and has not
moved in forty-five. It is idempotent — a lane resumes from the cursor in its
own row — so restarting a live one costs a duplicate page, not a duplicate walk.
`tests/unit/core/test_alert_rules.py` checks that every rule here names a series
the application actually publishes, because an alert on a misspelled metric
evaluates to nothing forever while its dashboard looks covered.

### Delivery

Alertmanager routes to **Telegram** — the same bot the backup job alerts with,
because an alert delivered somewhere nobody reads is indistinguishable from no
alert. Set `ALERT_TELEGRAM_BOT_TOKEN` / `ALERT_TELEGRAM_CHAT_ID` in
`backend/.env` to split monitoring onto its own bot; left empty it falls back to
`BACKUP_ALERT_TELEGRAM_*`.

**The road to Telegram goes through a relay.** From some networks a fresh TCP
connection to `api.telegram.org` fails a noticeable share of the time — dropped
SYNs, per connection — with IPv4 and IPv6 mostly failing at different moments.
Alertmanager's container has IPv4 only (the Docker networks here have no IPv6),
and on its own it makes one slow attempt and backs off.

So `telegram-relay` — HAProxy in TCP mode, in the **host's** network — sits in
between. It has both families, gives each connect two seconds, and retries up to
six times alternating between them, which turns a flaky road into a reliable
one. TLS runs end to end: Alertmanager still connects to `api.telegram.org`
(pinned to docker0 by `extra_hosts`) and checks Telegram's certificate; only the
port in `api_url` (7443) says "relay". The relay listens on docker0's address,
not a wildcard, and forwards to Telegram's addresses and nowhere else.
`tests/unit/core/test_telegram_relay_wiring.py` pins all of that across the four
files it lives in. A dual-stack relay was chosen over an IPv4-only one inside
Alertmanager's own namespace, which would have opened nothing on the host but
would go silent the day the IPv4 road does.

The relay health-checks both roads every ten seconds, and Prometheus scrapes it
(`telegram-relay` job). `TelegramRoadDown` (warn) fires when one road has been
down for six hours — the shape of an address that stopped answering.

**Who notices when alerts stop getting out.** Nothing that sends alerts can
report that alerts stopped, so the witness is outside the host. `Watchdog`
(`alerts.yml`, group `meta`) fires for as long as Alertmanager is scraped, no
Telegram delivery has failed in 30 minutes, and the relay has at least one road
up. It is routed to a receiver with nothing in it. The API's `/healthz/alerts`
asks Alertmanager whether it is active (`src/core/observability/alert_path.py`,
answer cached 15 s so a flood costs Alertmanager nothing), and an external
uptime monitor polls that page as a keyword monitor on `alerts-ok` — the same
monitor that already watches `/healthz`. Host down, Prometheus or Alertmanager
down, the relay down or out of roads, a delivery failing: each one turns the
page to `alerts-down` within a few minutes.

This pull design replaced a push heartbeat (`ALERT_HEARTBEAT_URL`) that was never
connected: pulling needs no account-specific URL in `backend/.env`, and keyword
monitors are widely available on free tiers. Telegram stays the only channel for
the alerts themselves.

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
`permission denied`. On a host where `chown` is not available the renderer
widens to 0644 and says so, rather than failing.

The message template uses **HTML, not Markdown**, and that is not cosmetic:
Telegram's Markdown parser rejects the whole message when underscores or
asterisks do not pair up, and metric names like `wb_api_requests_total` are full
of them. A monitoring system whose alerts fail to send because of a metric name
is worse than one with no formatting.

---

## Verified, not assumed

Run against the local stack, with the API and worker rebuilt from this code:

* `/healthz` answered 200 from the real container with live Postgres and Redis
  latencies in the low milliseconds.
* Prometheus scraped `api` and `worker` — the worker's exporter aggregating
  `celery_tasks_total` and `celery_task_duration_seconds` **across prefork
  children** through `prometheus_client`'s multiprocess mode.
* Every alert rule loaded and evaluated with no errors. The only alert firing
  was `ApiDown{instance="api_standby"}`, which genuinely is not running locally.
* Grafana provisioned both datasources (`OK` on each health check) and the
  dashboard, from files.
* **The Telegram notification path**, exercised against a local capture server
  standing in for `api.telegram.org` rather than against a real chat: a
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

## Resource ceilings

The stack is sized for one small host shared with the application, so every
service carries a memory ceiling in `docker/docker-compose.observability.yml`.
Together they add **928m** of ceilings on top of the base topology:

| | ceiling |
|---|---|
| prometheus | 320m |
| grafana | 224m |
| loki | 192m |
| alloy | 96m |
| alertmanager | 64m |
| telegram-relay | 32m |

Ceilings are not reservations — nothing is set aside, and the measured steady
state of the whole group is a few hundred MB — so over-subscribing the host's
memory with ceilings is intended, exactly as it already is for the base stack.

Two consequences are load-bearing rather than advisory:

* Prometheus retention is bounded by **size** (2 GB) as well as time. Time alone
  bounds how far back you can look; it does not bound the disk, because the disk
  is retention *multiplied by* series count — and series count grows when
  somebody adds a label.
* Loki's ingestion limits are set low (8 MB/s, 16 MB burst). A retry loop
  logging in a tight cycle is the realistic way a log store fills a disk, and
  taking Postgres down to keep every line of a runaway would be a poor trade.

If the host gains co-tenants or the customer list grows, **the first thing to
move off is Grafana** — it is the only one of these that is idle unless somebody
is looking at it, and pointing a hosted Grafana at this Prometheus and Loki costs
nothing here.

---

## Where things live

| | |
|---|---|
| `src/core/observability/scrubbing.py` | redaction, shared by logs and Sentry |
| `src/core/observability/metrics/` | every metric, defined in one place |
| `src/core/observability/collectors.py` | gauges sampled at scrape time |
| `src/core/observability/instrument.py` | HTTP metrics, `/metrics`, `/healthz` |
| `src/core/observability/celery_runtime.py` | worker exporter, task context, trace propagation |
| `src/core/observability/rls_watch.py` | counting tenancy refusals at the engine |
| `src/core/observability/sentry.py` | error reporting for both runtimes |
| `src/core/observability/health.py` | the readiness checks |
| `src/core/observability/alert_path.py` | `/healthz/alerts`: is `Watchdog` active in Alertmanager |
| `src/core/logging.py` | the structlog pipeline |
| `src/core/logcontext.py` | trace/request/actor/tenant/workspace binding |
| `docker/observability/` | Prometheus, alerts, Alertmanager, Loki, Alloy, Grafana provisioning |
| `docker/telegram-relay/haproxy.cfg` | the relay to Telegram, and the reasoning behind it |
| `scripts/observability/render_alertmanager_config.sh` | renders the Alertmanager config from `.env` |
| `docker/docker-compose.observability.yml` | the overlay |
