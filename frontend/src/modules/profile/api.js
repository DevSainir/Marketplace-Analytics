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
