/**
 * FinReports module API layer — thin async wrappers over the backend's
 * `/api/v1/finreports/*` endpoints (see backend `finreports/routers`).
 *
 * The P&L statement plus its cost-price inputs and the settlement-report
 * upload. Errors propagate to the caller.
 */
import apiClient, { WINDOW_TIMEOUT_MS } from '@/core/api/axios'

/**
 * GET /v1/finreports/pnl/skus — the per-SKU P&L cut («По артикулам») for an
 * arbitrary settlement-date window.
 *
 * @param {{date_from?: string, date_to?: string}} [params]
 * @param {AbortSignal} [signal] Cancels the request when a newer fetch starts.
 * @returns {Promise<object>} `{ rows, unallocated, totals, notes, ... }`
 */
export async function fetchSkuPnl(params = {}, signal) {
  const { data } = await apiClient.get('/v1/finreports/pnl/skus', {
    params,
    signal,
    timeout: WINDOW_TIMEOUT_MS,
  })
  return data
}

/**
 * GET /v1/finreports/pnl/skus/{nmId}/sizes — the sizes of one article over the
 * same window as the table. Requested when a row is expanded: a report of forty
 * articles has ~400 size rows, and people open one or two.
 *
 * @param {number} nmId WB article ID.
 * @param {{date_from?: string, date_to?: string}} [params]
 * @param {AbortSignal} [signal] Cancels the request when a newer fetch starts.
 * @returns {Promise<object>} `{ nm_id, sa_name, currency, rows }`
 */
