/**
 * The two endpoints the profile sandbox needs and no module Public API exposes.
 *
 * Everything else on this page goes through `@/modules/profile` and
 * `@/modules/auth` — the same stores the real page uses, so the sandbox reads
 * and writes real data rather than fixtures. These two have no store action
 * behind them yet:
 *
 *  - the backfill status, which lives in the profile module's private api.js
 *    (its only caller is a private component);
 *  - `logout-all`, which the backend has shipped since the incident-response
 *    work and the SPA has never called from anywhere.
 *
 * They are here rather than added to those modules on purpose: a sandbox must
 * stay droppable without editing production code.
 */
import apiClient from '@/core/api/axios'

/**
 * GET /v1/workspaces/{id}/backfill — how far this workspace's history walk got.
 *
 * @param {string} workspaceId
 * @returns {Promise<{active: boolean, lanes: Array<object>}>}
 */
export async function fetchBackfillStatus(workspaceId) {
  const { data } = await apiClient.get(`/v1/workspaces/${workspaceId}/backfill`)
  return data
}

/**
 * POST /v1/auth/logout-all — end every session of the calling account.
 *
 * The caller's own session dies too, cookie included: whoever presses this has
 * decided the account is not to be trusted right now.
 *
 * @returns {Promise<{revoked: number}>}
 */
export async function revokeAllSessions() {
  const { data } = await apiClient.post('/v1/auth/logout-all')
  return data
}
