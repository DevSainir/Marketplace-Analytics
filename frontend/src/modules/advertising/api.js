/** HTTP calls of the "Advertising" page. Workspace header and cookies come from the shared client. */
import apiClient, { WINDOW_TIMEOUT_MS } from '@/core/api/axios'

/** Every figure for one window: `{date_from, date_to}`. */
export async function fetchAdvertising(params, signal) {
  const { data } = await apiClient.get('/v1/advertising', {
    params,
    signal,
    timeout: WINDOW_TIMEOUT_MS,
  })
  return data
}

/** The days the workspace has advertising for, and the last settled day. */
export async function fetchAdvertisingSpan(signal) {
  const { data } = await apiClient.get('/v1/advertising/span', { signal })
  return data
}
