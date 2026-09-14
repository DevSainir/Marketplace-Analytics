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

/**
 * GET /v1/organizations/members — the organisation's roster.
 *
 * Here rather than through `useMembersStore` because that store asks for the
 * roster only when the effective role is exactly `owner`, and a `dev` account
 * collapses to `dev` however it is a member — so the store leaves a developer
 * with an empty list and the team panel invisible. The ENDPOINT allows a dev
 * (verified live on prod: 200, not 403); only the store's gate does not.
 *
 * @returns {Promise<Array<{user_id: string, email: string, role: string,
 *   joined_at: string, access_level: string, modules: string[]}>>}
 */
export async function fetchMembers() {
  const { data } = await apiClient.get('/v1/organizations/members')
  return data
}

/**
 * PATCH /v1/organizations/members/{id}/access — set one manager's grant.
 *
 * The whole grant travels every time, matching the endpoint: a partial update
 * from a stale form would silently keep a module the owner had switched off.
 *
 * @param {string} userId
 * @param {{accessLevel: string, modules: string[]}} grant
 */
export async function updateMemberAccess(userId, { accessLevel, modules }) {
  const { data } = await apiClient.patch(`/v1/organizations/members/${userId}/access`, {
    access_level: accessLevel,
    modules,
  })
  return data
}

/**
 * DELETE /v1/organizations/members/{id} — remove a member from the company.
 *
 * Their ACCOUNT keeps existing; it simply stops belonging here. The owner
 * cannot be removed — 422.
 *
 * @param {string} userId
 */
export async function removeMember(userId) {
  await apiClient.delete(`/v1/organizations/members/${userId}`)
}

/**
 * POST /v1/organizations/invitations — invite a manager with a grant.
 *
 * @param {{email: string|null, validForHours: number, accessLevel: string,
 *   modules: string[]}} payload
 * @returns {Promise<{id: string, email: string|null, token: string, expires_at: string}>}
 */
export async function createInvitation({ email, validForHours, accessLevel, modules }) {
  const { data } = await apiClient.post('/v1/organizations/invitations', {
    email: email || null,
    valid_for_hours: validForHours,
    access: { access_level: accessLevel, modules },
  })
  return data
}
