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
