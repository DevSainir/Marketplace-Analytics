# Performance tier

These tests answer "does it hold up?", not "is it correct?". The directory
splits by how much of the world each half disturbs, and CI treats the two
halves differently because of it:

* **`resilience/` is a gate.** It runs in the `verify` job on every push, right
  after the integration tier and against the same throwaway database, because
  the pools and engines it exhausts are ones it creates and owns. Eleven tests,
  about four and a half seconds. It spent months behind a `run_slow_tiers` flag
  the nightly schedule never set, which meant it never ran at all — that is
  what made it worth moving rather than scheduling.
* **The k6 profiles run on their own schedule, on a hosted runner.**
  `.github/workflows/load.yml` runs the three short ones nightly and adds the
  hour-long soak on Sunday. They aim real load at a real API — 120 concurrent
  VUs in the spike, 60 requests a second in the flood — so they must never
  point at anything shared, which rules out the VPS that serves production.
  The workflow asserts `RUNNER_ENVIRONMENT=github-hosted` before generating a
  single request, and a unit test asserts the job never carries the
  `self-hosted` label.
* **The Playwright half is still run by hand.** It needs a running SPA and is
  in no workflow.

### Why the soak is weekly and an hour long

An hour is what it takes to see a slope. Ten minutes of samples through a noisy
series fits a line to almost anything, and the old profile did not even try: it
compared the opening minute against the closing one, against a fixed ceiling —
two points, which always fit perfectly, and a ceiling that passes a service
which doubled and fails one that was always slow and never moved.

An hour is also what makes it weekly rather than nightly. Hosted minutes are
the constraint that moved everything else onto the VPS; 65 minutes once a week
is about 285 a month, and nightly would be 2000 on its own.

## Layout

| Path | Runner | What it probes |
| --- | --- | --- |
| `resilience/` | pytest | Pool exhaustion, frozen transactions, connection leaks, write races |
| `users/auth-flood.js` | k6 | Credential-stuffing / DDoS on the auth surface |
| `monitoring/summary-load.js` | k6 | Steady-state dashboard load + latency drift (leak detection) |
| `monitoring/matrix-spike.js` | k6 | Spike, overload, and — the real assertion — recovery |
| `lib/regression.js` | — | The least-squares fit the soak's verdict rests on |
| `frontend/` | Playwright | The SPA loading forever behind a dead or hanging backend |

Split by runner because the question decides the tool: anything expressible in
pytest or Playwright stays there, and k6 is used only where sustained
multi-VU load is the point.

## Running

The pytest half needs only PostgreSQL and skips itself when it is missing:

```bash
make test-perf
```

The Playwright half needs the SPA running (`npm --prefix frontend run dev`):

```bash
make test-perf-frontend
```

The k6 half needs the [k6 binary](https://grafana.com/docs/k6/latest/set-up/install-k6/):

```bash
brew install k6
```

Then, against a running API — all four profiles in one go:

```bash
make test-perf-load
```

### The soak's knobs

```bash
# what CI runs on Sunday
```

| Variable | Default | What it changes |
| --- | --- | --- |
| `SOAK_MINUTES` | `10` | Minutes of held load, after the warm-up |
| `SOAK_RPS` | `10` | Request rate, held regardless of latency |
| `SOAK_WARMUP_MINUTES` | `2` | Load before the first sample, excluded from every fit |
| `SOAK_MIN_FIT` | `0.7` | How straight a line must be before its slope is believed |
| `SOAK_MAX_RSS_GROWTH` | `1048576` | Bytes/min of resident memory that counts as a leak |
| `SOAK_MAX_LATENCY_GROWTH` | `10` | ms/min of probe latency that counts as degradation |
| `SOAK_MAX_POOL_GROWTH` | `0.05` | Connections/min never returned to the pool |
| `SOAK_MAX_FDS_GROWTH` | `0.5` | Descriptors/min never closed |

The ceilings are objectives, not observations: each is the growth rate at which
something breaks within a working day. They have not been calibrated against a
real hour-long run, because until now nothing had ever executed one — read the
first Sunday's numbers as a measurement and revisit them.

Two failures are worth knowing about before you see them:

* **`soak_leak_signals`** — a series that is both steeper than its ceiling and
  straight enough to believe. This is the finding.
* **`soak_blind_signals`** — a series the API never published, so no line could
  be fitted. It fails the run on purpose. In multiprocess mode `process_*` is
  not exported at all, and a soak that silently fitted a line through an empty
  series would report "no leak" forever.

Or one at a time, which is what you want while tuning:

```bash
k6 run tests/performance/monitoring/summary-load.js
k6 run tests/performance/monitoring/matrix-spike.js
k6 run tests/performance/users/auth-flood.js
```

Shorten the soak while iterating with `-e SOAK_MINUTES=3`; lengthen it to
`60` before a release.

k6 exits `99` when a threshold is breached, so any of these can gate a
pipeline as-is.

## Configuration

| Variable | Default | Meaning |
| --- | --- | --- |
| `PERF_API_URL` | `http://localhost:8000` | API under test |
| `PERF_EMAIL` / `PERF_PASSWORD` | the dev-preview account | Load-test credentials |
| `PERF_WORKSPACE_ID` | first visible workspace | Tenant to scope the load to |
| `SOAK_MINUTES` | `10` | Hold time for the soak profile |
| `TEST_POSTGRES_DB` | `marketplace_test` | Database the pytest probes use |

## Rules for this tier

**Never point these at production or at the dev database.** `auth-flood.js`
deliberately triggers the rate limiter, `matrix-spike.js` deliberately
overloads the pool, and the pytest probes deliberately hold every connection
they can get. `resilience/` defaults to the throwaway `marketplace_test`
database for exactly this reason.

**Thresholds are objectives, not observations.** A threshold copied from
today's measurement passes forever and warns nobody. Every number in
`lib/config.js` is one the team would treat as a regression — change them when
the objective changes, not when a run goes red.

**Assert the failure mode, not just the speed.** The valuable assertions here
are "degrades gracefully", "recovers afterwards", and "does not drift upward
under constant load". Raw percentiles alone would not have caught the incident
that motivated this tier.
