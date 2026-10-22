/**
 * HTTP calls of the monitoring sandbox (/labs/monitoring): the live /monitoring
 * endpoints, read-only. Workspace header and cookies come from the shared client.
 */
import apiClient from '@/core/api/axios'

/** The workspace's SKUs with figures in the window: `{date_from, date_to, limit}`. */
export async function fetchSkuSummary(params, signal) {
  const { data } = await apiClient.get('/v1/monitoring/summary', { params, signal })
  return data
}

/** The workspace's pinned SKUs, in their order. */
export async function fetchPinnedSkus(signal) {
  const { data } = await apiClient.get('/v1/monitoring/pins', { signal })
  return data
}

/** One SKU's `SkuDetailResponse` for the window. */
export async function fetchSkuDetail(nmId, params, signal) {
  const { data } = await apiClient.get(`/v1/monitoring/skus/${nmId}`, { params, signal })
  return data
}

/** One SKU's per-day stock by warehouse and size for the window. */
export async function fetchStockRange(nmId, params, signal) {
  const { data } = await apiClient.get(`/v1/monitoring/skus/${nmId}/stock`, { params, signal })
  return data
}
