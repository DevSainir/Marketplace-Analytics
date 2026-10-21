/**
 * Monitoring module API layer — thin async wrappers over the backend's
 * `/api/v1/monitoring/*` endpoints (see backend `monitoring/routers`).
 *
 * All functions return the parsed response body; errors propagate to the
 * caller (the Pinia store) where they are mapped onto UI state.
 */
import apiClient from '@/core/api/axios'

/**
 * GET /v1/monitoring/summary — compact per-SKU rollup listing for the window
 * (feeds the search dropdown and dashboards).
 *
 * @param {{date_from?: string, date_to?: string, limit?: number, offset?: number}} [params]
 * @param {AbortSignal} [signal] Cancels the request when a newer fetch starts.
 * @returns {Promise<import('@/core/api/types').SkuSummaryListResponse>}
 */
export async function fetchSkuSummary(params = {}, signal) {
  const { data } = await apiClient.get('/v1/monitoring/summary', { params, signal })
  return data
}

/**
 * GET /v1/monitoring/skus/lookup — resolve a vendor code (or fragment) to
 * matching SKUs.
 *
 * @param {string} vendorCode Seller article code, e.g. "M-TRX01-BLK" or "M-TRX".
 * @param {AbortSignal} [signal] Cancels the request when a newer search starts.
 * @returns {Promise<import('@/core/api/types').SkuLookupResponse>}
 */
export async function lookupSkus(vendorCode, signal) {
  const { data } = await apiClient.get('/v1/monitoring/skus/lookup', {
    params: { vendor_code: vendorCode },
    signal,
  })
  return data
}

/**
 * GET /v1/monitoring/skus/{nm_id} — full detail: funnel, per-campaign
 * advertising (with derived CPM/CTR/CPC) and the size × warehouse stock grid.
 *
 * @param {number|string} nmId WB SKU identifier.
 * @param {{date_from?: string, date_to?: string, campaign_id?: number, campaign_status?: string}} [params]
 * @param {AbortSignal} [signal] Cancels the request when a newer search starts.
 * @returns {Promise<import('@/core/api/types').SkuDetailResponse>}
 */
export async function fetchSkuDetail(nmId, params = {}, signal) {
  const { data } = await apiClient.get(`/v1/monitoring/skus/${nmId}`, { params, signal })
  return data
}

/**
 * POST /v1/monitoring/skus/{nm_id}/matrix/preview — apply one pending cell edit
 * to the working copy and get the recomputed matrix back (nothing persisted).
 *
 * @param {number} nmId WB SKU identifier.
 * @param {object} base The current editable working copy (`matrix_base`).
 * @param {{day: string, bucket: string, metric: string, value: number}} edit
 * @param {AbortSignal} [signal]
 * @returns {Promise<{base: object, matrix: object}>}
 */
export async function previewMatrixEdit(nmId, base, edit, signal) {
  const { data } = await apiClient.post(
    `/v1/monitoring/skus/${nmId}/matrix/preview`,
    { base, edit },
    { signal },
  )
  return data
}

/**
 * PUT /v1/monitoring/skus/{nm_id}/matrix — persist the working copy as manual
 * overrides; returns the refreshed SkuDetailResponse.
 *
 * @param {number} nmId WB SKU identifier.
 * @param {object} base The working copy to persist.
 * @param {{date_from?: string, date_to?: string}} [params] The saved window.
 * @returns {Promise<import('@/core/api/types').SkuDetailResponse>}
 */
export async function saveMatrix(nmId, base, params = {}) {
  const { data } = await apiClient.put(`/v1/monitoring/skus/${nmId}/matrix`, { base }, { params })
  return data
}

/**
 * GET /v1/monitoring/skus/{nm_id}/stock — one size × warehouse breakdown per
 * day of the window, which is what the «Остатки по складам» ribbon scrolls
 * through. Unobserved days come back as empty breakdowns, never as gaps.
 *
 * @param {number} nmId WB SKU identifier.
 * @param {{date_from?: string, date_to?: string}} [params] The analysis window;
 *   the backend applies its own defaults and ceiling when either is missing.
 * @param {AbortSignal} [signal]
 * @returns {Promise<{days: Array<{stat_date: string, stock: object}>}>}
 */
export async function fetchStockRange(nmId, params = {}, signal) {
  const { data } = await apiClient.get(`/v1/monitoring/skus/${nmId}/stock`, {
    params,
    signal,
  })
  return data
}

/**
 * @typedef {object} PinnedSku
 * @property {number} nm_id
 * @property {string|null} vendor_code
 * @property {string|null} title
 * @property {string|null} color Chip tint as #rrggbb, or null when unpainted.
 */

/**
 * GET /v1/monitoring/pins — the global pinned-SKU list (shared by everyone),
 * in chip-row order.
 *
 * @param {AbortSignal} [signal]
 * @returns {Promise<{items: PinnedSku[]}>}
 */
export async function fetchPinnedSkus(signal) {
  const { data } = await apiClient.get('/v1/monitoring/pins', { signal })
  return data
}

/**
 * PUT /v1/monitoring/skus/{nm_id}/pin — pin («Закрепить») or unpin a SKU for
 * every account; returns the full updated pinned list.
 *
 * @param {number} nmId WB SKU identifier.
 * @param {boolean} pinned True to pin, false to unpin.
 * @returns {Promise<{items: PinnedSku[]}>}
 */
export async function setSkuPin(nmId, pinned) {
  const { data } = await apiClient.put(`/v1/monitoring/skus/${nmId}/pin`, { pinned })
  return data
}

