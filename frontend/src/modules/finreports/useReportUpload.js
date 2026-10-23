/**
 * "Upload report" — the weekly report WB shows the seller before its API serves it.
 *
 * The seller downloads the weekly detailed report from the WB seller portal
 * and picks it here. The backend answers at once (is it WB's file, which
 * report) and a worker reads it; this polls until the worker is done and then
 * shows the worker's own sentence — loaded, already on file, or why not.
 *
 * Kept out of the store, which sits at the file ceiling: the only thing the
 * store needs from an upload is to reload what it shows once rows were written.
 */
import { ref } from 'vue'

import { extractErrorMessage } from '@/core/api/axios'
import { fetchSettlementUpload, uploadSettlementReport } from '@/modules/finreports/api'

/** Between polls. A 3 000-row week reads in about two seconds. */
const POLL_MS = 1500
/** Past this the worker is presumed busy elsewhere; the seller is told to look later. */
const GIVE_UP_MS = 5 * 60 * 1000
const STILL_READING = 'Still reading the file — reload the page later for the result.'

const IN_FLIGHT = new Set(['queued', 'processing'])

/**
 * @param {{loadWeeks: Function, loadReport: Function, loadHarvestState: Function}} store
 * @param {{sleep?: (ms: number) => Promise<void>, now?: () => number}} [clock] Injected in tests.
 */
export function useReportUpload(store, clock = {}) {
  const sleep = clock.sleep ?? ((ms) => new Promise((resolve) => setTimeout(resolve, ms)))
  const now = clock.now ?? (() => Date.now())

  const busy = ref(false)
  const notice = ref('')
  const error = ref('')

  /** Send one file and follow it to its end. */
  async function upload(file) {
    if (!file || busy.value) return
    busy.value = true
    notice.value = ''
    error.value = ''
    try {
      let state = await uploadSettlementReport(file)
      const deadline = now() + GIVE_UP_MS
      while (IN_FLIGHT.has(state.status)) {
        if (now() > deadline) {
          notice.value = STILL_READING
          return
        }
        await sleep(POLL_MS)
        state = await fetchSettlementUpload(state.id)
      }
      if (state.status === 'failed') {
        error.value = state.message
        return
      }
      notice.value = state.message
      if (state.status === 'written') {
        await store.loadWeeks()
        await store.loadReport()
        store.loadHarvestState()
      }
    } catch (failure) {
      error.value = extractErrorMessage(failure)
    } finally {
      busy.value = false
    }
  }

  return { busy, notice, error, upload }
}
