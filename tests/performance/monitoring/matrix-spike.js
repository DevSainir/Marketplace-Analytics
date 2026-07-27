/**
 * k6: spike and overload behaviour on the heaviest read path.
 *
 * The SKU detail endpoint builds the day×bucket matrix in the backend, so it is
 * the most expensive read in the product and the first thing to fall over. What
 * this profile checks is not "how fast" but **how it fails**: under a spike far
 * beyond normal use the API must degrade honestly — refuse or slow down — and
 * then *recover* once the spike passes.
 *
 * The recovery half is the important one. A pool that never recovers turns a
 * ten-second traffic burst into an outage that lasts until someone restarts the
 * container, which is exactly what a leaked connection produces.
 *
 * Run:
 *   k6 run tests/performance/monitoring/matrix-spike.js
 */
import { check, sleep } from 'k6'
import exec from 'k6/execution'
import http from 'k6/http'
import { Rate, Trend } from 'k6/metrics'

import { API_URL, authHeaders } from '../lib/config.js'
import { login } from '../lib/auth.js'

/**
 * When the recovery window opens, in ms from the start of the run.
 *
 * The stages below run 20 s + 10 s + 30 s + 10 s + 40 s; the last one is the
 * recovery stage, starting at 70 s. Sampling begins a few seconds later so the
 * in-flight requests from the overload stage have drained and are not counted
 * as recovery.
 *
 * This MUST be a time window, not a VU-id filter: VUs 1-5 stay active through
 * the spike as well, so gating on `__VU <= 5` measures the overload and calls
 * it recovery.
 */
const RECOVERY_STARTS_MS = 78_000

/** Requests that neither succeeded nor produced a clean 429/503. */
const uglyFailures = new Rate('ugly_failures')
/** Latency measured after the spike has drained. */
const recoveryLatency = new Trend('recovery_latency')

export const options = {
  stages: [
    { duration: '20s', target: 5 }, // baseline
    { duration: '10s', target: 120 }, // spike
    { duration: '30s', target: 120 }, // sustained overload
    { duration: '10s', target: 5 }, // drain
    { duration: '40s', target: 5 }, // recovery window — the real assertion
  ],
  thresholds: {
    // Overload may legitimately produce 429/503. It must NOT produce hangs,
    // connection resets, or 500s: those mean the process is damaged rather
    // than busy.
    ugly_failures: ['rate<0.05'],
    // Once the spike drains, latency must return to normal. If this fails, the
    // service did not recover on its own.
    recovery_latency: ['p(95)<1500'],
    http_req_duration: ['max<30000'],
  },
}

export function setup() {
  const session = login()
  const summary = http.get(
    `${API_URL}/api/v1/monitoring/summary?limit=1`,
    authHeaders(session.token, session.workspaceId),
  )
  const items = summary.json('items') || []
  return { ...session, nmId: items.length ? items[0].nm_id : null }
}

export default function (session) {
  const requestOptions = authHeaders(session.token, session.workspaceId)
  const path = session.nmId
    ? `/api/v1/monitoring/skus/${session.nmId}`
    : '/api/v1/monitoring/summary?limit=100'

  const response = http.get(`${API_URL}${path}`, requestOptions)

  const graceful =
    response.status === 200 || response.status === 429 || response.status === 503 ||
    response.status === 404
  uglyFailures.add(!graceful)
  check(response, { 'degraded gracefully (not a 5xx or a reset)': () => graceful })

  // Only the final recovery stage feeds the recovery threshold.
  if (exec.instance.currentTestRunDuration >= RECOVERY_STARTS_MS && response.status === 200) {
    recoveryLatency.add(response.timings.duration)
  }

  sleep(0.5)
}
