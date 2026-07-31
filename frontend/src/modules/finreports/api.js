/**
 * FinReports module API layer — thin async wrappers over the backend's
 * `/api/v1/finreports/*` endpoints (see backend `finreports/routers`).
 *
 */
import apiClient from '@/core/api/axios'

/**
 * GET /v1/finreports/pnl — the settlement-basis profit-and-loss statement.
 *
 * @param {{date_from?: string, date_to?: string, grouping?: 'week'|'month'|'sku'}} [params]
 * @param {AbortSignal} [signal] Cancels the request when a newer fetch starts.
 * @returns {Promise<object>} `{ total, buckets, notes, ... }`
 */
export async function fetchPnl(params = {}, signal) {
  const { data } = await apiClient.get('/v1/finreports/pnl', { params, signal })
  return data
}

/**
 * GET /v1/finreports/pnl/skus — the per-SKU P&L cut («По артикулам») for an
 * arbitrary settlement-date window.
 *
 * @param {{date_from?: string, date_to?: string}} [params]
 * @param {AbortSignal} [signal] Cancels the request when a newer fetch starts.
 * @returns {Promise<object>} `{ rows, unallocated, totals, notes, ... }`
 */
export async function fetchSkuPnl(params = {}, signal) {
  const { data } = await apiClient.get('/v1/finreports/pnl/skus', { params, signal })
  return data
}

/**
 * PUT /v1/finreports/pnl/skus/{nmId}/exclusion — mark a SKU «Не включать в
 * общий счёт» (or clear it). The mark is stored per workspace and shared.
 *
 * @param {number} nmId WB SKU identifier.
 * @param {boolean} excluded `true` to exclude the SKU, `false` to include it.
 * @returns {Promise<void>}
 */
export async function setSkuExclusion(nmId, excluded) {
  await apiClient.put(`/v1/finreports/pnl/skus/${nmId}/exclusion`, { excluded })
}

/**
 * GET /v1/finreports/cost-prices — costs on file plus the SKUs still missing one.
 *
 * @param {AbortSignal} [signal]
 * @returns {Promise<{currency: string, items: Array<object>, missing: Array<object>}>}
 */
export async function fetchCostPrices(signal) {
  const { data } = await apiClient.get('/v1/finreports/cost-prices', { signal })
  return data
}

/**
 * PUT /v1/finreports/cost-prices — save the whole edited grid in one request.
 *
 * @param {Array<{nm_id: number, cost: number, currency?: string, vendor_code?: string, note?: string}>} items
 * @returns {Promise<{saved: number}>}
 */
export async function saveCostPrices(items) {
  const { data } = await apiClient.put('/v1/finreports/cost-prices', { items })
  return data
}

/**
 * DELETE /v1/finreports/cost-prices/{nmId} — clear one SKU's cost.
 *
 * @param {number} nmId
 * @returns {Promise<void>}
 */
export async function deleteCostPrice(nmId) {
  await apiClient.delete(`/v1/finreports/cost-prices/${nmId}`)
}

/**
 * GET /v1/finreports/weeks — the WB weekly report periods (newest first) that
 *
 * @param {AbortSignal} [signal]
 * @returns {Promise<{weeks: Array<{report_id: number, date_from: string, date_to: string}>}>}
 */
export async function fetchWeeks(signal) {
  const { data } = await apiClient.get('/v1/finreports/weeks', { signal })
  return data
}

/**
 *
 * Returns the archive as a Blob plus the server-suggested file name.
 *
 * @param {{date_from?: string, date_to?: string}} [params]
 * @returns {Promise<{blob: Blob, filename: string}>}
 */
    params,
    responseType: 'blob',
    // Building the full-history package renders ~90k ledger rows and bundles
    // the proof archive (tens of MB); it legitimately outruns the client's
    // default timeout, so this request gets its own generous budget.
    timeout: 600000,
  })
  const disposition = response.headers['content-disposition'] || ''
  const match = disposition.match(/filename="?([^"]+)"?/)
}

/**
 *
 * @param {{date_from?: string, date_to?: string}} [params]
 * @param {AbortSignal} [signal] Cancels the request when a newer fetch starts.
 * @returns {Promise<object>}
 */
  return data
}

/**
 * for one SKU (WB charge vs fair charge, baseline vs implied volume).
 *
 * @param {number} nmId WB SKU identifier.
 * @param {{date_from?: string, date_to?: string}} [params]
 * @param {AbortSignal} [signal] Cancels the request when a newer fetch starts.
 * @returns {Promise<object>}
 */
  return data
}
