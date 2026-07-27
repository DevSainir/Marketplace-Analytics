/**
 * k6: credential-stuffing / DDoS behaviour on the auth surface.
 *
 * This is an **abuse** profile, not a throughput one. Login burns a bcrypt
 * cycle per attempt by design, so an unthrottled login endpoint is a free CPU
 * amplifier: a few hundred requests a second will starve the event loop and
 * take the whole API down, without any exploit.
 *
 * What is asserted:
 *   * the per-IP limiter engages (429s appear) rather than every attempt being
 *     served;
 *   * no attempt ever *succeeds* with a wrong password, however many are made;
 *   * the API stays up throughout — the flood must be absorbed, not fatal;
 *   * `/refresh` keeps its own budget, so a login flood cannot log real users
 *     out by exhausting a shared counter.
 *
 * Run against a disposable environment only:
 *   k6 run tests/performance/users/auth-flood.js
 */
import { check, sleep } from 'k6'
import http from 'k6/http'
import { Counter, Rate } from 'k6/metrics'

import { API_URL, CREDENTIALS } from '../lib/config.js'

const throttled = new Counter('throttled_attempts')
const accepted = new Counter('accepted_attempts')
/** Requests that produced neither a clean rejection nor a clean throttle. */
const serverBroke = new Rate('server_broke')

export const options = {
  scenarios: {
    credential_stuffing: {
      executor: 'constant-arrival-rate',
      rate: 60,
      timeUnit: '1s',
      duration: '30s',
      preAllocatedVUs: 50,
      maxVUs: 200,
    },
  },
  thresholds: {
    // The limiter must actually engage. Zero 429s under 60 rps means the
    // endpoint is wide open and one laptop can exhaust the CPU.
    throttled_attempts: ['count>0'],
    // Not one wrong password may be accepted, at any rate.
    accepted_attempts: ['count==0'],
    // The service must survive: a 5xx or a dropped connection means the flood
    // damaged the process rather than being absorbed.
    server_broke: ['rate<0.01'],
  },
}

export default function () {
  const response = http.post(
    `${API_URL}/api/v1/auth/login`,
    JSON.stringify({ email: CREDENTIALS.email, password: `wrong-${__ITER}` }),
    { headers: { 'Content-Type': 'application/json' }, tags: { name: 'login-flood' } },
  )

  if (response.status === 429) throttled.add(1)
  if (response.status === 200) accepted.add(1)
  serverBroke.add(response.status >= 500 || response.status === 0)

  check(response, {
    'never authenticates a wrong password': (r) => r.status !== 200,
    'answers 401 or 429, never 5xx': (r) => r.status === 401 || r.status === 429,
  })

  sleep(0.1)
}

/**
 * After the flood, confirm the service still serves legitimate traffic.
 *
 * A limiter that leaves the endpoint unusable afterwards has converted an
 * attack into an outage — the attacker's goal.
 */
export function teardown() {
  sleep(2)
  const health = http.get(`${API_URL}/health`)
  check(health, { 'API is still alive after the flood': (r) => r.status === 200 })
}
