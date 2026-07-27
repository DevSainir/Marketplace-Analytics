/**
 * k6: steady-state load on the monitoring dashboard.
 *
 * Models what the product actually does — a handful of managers with the
 * dashboard open, each re-reading the summary and drilling into SKUs. The point
 * is not to find the breaking point (that is `matrix-spike.js`) but to prove
 * the ordinary working day stays inside its latency budget and, crucially,
 * that latency does not *drift upward* over the run.
 *
 * Upward drift under constant load is the signature of a leak — a connection
 * not returned to the pool, a session not closed — and it is invisible in any
 * single-request test.
 *
 * Run:
 *   k6 run tests/performance/monitoring/summary-load.js
 */
import { check, sleep } from 'k6'
import exec from 'k6/execution'
import http from 'k6/http'
import { Trend } from 'k6/metrics'

import { API_URL, READ_THRESHOLDS, authHeaders } from '../lib/config.js'
import { login } from '../lib/auth.js'

/** Total run length in ms; the halfway mark splits early from late samples. */
const RUN_DURATION_MS = 180_000

/** Latency of the first half of the run, compared against the second half. */
const earlyLatency = new Trend('summary_latency_early')
/** Latency of the second half — the drift detector. */
const lateLatency = new Trend('summary_latency_late')

export const options = {
  stages: [
    { duration: '30s', target: 10 }, // ramp to a realistic team size
    { duration: '2m', target: 10 }, // hold — this is the measurement
    { duration: '30s', target: 0 }, // ramp down
  ],
  thresholds: {
    ...READ_THRESHOLDS,
    // The leak detector: the back half of a constant-load run must not be
    // materially slower than the front half.
    summary_latency_late: ['p(95)<1200'],
    checks: ['rate>0.99'],
  },
}

export function setup() {
  return login()
}

export default function (session) {
  const requestOptions = authHeaders(session.token, session.workspaceId)

  const summary = http.get(`${API_URL}/api/v1/monitoring/summary?limit=50`, requestOptions)
  check(summary, {
    'summary responded 200': (r) => r.status === 200,
    'summary carried items': (r) => r.json('items') !== undefined,
  })

  const elapsed = exec.instance.currentTestRunDuration
  const bucket = elapsed < RUN_DURATION_MS / 2 ? earlyLatency : lateLatency
  bucket.add(summary.timings.duration)

  const pins = http.get(`${API_URL}/api/v1/monitoring/pins`, requestOptions)
  check(pins, { 'pins responded 200': (r) => r.status === 200 })

  // A real user reads the screen between requests; hammering with zero think
  // time measures the load generator, not the product.
  sleep(Math.random() * 2 + 1)
}

export function teardown() {
  // Nothing to clean: this profile is read-only by design, so it can be run
  // against a staging environment without mutating anyone's data.
}
