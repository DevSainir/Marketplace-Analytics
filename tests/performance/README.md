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
* **Everything else is run deliberately, by hand.** The k6 profiles aim real
  load at a real API — 120 concurrent VUs in the spike, 60 requests a second in
  the flood — so they must never point at anything shared, which rules out both
  a hosted runner beside other jobs and the VPS that serves production. The
  Playwright half needs a running SPA. Neither is in any workflow.

## Layout

| Path | Runner | What it probes |
| --- | --- | --- |
| `resilience/` | pytest | Pool exhaustion, frozen transactions, connection leaks, write races |
| `users/auth-flood.js` | k6 | Credential-stuffing / DDoS on the auth surface |
| `monitoring/summary-load.js` | k6 | Steady-state dashboard load + latency drift (leak detection) |
| `monitoring/matrix-spike.js` | k6 | Spike, overload, and — the real assertion — recovery |
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