/**
 * PUT /v1/monitoring/pins/order — persist the chip row's order after a
 * drag-and-drop, for every account.
 *
 * The full pinned list must be sent: the backend rejects an order that no
 * longer matches the pinned set (a teammate pinned or unpinned meanwhile).
 *
 * @param {number[]} nmIds Every pinned nm_id, in the new left-to-right order.
 * @returns {Promise<{items: PinnedSku[]}>}
 */
export async function reorderPinnedSkus(nmIds) {
  const { data } = await apiClient.put('/v1/monitoring/pins/order', { nm_ids: nmIds })
  return data
}

/**
 * PUT /v1/monitoring/skus/{nm_id}/pin-color — paint a pinned chip, or clear
 * its tint, for every account.
 *
 * @param {number} nmId WB SKU identifier.
 * @param {string|null} color Tint as #rrggbb, or null to clear it.
 * @returns {Promise<{items: PinnedSku[]}>}
 */
export async function setSkuPinColor(nmId, color) {
  const { data } = await apiClient.put(`/v1/monitoring/skus/${nmId}/pin-color`, { color })
  return data
}

/**
 * @typedef {object} DayNote
 * @property {string} body The free-text comment ('' when absent).
 * @property {string} header The note's title ('' when absent).
 */

/**
 * PUT /v1/monitoring/skus/{nm_id}/comments/{date} — save one day's note on a
 * SKU (shared by every account): its comment, its header, or both.
 *
 * Only the edited field is sent; an omitted field keeps its stored value, so
 * the header and the comment never clobber each other. Blanking both clears
 * the day.
 *
 * @param {number} nmId WB SKU identifier.
 * @param {string} iso The day, as YYYY-MM-DD.
 * @param {{body?: string, header?: string}} patch The field(s) just edited.
 * @returns {Promise<{nm_id: number, comment_date: string, note: DayNote|null}>} The stored note.
 */
export async function setDayComment(nmId, iso, patch) {
  const { data } = await apiClient.put(`/v1/monitoring/skus/${nmId}/comments/${iso}`, patch)
  return data
}

/**
 * @typedef {'uni'|'manual_search'|'manual_shelves'|'cpc'} RkType
 * @typedef {object} DayAction
 * @property {RkType|null} first_rk_type «Первая РК» campaign type (null = unset).
 * @property {number|null} first_rk_budget First campaign «Бюджет рекламы», in the workspace's currency.
 * @property {RkType|null} second_rk_type «Вторая РК» campaign type.
 * @property {number|null} second_rk_budget Second campaign «Бюджет рекламы», same currency.
 * @property {'up'|'down'|null} price_change «Меняли цену?».
 * @property {number|null} price_change_amount «На сколько», same currency.
 */

/**
 * PUT /v1/monitoring/skus/{nm_id}/actions/{date} — save one day's «Действия»
 * row on a SKU (shared by every account). The WHOLE day state is sent (last
 * write wins); all-null clears the day's row.
 *
 * @param {number} nmId WB SKU identifier.
 * @param {string} iso The day, as YYYY-MM-DD.
 * @param {DayAction} action The full desired state of the day's answers.
 * @returns {Promise<{nm_id: number, action_date: string, action: DayAction|null}>}
 */
export async function setDayAction(nmId, iso, action) {
  const { data } = await apiClient.put(`/v1/monitoring/skus/${nmId}/actions/${iso}`, action)
  return data
}

/**
 * POST /v1/monitoring/skus/{nm_id}/refresh — enqueue a fresh WB harvest for one
 * SKU (discards its manual edits). Returns the Celery task id to poll.
 *
 * @param {number} nmId WB SKU identifier.
 * @returns {Promise<{task_id: string}>}
 */
export async function refreshSku(nmId) {
  const { data } = await apiClient.post(`/v1/monitoring/skus/${nmId}/refresh`)
  return data
}

/**
 * POST /v1/monitoring/skus/refresh-all — enqueue a fresh WB harvest for EVERY
 * SKU in the workspace. Returns the Celery task id to poll with
 * {@link getRefreshStatus}, exactly like the single-SKU refresh.
 *
 * @returns {Promise<{task_id: string}>}
 */
export async function refreshAllSkus() {
  const { data } = await apiClient.post('/v1/monitoring/skus/refresh-all')
  return data
}

/**
 * GET /v1/monitoring/refresh/{task_id} — poll a refresh task's state.
 *
 * @param {string} taskId Celery task id from {@link refreshSku}.
 * @returns {Promise<{task_id: string, status: string, ready: boolean, successful: boolean}>}
 */
export async function getRefreshStatus(taskId) {
  const { data } = await apiClient.get(`/v1/monitoring/refresh/${taskId}`)
  return data
}

/**
 * GET /v1/monitoring/skus/{nm_id}/clusters — the search clusters this SKU's
 * advertising served in over the window («Поиск по кластерам», stored half).
 *
 * Harvested history, so it answers instantly and covers only phrases the seller
 * PAID to appear for.
 *
 * Called only for workspaces with `search_clusters_enabled` set; see
 * `MonitoringView.vue`.
 *
 * @param {number|string} nmId WB SKU identifier.
 * @param {{date_from?: string, date_to?: string, limit?: number}} [params]
 * @param {AbortSignal} [signal] Cancels the request when the SKU/window changes.
 * @returns {Promise<import('@/core/api/types').SkuClustersResponse>}
 */
export async function fetchSkuClusters(nmId, params = {}, signal) {
  const { data } = await apiClient.get(`/v1/monitoring/skus/${nmId}/clusters`, { params, signal })
  return data
}
