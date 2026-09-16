/**
 * Summary module API layer — one endpoint, `/api/v1/summary`.
 *
 * The backend composes the whole page in one response (cards, daily series,
 * category ranking) precisely so the screen cannot show a total from one window
 * and a chart from another. Errors propagate to the caller.
 */
import apiClient from '@/core/api/axios'

/**
 * GET /v1/summary — every figure the «Сводка» page draws for one window.
 *
 * @param {{date_from?: string, date_to?: string, revenue_base?: 'paid'|'seller',
 *   grouping?: 'sku'|'subject'|'brand'}} [params]
 * @param {AbortSignal} [signal] Cancels the request when a newer fetch starts.
 * @returns {Promise<object>} `{ kpi, days, categories, coverage, ... }`
 */
export async function fetchSummary(params = {}, signal) {
  const { data } = await apiClient.get('/v1/summary', { params, signal })
  return data
}
