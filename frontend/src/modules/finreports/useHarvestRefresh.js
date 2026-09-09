/**
 * «Обновить» — ask WB now for a settlement report we do not already hold, then
 * wait for the harvest to finish.
 *
 * The schedule asks WB hourly, which covers most of the gap between a report
 * being published and the P&L showing it — but not all of it. A report
 * published at 02:00 waits for the 08:00 tick, and an hour the worker was down
 * for is an hour nobody asked. In both cases the seller can already see the
 * report on WB's own site, and «подождите до утра» is not an answer.
 *
 * Two things this deliberately does NOT do. It does not decide whether a
 * harvest may run — the backend refuses to start a second one on top of a
 * running one, and this only reflects that back. And it does not decide what to
 * do with new data: the caller's `onNewReports` owns that, because what a new
 * week means for the visible period is a question about the period, not about
 * harvesting.
 */
import { ref } from 'vue'

import { extractErrorMessage } from '@/core/api/axios'
import { fetchHarvestState, triggerHarvest } from '@/modules/finreports/api'

/** How often to ask whether the harvest has finished. */
const POLL_MS = 5000

/**
 * How many polls before we stop watching. The walk paces itself against WB's
 * ~1 req/min surfaces, so a fleet-wide run is minutes long; 20 minutes is past
 * any run we have measured. Giving up stops only the *watching* — the harvest
 * keeps going on the worker, which is what the closing message says.
 */
const POLL_LIMIT = 240

/** Resolves after `ms`, so the poll below reads as a loop rather than a chain. */
function delay(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms))
}

/**
 * @param {object} options
 * @param {() => string} options.currentSettled Last settlement day already on
 *   screen, read at click time. Compared against the day the harvest ends on:
 *   a run that pulled a week and a run that found nothing are both successes,
 *   and this is the only thing that tells them apart.
 * @param {() => Promise<void>} options.onNewReports Called once, after a run
 *   that moved the settlement day, to reload what it changed.
 * @param {(state: object) => void} [options.onState] Called with every state
 *   the poll reads. The P&L's freshness line is built from exactly this answer,
 *   so reusing the poll is what keeps the line describing the run the seller
 *   just watched finish rather than the situation before it.
 */
export function useHarvestRefresh({ currentSettled, onNewReports, onState }) {
  const harvestRunning = ref(false)
  const harvestNotice = ref('')
  const harvestError = ref('')

  /** Poll until the harvest stops, then report which ending it was. */
  async function watchHarvest(settledBefore) {
    for (let attempt = 0; attempt < POLL_LIMIT; attempt += 1) {
      await delay(POLL_MS)
      let state
      try {
        state = await fetchHarvestState()
      } catch {
        // A dropped poll says nothing about the harvest — keep watching.
        continue
      }
      onState?.(state)
      if (state.running) continue
      harvestRunning.value = false
      if (state.latest_settled && state.latest_settled !== settledBefore) {
        await onNewReports()
        harvestNotice.value = `Загружен отчёт по ${state.latest_settled}.`
      } else {
        harvestNotice.value = 'Новых отчётов у Wildberries пока нет.'
      }
      return
    }
    harvestRunning.value = false
    harvestNotice.value = 'Обновление идёт дольше обычного — оно продолжится в фоне.'
  }

  /** Trigger a harvest (unless one is running) and wait it out. */
  async function refreshFromWb() {
    if (harvestRunning.value) return
    // Claimed before the first await, not after the trigger returns: two clicks
    // in the same tick would otherwise both get past the check and POST twice.
    // The second harvest would find the lock held and do nothing, but a button
    // that queues work it knows is redundant is a bug on this side of the wire.
    harvestRunning.value = true
    harvestError.value = ''
    harvestNotice.value = ''
    const settledBefore = currentSettled()
    try {
      const { status } = await triggerHarvest()
      harvestNotice.value =
        status === 'already_running'
          ? 'Обновление уже идёт — ждём его окончания.'
          : 'Спрашиваем Wildberries о новых отчётах…'
    } catch (error) {
      harvestRunning.value = false
      harvestError.value = extractErrorMessage(error)
      return
    }
    await watchHarvest(settledBefore)
  }

  return { harvestRunning, harvestNotice, harvestError, refreshFromWb }
}
