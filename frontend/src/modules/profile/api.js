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
 * POST /v1/organizations/invitations — invite a manager with a grant.
 *
 * The access travels WITH the invitation rather than being applied after they
 * join, so a new manager never briefly holds more than the owner intended.
 *
 * @param {{email: string|null, validForDays: number, accessLevel: string, modules: string[]}} payload
 * @returns {Promise<{id: string, email: string|null, token: string, expires_at: string}>}
 */
export async function createInvitation({ email, validForDays, accessLevel, modules }) {
  const { data } = await apiClient.post('/v1/organizations/invitations', {
    email: email || null,
    valid_for_days: validForDays,
    access: { access_level: accessLevel, modules },
  })
  return data
}
