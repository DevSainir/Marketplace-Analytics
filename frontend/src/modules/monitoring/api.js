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
 * GET /v1/monitoring/skus/{nm_id}/stock — one exact snapshot day's
 * size × warehouse stock breakdown (a side of the two-day comparison).
 *
 * @param {number} nmId WB SKU identifier.
 * @param {string} onDate ISO date of the snapshot day.
 * @param {AbortSignal} [signal]
 * @returns {Promise<{stat_date: string, stock: object}>}
 */
export async function fetchStockDay(nmId, onDate, signal) {
  const { data } = await apiClient.get(`/v1/monitoring/skus/${nmId}/stock`, {
    params: { on_date: onDate },
    signal,
  })
  return data
}

/**
 * PUT /v1/monitoring/skus/{nm_id}/warehouse-marks — mark («Отгрузить») or
 * unmark («Разгрузить») one warehouse for THIS SKU only.
 *
 * @param {number} nmId WB SKU identifier.
 * @param {string} warehouseName WB warehouse name from the stock breakdown.
 * @param {boolean} marked True to mark, false to unmark.
 * @returns {Promise<{marked_warehouses: string[]}>} The SKU's marks after the update.
 */
export async function setWarehouseMark(nmId, warehouseName, marked) {
  const { data } = await apiClient.put(`/v1/monitoring/skus/${nmId}/warehouse-marks`, {
    warehouse_name: warehouseName,
    marked,
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
 * PUT /v1/monitoring/skus/{nm_id}/comments/{date} — save or clear one day's
 * free-text note on a SKU (shared by every account). A blank body clears it.
 *
 * @param {number} nmId WB SKU identifier.
 * @param {string} iso The commented day, as YYYY-MM-DD.
 * @param {string} body The note text; blank/whitespace-only clears the comment.
 * @returns {Promise<{nm_id: number, comment_date: string, body: string|null}>} The stored note.
 */
export async function setDayComment(nmId, iso, body) {
  const { data } = await apiClient.put(`/v1/monitoring/skus/${nmId}/comments/${iso}`, { body })
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
 * GET /v1/monitoring/refresh/{task_id} — poll a refresh task's state.
 *
 * @param {string} taskId Celery task id from {@link refreshSku}.
 * @returns {Promise<{task_id: string, status: string, ready: boolean, successful: boolean}>}
 */
export async function getRefreshStatus(taskId) {
  const { data } = await apiClient.get(`/v1/monitoring/refresh/${taskId}`)
  return data
}