export async function fetchSkuSizes(nmId, params = {}, signal) {
  const { data } = await apiClient.get(`/v1/finreports/pnl/skus/${nmId}/sizes`, {
    params,
    signal,
    timeout: WINDOW_TIMEOUT_MS,
  })
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
 * GET /v1/finreports/harvest — is a WB harvest running, and how far does this
 * workspace's harvested settlement history reach.
 *
 * Polled while «Обновить» is in flight: `running` falling to false ends the
 * wait, and `latest_settled` moving is what says a new report actually arrived.
 * Also read on every load of the P&L, for the freshness line under its header:
 * `latest_report` is what we hold, `last_check` is what the hourly gate found
 * the last time it asked WB for something newer. Both are nullable, and the
 * route never asks WB anything itself.
 *
 * @returns {Promise<{running: boolean, latest_settled: string|null,
 *   latest_report: {report_id: number, date_from: string|null,
 *     date_to: string|null, harvested_at: string}|null,
 *   last_check: {outcome: string, checked_at: string,
 *     probe_from: string|null, probe_to: string|null}|null}>}
 */
export async function fetchHarvestState() {
  const { data } = await apiClient.get('/v1/finreports/harvest')
  return data
}

/**
 * POST /v1/finreports/harvest — ask WB now for any report we do not hold.
 *
 * Answers in one round trip, always. A click while a harvest is running
 * enqueues nothing and comes back as `already_running`; one made while WB's
 * settlement endpoint is still inside its ~15-minute window enqueues nothing
 * either and comes back as `rate_limited` with the wait attached — read from
 * the shared rate bucket, so producing it costs no WB request.
 *
 * @returns {Promise<{status: 'started'|'already_running'|'rate_limited',
 *   task_id: string|null, retry_after_seconds: number|null}>}
 */
export async function triggerHarvest() {
  const { data } = await apiClient.post('/v1/finreports/harvest')
  return data
}

/**
 * GET /v1/finreports/currency — the currency the active workspace is settled in.
 *
 * Membership is enough, not the «P&L» grant: monitoring and the A/B tests print
 * money in this unit for managers who cannot open the P&L.
 *
 * @returns {Promise<string>} ISO code (`KGS`), or `''` before the first report.
 */
export async function fetchSettlementCurrency() {
  const { data } = await apiClient.get('/v1/finreports/currency')
  return data.currency
}

/**
 * GET /v1/finreports/balance — «Баланс по товарным остаткам»: the SKU x
 * warehouse stock grid for ONE snapshot day, priced at the seller's costs.
 *
 * @param {{stat_date?: string}} [params] Omit the day to get the newest snapshot.
 * @param {AbortSignal} [signal] Cancels the request when a newer fetch starts.
 * @returns {Promise<object>} `{ stat_date, warehouses, rows, total_*, notes, ... }`
 */
export async function fetchBalance(params = {}, signal) {
  const { data } = await apiClient.get('/v1/finreports/balance', { params, signal })
  return data
}

/**
 * PUT /v1/finreports/balance/pins — pin («Закрепить») a SKU row or a warehouse
 * column of the balance grid, or clear the pin. Stored per workspace.
 *
 * @param {'sku'|'warehouse'} kind What the pin is attached to.
 * @param {string} value `nm_id` as text for a SKU, the warehouse name otherwise.
 * @param {boolean} pinned `true` to pin, `false` to unpin.
 * @returns {Promise<void>}
 */
export async function setBalancePin(kind, value, pinned) {
  await apiClient.put('/v1/finreports/balance/pins', { kind, value, pinned })
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
 * GET /v1/finreports/cost-prices/export — the per-SKU P&L as an XLSX, with an
 * editable «Себестоимость за 1 ед.» column for bulk offline cost entry.
 *
 * Returns the workbook as a Blob plus the server-suggested file name; the
 * Cyrillic real name travels in `filename*` (RFC 5987), decoded here.
 *
 * @param {{date_from?: string, date_to?: string}} [params] Settlement window.
 * @returns {Promise<{blob: Blob, filename: string}>}
 */
export async function downloadCostPricesXlsx(params = {}) {
  const response = await apiClient.get('/v1/finreports/cost-prices/export', {
    params,
    responseType: 'blob',
    // The whole-history P&L aggregates ~620k settlement rows, so the export
    // legitimately outruns the client's default timeout.
    timeout: 600000,
  })
  const disposition = response.headers['content-disposition'] || ''
  const utf8 = disposition.match(/filename\*=UTF-8''([^;]+)/i)
  const ascii = disposition.match(/filename="?([^";]+)"?/i)
  const filename = utf8 ? decodeURIComponent(utf8[1]) : ascii ? ascii[1] : 'cost-prices.xlsx'
  return { blob: response.data, filename }
}

/**
 * POST /v1/finreports/cost-prices/import — upload a filled-in workbook.
 *
 * Sends the file as multipart form data; the backend parses «Себестоимость»
 * into existing SKUs and returns a summary of what it applied and skipped.
 *
 * @param {File} file The XLSX file exported from this module, with costs filled in.
 * @returns {Promise<{applied: number, skipped: number, issues: Array<object>}>}
 */
export async function importCostPricesXlsx(file) {
  const form = new FormData()
  form.append('file', file)
  // The shared client defaults to `Content-Type: application/json`. Left in
  // place, axios serialises the FormData to JSON and the file never leaves the
  // browser — the backend then rejects the multipart field as «Field required».
  // Overriding to multipart keeps the FormData intact; axios drops this header
  // just before sending so the browser sets it *with* the boundary.
  const { data } = await apiClient.post('/v1/finreports/cost-prices/import', form, {
    headers: { 'Content-Type': 'multipart/form-data' },
  })
  return data
}

/**
 * POST /v1/finreports/settlement-uploads — hand WB's weekly report to the backend.
 *
 * The file the seller downloads from their WB seller account («Еженедельный
 * детализированный отчет №…»): the zip, or the .xlsx inside it. Answered at
 * once with `status: 'queued'`; the worker reads it and
 * {@link fetchSettlementUpload} says how it ended.
 *
 * @param {File} file
 * @returns {Promise<{id: string, status: string, message: string}>}
 */
export async function uploadSettlementReport(file) {
  const form = new FormData()
  form.append('file', file)
  // Multipart, not the client's JSON default — see importCostPricesXlsx.
  const { data } = await apiClient.post('/v1/finreports/settlement-uploads', form, {
    headers: { 'Content-Type': 'multipart/form-data' },
  })
  return data
}

/**
 * GET /v1/finreports/settlement-uploads/{id} — where an upload stands.
 *
 * @param {string} id
 * @returns {Promise<{id: string, status: string, message: string, rows_written: number}>}
 */
export async function fetchSettlementUpload(id) {
  const { data } = await apiClient.get(`/v1/finreports/settlement-uploads/${id}`)
  return data
}

/**
 * GET /v1/finreports/weeks — the WB weekly report periods (newest first) that
 * the P&L period picker offers.
 *
 * @param {AbortSignal} [signal]
 * @returns {Promise<{weeks: Array<{report_id: number, date_from: string, date_to: string}>}>}
 */
export async function fetchWeeks(signal) {
  const { data } = await apiClient.get('/v1/finreports/weeks', { signal })
  return data
}
