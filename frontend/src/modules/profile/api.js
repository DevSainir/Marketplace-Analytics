/**
 * Profile module API layer — thin async wrappers over the account and
 * workspace endpoints. Token *values* only ever travel to the server; the
 * backend answers with per-surface booleans, never stored tokens.
 */
import apiClient from '@/core/api/axios'

/**
 * GET /v1/auth/me — the authenticated account (email + role for UI gating).
 *
 * @returns {Promise<{id: string, email: string, is_active: boolean, role: string, created_at: string}>}
 */
export async function fetchMe() {
  const { data } = await apiClient.get('/v1/auth/me')
  return data
}

/**
 * GET /v1/workspaces — every workspace the caller can switch into.
 *
 * @returns {Promise<Array<{id: string, name: string, created_at: string}>>}
 */
export async function fetchWorkspaces() {
  const { data } = await apiClient.get('/v1/workspaces')
  return data.items
}

/**
 * POST /v1/workspaces — create a workspace (dev role required).
 *
 * @param {string} name
 * @returns {Promise<{id: string, name: string, created_at: string}>}
 */
export async function createWorkspace(name) {
  const { data } = await apiClient.post('/v1/workspaces', { name })
  return data
}

/**
 * DELETE /v1/workspaces/{id} — delete a workspace and its stored WB tokens
 * (dev role required).
 *
 * @param {string} workspaceId
 */
export async function deleteWorkspace(workspaceId) {
  await apiClient.delete(`/v1/workspaces/${workspaceId}`)
}

/**
 * GET /v1/workspaces/{id}/tokens — which token kinds are configured
 * (dev role required; slugs only, never values).
 *
 * @param {string} workspaceId
 * @returns {Promise<{workspace_id: string, is_primary: boolean, configured: string[]}>}
 */
export async function fetchTokenStatus(workspaceId) {
  const { data } = await apiClient.get(`/v1/workspaces/${workspaceId}/tokens`)
  return data
}

/**
 * PUT /v1/workspaces/{id}/tokens — set/rotate WB tokens (dev role required).
 * `tokens` maps a kind slug to its value: a non-empty string sets it, an empty
 * string deletes it, and an absent kind is left untouched.
 *
 * @param {string} workspaceId
 * @param {Record<string, string>} tokens
 * @returns {Promise<{workspace_id: string, is_primary: boolean, configured: string[]}>}
 */
export async function updateTokens(workspaceId, tokens) {
  const { data } = await apiClient.put(`/v1/workspaces/${workspaceId}/tokens`, { tokens })
  return data
}

/**
 * GET /v1/organizations/me — the caller's effective role and tenant.
 *
 * Separate from `fetchMe`: that one answers "who is this account" (the
 * PLATFORM role, dev or user), this one answers "what are they inside their
 * company" (owner or manager). The manager-access panel is gated on the
 * second, and reading it off the first would show the panel to nobody.
 *
 * @returns {Promise<{role: string, can_write: boolean, organization: object|null}>}
 */
export async function fetchOrganizationMe() {
  const { data } = await apiClient.get('/v1/organizations/me')
  return data
}

/**
 * GET /v1/organizations/members — the organisation's members (owner only).
 *
 * @returns {Promise<Array<{user_id: string, email: string, role: string,
 *   joined_at: string, access_level: string, modules: string[]}>>}
 */
/**
 * POST /v1/organizations/activate — redeem an activation code.
 *
 * Creates the organisation and makes the caller its owner. 403 for a code that
 * is unknown, spent or expired; 409 when this account already has an
 * organisation.
 *
 * @param {string} code
 * @returns {Promise<{id: string, name: string}>}
 */
export async function activateOrganization(code) {
  const { data } = await apiClient.post('/v1/organizations/activate', { code })
  return data
}

export async function fetchMembers() {
  const { data } = await apiClient.get('/v1/organizations/members')
  return data
}

/**
 * PATCH /v1/organizations/members/{id}/access — set one manager's grant.
 *
 * The whole grant is sent every time, matching the endpoint: the form shows
 * the current state, and a partial update from a stale form would silently
 * keep a module the owner had just switched off.
 *
 * @param {string} userId
 * @param {{accessLevel: string, modules: string[]}} grant
 * @returns {Promise<object>} The member as it now stands.
 */
export async function updateMemberAccess(userId, { accessLevel, modules }) {
  const { data } = await apiClient.patch(`/v1/organizations/members/${userId}/access`, {
    access_level: accessLevel,
    modules,
  })
  return data
}

/**
 * GET /v1/organizations/invitations/mine — invitations waiting for this account.
 *
 * Matched on the signed-in address, and carrying the inviting company's name
 * and nothing else: someone who has not accepted is not a member yet, so a
 * preview must not show them a roster.
 *
 * @returns {Promise<Array<{id: string, organization_name: string|null, expires_at: string}>>}
 */
export async function fetchMyInvitations() {
  const { data } = await apiClient.get('/v1/organizations/invitations/mine')
  return data
}

/**
 * POST /v1/organizations/invitations/accept — join the inviting company.
 *
 * Answers the same shape as `/organizations/me`, so the caller can swap
 * straight into the app without a second round trip.
 *
 * @param {string} token
 */
export async function acceptInvitation(token) {
  const { data } = await apiClient.post('/v1/organizations/invitations/accept', { token })
  return data
}

/**
 * DELETE /v1/organizations/members/:userId — remove a manager.
 *
 * This, not revoking their invitation, is what withdraws access once somebody
 * has joined. Their ACCOUNT keeps existing; it simply stops belonging to the
 * organisation. The owner cannot be removed — 422.
 *
 * @param {string} userId
 */
export async function removeMember(userId) {
  await apiClient.delete(`/v1/organizations/members/${userId}`)
}

/**
 * POST /v1/organizations/invitations — invite a manager with a grant.
 *
 * The access travels WITH the invitation rather than being applied after they
 * join, so a new manager never briefly holds more than the owner intended.
 *
 * @param {{email: string|null, validForHours: number, accessLevel: string, modules: string[]}} payload
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
 * GET /v1/workspaces/{id}/backfill — how far this workspace's history walk got.
 *
 * Four lanes on four different clocks: the catalogue is one request, the funnel
 * and advertising aggregates are a couple of hours each, and P&L is one WB
 * request per fifteen minutes — sixteen hours for a large seller. That is why
 * the endpoint reports lanes rather than a single percentage.
 *
 * @param {string} workspaceId Workspace whose backfill to report on.
 * @returns {Promise<{active: boolean, lanes: Array<{lane: string, label: string,
 *   state: string, done_units: number, total_units: number, percent: number,
 *   message: string, updated_at: string|null}>}>}
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
