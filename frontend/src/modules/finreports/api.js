/**
 * FinReports module API layer — thin async wrappers over the backend's
 * `/api/v1/finreports/*` endpoints (see backend `finreports/routers`).
 *
 * SCAFFOLD: the backend answers `501 Not Implemented` until the WB finance
 * token is provisioned. These wrappers are the stable shape the store/view will
 * consume; errors propagate to the caller.
 */
import apiClient from '@/core/api/axios'

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
