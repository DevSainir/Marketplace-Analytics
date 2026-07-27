/**
 * Shared configuration for the k6 load profiles.
 *
 * Thresholds are written as **service-level objectives, not observations**: a
 * threshold that merely records today's numbers turns green forever and warns
 * nobody. Each one below is a number the team would treat as a regression.
 *
 * k6 fails the run (exit code 99) when a threshold is breached, which is what
 * makes these usable as a CI gate rather than a report nobody reads.
 */

/** Base URL of the API under test. */
export const API_URL = __ENV.PERF_API_URL || 'http://localhost:8000'

/** Credentials of the seeded load-test account. */
export const CREDENTIALS = {
  email: __ENV.PERF_EMAIL || 'dev-preview@example.com',
  password: __ENV.PERF_PASSWORD || 'dev-preview-password',
}

/** Workspace the load is scoped to; resolved at setup when unset. */
export const WORKSPACE_ID = __ENV.PERF_WORKSPACE_ID || ''

/**
 * Objectives for ordinary read traffic.
 *
 * The p95 budget is deliberately below what a human notices (~1 s): this is a
 * dashboard people keep open, and a slow summary is the difference between
 * "the tool" and "the slow tool".
 */
export const READ_THRESHOLDS = {
  http_req_failed: ['rate<0.01'],
  http_req_duration: ['p(95)<800', 'p(99)<2000'],
  // No request may hang: an unbounded tail is what freezes the SPA behind its
  // header, which users report as a broken frontend rather than a slow one.
  'http_req_duration{expected_response:true}': ['max<15000'],
}

/** Objectives for the heavier report endpoints, which fan out over a window. */
export const REPORT_THRESHOLDS = {
  http_req_failed: ['rate<0.02'],
  http_req_duration: ['p(95)<3000', 'max<30000'],
}

/**
 * Build the headers an authenticated, workspace-scoped request needs.
 *
 * @param {string} token access token from `login()`
 * @param {string} workspaceId active workspace id
 */
export function authHeaders(token, workspaceId) {
  return {
    headers: {
      Authorization: `Bearer ${token}`,
      'X-Workspace-Id': workspaceId,
      'Content-Type': 'application/json',
    },
  }
}
