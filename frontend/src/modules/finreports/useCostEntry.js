/**
 * One article's cost price, typed straight into the P&L.
 *
 * The cost editor is a page of its own, and a seller reading the P&L used to
 * see an uncosted article only as a number on a card — then had to leave the
 * statement, find the article again in a second grid, and come back. This is
 * the short path: save one cost, then re-read the statement, so the row, its
 * profit and «Итого» are the backend's figures again rather than a guess.
 *
 * Kept out of the store, which sits at the file ceiling — the same split as
 * `useReportUpload`. The editor's cached list is dropped rather than patched:
 * it is re-read the next time that page opens, so it cannot show this article
 * as still missing.
 */
import { saveCostPrices } from '@/modules/finreports/api'

/** @param {{report: object|null, costPrices: object|null, loadReport: Function}} store */
export function useCostEntry(store) {
  /**
   * Persist one cost and reload the statement. Throws on a refused save, so
   * the dialog that asked can keep itself open and say why.
   *
   * @param {{nmId: number, cost: number, vendorCode: string}} entry
   */
  async function save({ nmId, cost, vendorCode }) {
    // Costs are matched in the window's settlement currency; one stated in
    // any other would leave the article uncosted. An empty window has none,
    // and the backend's default is the workspace's.
    const currency = store.report?.currency
    await saveCostPrices([
      { nm_id: nmId, cost, vendor_code: vendorCode, ...(currency ? { currency } : {}) },
    ])
    store.costPrices = null
    await store.loadReport()
  }

  return { save }
}
