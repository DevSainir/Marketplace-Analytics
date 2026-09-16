/**
 * Summary module API layer — one endpoint, `/api/v1/summary`.
 *
 * The backend composes the whole page in one response (cards, daily series,
 * category ranking) precisely so the screen cannot show a total from one window
 * and a chart from another. Errors propagate to the caller.
 */
import apiClient, { WINDOW_TIMEOUT_MS } from '@/core/api/axios'

/**
 * GET /v1/summary — every figure the «Сводка» page draws for one window.
 *
 * The window is the only parameter. Price base, grouping and sort order are
 * answered from the payload, which carries both bases and every article row —
 * they used to be query parameters, and each click cost a round trip over the
 * whole settlement window.
 *
 * @param {{date_from?: string, date_to?: string}} [params]
 * @param {AbortSignal} [signal] Cancels the request when a newer fetch starts.
 * @returns {Promise<object>} `{ kpi, days, rows, coverage, ... }`
 */
export async function fetchSummary(params = {}, signal) {
  const { data } = await apiClient.get('/v1/summary', {
    params,
    signal,
    timeout: WINDOW_TIMEOUT_MS,
  })
  return data
}

/**
 * GET /v1/summary/span — the settled days this кабинет has.
 *
 * Its own request because the period picker needs it before a window exists,
 * and because it is answered off the report headers rather than the settlement
 * detail — a hundred rows against three quarters of a gigabyte.
 *
 * @param {AbortSignal} [signal]
 * @returns {Promise<{date_from: string|null, date_to: string|null}>}
 */
export async function fetchSummarySpan(signal) {
  const { data } = await apiClient.get('/v1/summary/span', { signal })
  return data
}
