/**
 * Login helper for the k6 profiles.
 *
 * Called once from each script's `setup()` rather than per virtual user, for
 * two reasons: logging in is bcrypt-bound and would otherwise dominate the
 * measurement, and every login rotates the refresh family — thousands of
 * parallel logins would look exactly like the token-reuse attack the backend
 * is built to detect.
 */
import http from 'k6/http'
import { fail } from 'k6'

import { API_URL, CREDENTIALS, WORKSPACE_ID } from './config.js'

/**
 * Authenticate once and resolve the workspace to run the load against.
 *
 * @returns {{token: string, workspaceId: string}}
 */
export function login() {
  const response = http.post(
    `${API_URL}/api/v1/auth/login`,
    JSON.stringify({ email: CREDENTIALS.email, password: CREDENTIALS.password }),
    { headers: { 'Content-Type': 'application/json' } },
  )

  if (response.status !== 200) {
    fail(
      `setup: login failed with ${response.status}. Seed the load-test account ` +
        `or set PERF_EMAIL / PERF_PASSWORD. Body: ${response.body}`,
    )
  }

  const token = response.json('access_token')
  return { token, workspaceId: WORKSPACE_ID || resolveWorkspace(token) }
}

/**
 * Pick the first workspace visible to the account.
 *
 * @param {string} token access token
 * @returns {string} workspace id
 */
function resolveWorkspace(token) {
  const response = http.get(`${API_URL}/api/v1/workspaces`, {
    headers: { Authorization: `Bearer ${token}` },
  })
  if (response.status !== 200) {
    fail(`setup: could not list workspaces (${response.status}).`)
  }
  const items = response.json('items')
  if (!items || items.length === 0) {
    fail('setup: the account has no workspaces to load-test against.')
  }
  return items[0].id
}
