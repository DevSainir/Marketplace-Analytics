/**
 * A/Б-tests module API layer — thin async wrappers over `/api/ab-tests/*`
 * (see backend `ab_tests/routers`).
 *
 * The photo endpoints are the reason this file is not just four GETs: an upload
 * is multipart, and the image itself is served from our own store rather than
 * from WB's CDN — a queued variant has no WB URL yet, and a replaced one no
 * longer has one. Errors propagate to the caller.
 */
import apiClient from '@/core/api/axios'

/**
 * GET /ab-tests — the workspace's tests, newest first.
 *
 * @param {{q?: string}} [params] Free-text needle matched against the test
 *   name, both articles and the status.
 * @param {AbortSignal} [signal] Cancels the request when a newer fetch starts.
 * @returns {Promise<Array<object>>} List rows.
 */
export async function fetchTests(params = {}, signal) {
  const { data } = await apiClient.get('/ab-tests', { params, signal })
  return data
}

/**
 * GET /ab-tests/{id} — one test with its per-photo result table.
 *
 * @param {string} testId Test identifier.
 * @param {AbortSignal} [signal] Cancels the request when a newer fetch starts.
 * @returns {Promise<object>} `{ ..., variants: [...] }`
 */
export async function fetchTest(testId, signal) {
  const { data } = await apiClient.get(`/ab-tests/${testId}`, { signal })
  return data
}

/**
 * POST /ab-tests — create a draft test. Photos are uploaded separately.
 *
 * @param {{nm_id: number, name: string, vendor_code?: string,
 *          impression_budget?: number}} payload
 * @returns {Promise<object>} The created test.
 */
export async function createTest(payload) {
  const { data } = await apiClient.post('/ab-tests', payload)
  return data
}

/**
 * PATCH /ab-tests/{id}/status — start, pause or cancel.
 *
 * Starting installs the first photo on the card synchronously, so a rejection
 * here means the seller's card was NOT touched.
 *
 * @param {string} testId Test identifier.
 * @param {'running'|'paused'|'cancelled'} status Target status.
 * @returns {Promise<object>} The updated test.
 */
export async function setTestStatus(testId, status) {
  const { data } = await apiClient.patch(`/ab-tests/${testId}/status`, { status })
  return data
}

/**
 * DELETE /ab-tests/{id} — remove a test and its photos.
 *
 * @param {string} testId Test identifier.
 * @returns {Promise<void>}
 */
export async function deleteTest(testId) {
  await apiClient.delete(`/ab-tests/${testId}`)
}

/**
 * POST /ab-tests/{id}/variants — upload one photo into the rotation.
 *
 * Returns the whole refreshed test rather than the new variant: the result
 * table has to re-render anyway, and one round trip keeps the upload list and
 * the table from disagreeing.
 *
 * @param {string} testId Test identifier.
 * @param {File} file The picture, up to 32 MB.
 * @returns {Promise<object>} The refreshed test detail.
 */
export async function uploadVariant(testId, file) {
  const form = new FormData()
  form.append('file', file)
  const { data } = await apiClient.post(`/ab-tests/${testId}/variants`, form)
  return data
}

/**
 * DELETE /ab-tests/{id}/variants/{variantId} — drop a photo from the rotation.
 *
 * @param {string} testId Test identifier.
 * @param {string} variantId Variant identifier.
 * @returns {Promise<void>}
 */
export async function deleteVariant(testId, variantId) {
  await apiClient.delete(`/ab-tests/${testId}/variants/${variantId}`)
}
