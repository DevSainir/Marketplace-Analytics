/**
 * Heatmap API layer — the grid, the catalogue behind its filters, «Группы» and norms.
 *
 * Errors propagate to the caller (the store decides what the page says).
 */
import apiClient, { WINDOW_TIMEOUT_MS } from '@/core/api/axios'

/**
 * Lists travel as repeated keys (`subjects=a&subjects=b`), which is what
 * FastAPI reads; Axios's default `subjects[]=` would arrive as nothing.
 */
const REPEATED_KEYS = { indexes: null }

/**
 * GET /v1/heatmap — the whole grid for one window.
 *
 * @param {object} params `date_from`, `date_to`, `metric`, `metric2`, `period`,
 *   `group_by`, and the filter lists `subjects`, `group_ids`, `nm_ids`.
 * @param {AbortSignal} [signal] Cancels the request when a newer one starts.
 */
export async function fetchHeatmap(params, signal) {
  const { data } = await apiClient.get('/v1/heatmap', {
    params,
    paramsSerializer: REPEATED_KEYS,
    signal,
    timeout: WINDOW_TIMEOUT_MS,
  })
  return data
}

/**
 * GET /v1/heatmap/catalog — every card of the workspace and its subjects,
 * most-ordered in the window first.
 *
 * @param {{date_from: string, date_to: string}} params
 */
export async function fetchCatalog(params) {
  const { data } = await apiClient.get('/v1/heatmap/catalog', { params })
  return data
}

/** GET /v1/heatmap/groups — the workspace's groups. */
export async function fetchGroups() {
  const { data } = await apiClient.get('/v1/heatmap/groups')
  return data
}

/** POST /v1/heatmap/groups — `{name, nm_ids}` → the created group. */
export async function createGroup(payload) {
  const { data } = await apiClient.post('/v1/heatmap/groups', payload)
  return data
}

/** PUT /v1/heatmap/groups/:id — replace a group's name and members. */
export async function updateGroup(id, payload) {
  const { data } = await apiClient.put(`/v1/heatmap/groups/${id}`, payload)
  return data
}

/** DELETE /v1/heatmap/groups/:id */
export async function deleteGroup(id) {
  await apiClient.delete(`/v1/heatmap/groups/${id}`)
}

/** GET /v1/heatmap/norms — every hand-set norm of the workspace. */
export async function fetchNorms() {
  const { data } = await apiClient.get('/v1/heatmap/norms')
  return data
}

/** PUT /v1/heatmap/norms/:nmId/:metric — set an article's norm, per day. */
export async function saveNorm(nmId, metric, value) {
  const { data } = await apiClient.put(`/v1/heatmap/norms/${nmId}/${metric}`, { value })
  return data
}

/** DELETE /v1/heatmap/norms/:nmId/:metric */
export async function deleteNorm(nmId, metric) {
  await apiClient.delete(`/v1/heatmap/norms/${nmId}/${metric}`)
}
