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

/**
 * GET /v1/auth/sessions — this account's live logins.
 *
 * A session is a refresh-token family: one login, rotated every fifteen
 * minutes for as long as the browser lives. `is_current` is decided by the
 * server from the access token's own lineage claim, so the list cannot be
 * wrong about which row is the browser reading it.
 *
 * @returns {Promise<Array<{family_id: string, user_agent: string|null,
 *   ip_address: string|null, started_at: string, last_seen_at: string,
 *   is_current: boolean}>>}
 */
export async function fetchSessions() {
  const { data } = await apiClient.get('/v1/auth/sessions')
  return data
}

/**
 * DELETE /v1/auth/sessions/{familyId} — end one login.
 *
 * @param {string} familyId
 */
export async function endSession(familyId) {
  await apiClient.delete(`/v1/auth/sessions/${familyId}`)
}

/**
 * POST /v1/auth/password — change the password from inside a session.
 *
 * No mailed code: the current password is what proves the caller here. Every
 * OTHER session ends; this one survives.
 *
 * @param {{currentPassword: string, newPassword: string}} payload
 * @returns {Promise<{other_sessions_ended: number}>}
 */
export async function changePassword({ currentPassword, newPassword }) {
  const { data } = await apiClient.post('/v1/auth/password', {
    current_password: currentPassword,
    new_password: newPassword,
  })
  return data
}

/**
 * GET /v1/organizations/invitations — every invitation this company issued.
 *
 * Never the token: that is shown once, at creation, and the server keeps only
 * its hash. `status` is resolved server-side against its own clock, so two
 * people looking at the same link read the same state.
 *
 * @returns {Promise<Array<{id: string, email: string|null, status: string,
 *   accepted_count: number, expires_at: string, created_at: string}>>}
 */
export async function fetchInvitations() {
  const { data } = await apiClient.get('/v1/organizations/invitations')
  return data
}

/**
 * DELETE /v1/organizations/invitations/{id} — stop a link working.
 *
 * @param {string} invitationId
 */
export async function revokeInvitation(invitationId) {
  await apiClient.delete(`/v1/organizations/invitations/${invitationId}`)
}

/**
 * GET /v1/organizations/audit-log — who did what inside this company.
 *
 * Owner-scoped and tenant-scoped server-side. The actor's address is stored
 * denormalised on the row, so an entry still names a person after their
 * account is gone.
 *
 * @param {number} limit 1–200, newest first.
 * @returns {Promise<Array<{id: string, occurred_at: string, event: string,
 *   actor_email: string|null, target_type: string|null, target_id: string|null}>>}
 */
export async function fetchAuditLog(limit = 25) {
  const { data } = await apiClient.get('/v1/organizations/audit-log', { params: { limit } })
  return data
}
